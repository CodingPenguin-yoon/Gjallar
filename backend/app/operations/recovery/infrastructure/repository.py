"""PostgreSQL/SQLAlchemy durable recovery repository with lease fencing."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.redaction import redact_secrets
from app.db.models import OperationLockRecord
from app.db.session import session_scope
from app.operations.core.domain import OperationActor, OperationSnapshot
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.recovery.domain import (
    RecoveryItem,
    RecoveryLease,
    RecoveryLeaseBusy,
    RecoveryLeaseLost,
    RecoverySpec,
)
from app.operations.recovery.infrastructure.models import OperationRecoveryItemRecord


SessionScope = Callable[[], AbstractContextManager[Session]]
Clock = Callable[[], datetime]
OPEN_LOCK_STATUSES = ("active", "stale", "reconciliation_required")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _sanitized(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    redacted = redact_secrets(dict(payload or {}))
    return dict(redacted) if isinstance(redacted, dict) else {}


def _item(row: OperationRecoveryItemRecord) -> RecoveryItem:
    return RecoveryItem(
        operation_id=row.operation_id,
        recovery_kind=row.recovery_kind,
        status=row.status,
        available_at=_as_utc(row.available_at),
        lease_owner=row.lease_owner,
        lease_generation=int(row.lease_generation),
        lease_expires_at=_as_utc(row.lease_expires_at) if row.lease_expires_at else None,
        attempt_count=int(row.attempt_count),
        last_error_code=row.last_error_code,
        details=dict(row.details or {}),
        created_at=_as_utc(row.created_at),
        updated_at=_as_utc(row.updated_at),
        completed_at=_as_utc(row.completed_at) if row.completed_at else None,
    )


class SqlAlchemyRecoveryStore:
    """Coordinate durable due work and fenced Operation writes."""

    def __init__(self, *, sessions: SessionScope = session_scope, clock: Clock = _now_utc) -> None:
        self._sessions = sessions
        self._clock = clock
        self._operations = SqlAlchemyOperationStore(sessions=sessions, clock=clock)

    def prepare_and_claim(
        self,
        spec: RecoverySpec,
        *,
        lease_owner: str,
        lease_seconds: float,
    ) -> RecoveryLease:
        owner = str(lease_owner).strip()
        if not owner:
            raise ValueError("Recovery lease_owner is required")
        now = _as_utc(self._clock())
        expires_at = now + timedelta(seconds=max(float(lease_seconds), 1.0))
        token = f"recovery-lease-{uuid.uuid4().hex}"
        with self._sessions() as session:
            row = session.scalar(
                select(OperationRecoveryItemRecord)
                .where(OperationRecoveryItemRecord.operation_id == spec.operation_id)
                .with_for_update()
            )
            if row is None:
                row = OperationRecoveryItemRecord(
                    operation_id=spec.operation_id,
                    recovery_kind=spec.recovery_kind,
                    status="leased",
                    available_at=now,
                    lease_owner=owner,
                    lease_token=token,
                    lease_generation=1,
                    lease_expires_at=expires_at,
                    attempt_count=1,
                    details=_sanitized(spec.details),
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                session.flush()
                return RecoveryLease(item=_item(row), token=token)
            if row.recovery_kind != spec.recovery_kind:
                raise ValueError(f"Recovery kind conflicts for operation {spec.operation_id}")
            live_lease = (
                row.status == "leased"
                and row.lease_expires_at is not None
                and _as_utc(row.lease_expires_at) > now
            )
            if live_lease:
                raise RecoveryLeaseBusy(spec.operation_id)
            if row.status == "completed":
                raise RecoveryLeaseBusy(spec.operation_id)
            row.status = "leased"
            row.available_at = now
            row.lease_owner = owner
            row.lease_token = token
            row.lease_generation = int(row.lease_generation) + 1
            row.lease_expires_at = expires_at
            row.attempt_count = int(row.attempt_count) + 1
            row.details = {**dict(row.details or {}), **_sanitized(spec.details)}
            row.updated_at = now
            session.flush()
            return RecoveryLease(item=_item(row), token=token)

    def get(self, operation_id: str) -> RecoveryItem | None:
        with self._sessions() as session:
            row = session.get(OperationRecoveryItemRecord, str(operation_id))
            return _item(row) if row is not None else None

    def claim_due(
        self,
        *,
        lease_owner: str,
        lease_seconds: float,
        limit: int = 1,
    ) -> list[RecoveryLease]:
        owner = str(lease_owner).strip()
        if not owner:
            raise ValueError("Recovery lease_owner is required")
        now = _as_utc(self._clock())
        expires_at = now + timedelta(seconds=max(float(lease_seconds), 1.0))
        bounded_limit = max(1, min(int(limit), 10))
        with self._sessions() as session:
            rows = list(
                session.scalars(
                    select(OperationRecoveryItemRecord)
                    .where(
                        OperationRecoveryItemRecord.available_at <= now,
                        or_(
                            OperationRecoveryItemRecord.status.in_(("pending", "retry_wait")),
                            and_(
                                OperationRecoveryItemRecord.status == "leased",
                                OperationRecoveryItemRecord.lease_expires_at <= now,
                            ),
                        ),
                    )
                    .order_by(
                        OperationRecoveryItemRecord.available_at.asc(),
                        OperationRecoveryItemRecord.operation_id.asc(),
                    )
                    .limit(bounded_limit)
                    .with_for_update(skip_locked=True)
                ).all()
            )
            leases: list[RecoveryLease] = []
            for row in rows:
                token = f"recovery-lease-{uuid.uuid4().hex}"
                row.status = "leased"
                row.lease_owner = owner
                row.lease_token = token
                row.lease_generation = int(row.lease_generation) + 1
                row.lease_expires_at = expires_at
                row.attempt_count = int(row.attempt_count) + 1
                row.updated_at = now
                session.flush()
                leases.append(RecoveryLease(item=_item(row), token=token))
            return leases

    def heartbeat(self, lease: RecoveryLease, *, lease_seconds: float) -> RecoveryLease:
        now = _as_utc(self._clock())
        with self._sessions() as session:
            row = self._locked_owned_row(session, lease, now=now)
            row.lease_expires_at = now + timedelta(seconds=max(float(lease_seconds), 1.0))
            row.updated_at = now
            session.flush()
            return RecoveryLease(item=_item(row), token=lease.token)

    def commit_observation(
        self,
        lease: RecoveryLease,
        *,
        event_type: str,
        stage: str,
        payload: Mapping[str, Any] | None = None,
        details_patch: Mapping[str, Any] | None = None,
        next_status: str | None = None,
        expected_statuses: Sequence[str] | None = None,
        actor: OperationActor | None = None,
        recovery_status: str,
        retry_delay_seconds: float = 0,
        error_code: str | None = None,
        recovery_details_patch: Mapping[str, Any] | None = None,
        release_target_lock: bool = False,
    ) -> tuple[OperationSnapshot, RecoveryItem]:
        if recovery_status not in {"leased", "pending", "retry_wait", "paused", "completed"}:
            raise ValueError(f"Unsupported post-observation recovery status: {recovery_status}")
        now = _as_utc(self._clock())
        with self._sessions() as session:
            row = self._locked_owned_row(session, lease, now=now)
            operation = self._operations.append_in_session(
                session,
                lease.operation_id,
                next_status=next_status,
                event_type=event_type,
                stage=stage,
                payload=payload,
                details_patch=details_patch,
                actor=actor,
                expected_statuses=expected_statuses,
                is_transition=next_status is not None,
            )
            row.status = recovery_status
            row.available_at = now + timedelta(seconds=max(float(retry_delay_seconds), 0.0))
            if recovery_status != "leased":
                row.lease_owner = None
                row.lease_token = None
                row.lease_expires_at = None
            row.last_error_code = str(error_code).strip()[:120] if error_code else None
            row.details = {**dict(row.details or {}), **_sanitized(recovery_details_patch)}
            row.updated_at = now
            row.completed_at = now if recovery_status == "completed" else None
            if release_target_lock:
                locks = list(
                    session.scalars(
                        select(OperationLockRecord)
                        .where(
                            OperationLockRecord.owner_id == lease.operation_id,
                            OperationLockRecord.scope_type == "proxmox_locator",
                            OperationLockRecord.status.in_(OPEN_LOCK_STATUSES),
                        )
                        .with_for_update()
                    ).all()
                )
                for lock in locks:
                    lock.status = "released"
                    lock.reason = "verified_recovery_completed"
                    lock.evidence = {
                        **dict(lock.evidence or {}),
                        "recovery_operation_id": lease.operation_id,
                        "recovery_event_type": event_type,
                    }
                    lock.released_at = now
                    lock.updated_at = now
            session.flush()
            return operation, _item(row)

    @staticmethod
    def _locked_owned_row(
        session: Session,
        lease: RecoveryLease,
        *,
        now: datetime,
    ) -> OperationRecoveryItemRecord:
        row = session.scalar(
            select(OperationRecoveryItemRecord)
            .where(OperationRecoveryItemRecord.operation_id == lease.operation_id)
            .with_for_update()
        )
        if row is None or (
            row.status != "leased"
            or row.lease_token != lease.token
            or int(row.lease_generation) != lease.generation
            or row.lease_expires_at is None
            or _as_utc(row.lease_expires_at) <= now
        ):
            raise RecoveryLeaseLost(lease.operation_id)
        return row


__all__ = ["SqlAlchemyRecoveryStore"]
