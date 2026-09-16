"""PostgreSQL/SQLAlchemy durable recovery repository with lease fencing."""

from __future__ import annotations

import re
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
from app.operations.core.domain import OperationStateConflict, ensure_operation_transition
from app.operations.core.infrastructure.models import OperationRecord
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.recovery.domain import (
    RecoveryItem,
    RecoveryLease,
    RecoveryLeaseBusy,
    RecoveryLeaseLost,
    RecoveryNotFound,
    RecoveryOperationConflict,
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
        expected_operation_version: int | None = None,
        expected_operation_checksum: str | None = None,
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
            self._assert_operation_identity(
                session,
                spec.operation_id,
                expected_version=expected_operation_version,
                expected_checksum=expected_operation_checksum,
            )
            if row is None:
                # A missing recovery row cannot itself be locked. The
                # Operation row above serializes first creation; re-read after
                # acquiring that lock so a concurrent creator becomes a
                # normal live-lease conflict instead of a duplicate-PK error.
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

    def claim_operation(
        self,
        operation_id: str,
        *,
        lease_owner: str,
        lease_seconds: float,
        expected_operation_version: int | None = None,
        expected_operation_checksum: str | None = None,
    ) -> RecoveryLease:
        """Claim one existing item, including an operator-paused item.

        Unlike ``prepare_and_claim`` this method never creates work. It is the
        exact-item primitive used by an operator-triggered observation.
        """

        owner = str(lease_owner).strip()
        if not owner:
            raise ValueError("Recovery lease_owner is required")
        normalized_operation_id = str(operation_id).strip()
        if not normalized_operation_id:
            raise ValueError("Recovery operation_id is required")
        now = _as_utc(self._clock())
        expires_at = now + timedelta(seconds=max(float(lease_seconds), 1.0))
        token = f"recovery-lease-{uuid.uuid4().hex}"
        with self._sessions() as session:
            row = session.scalar(
                select(OperationRecoveryItemRecord)
                .where(OperationRecoveryItemRecord.operation_id == normalized_operation_id)
                .with_for_update()
            )
            if row is None:
                raise RecoveryNotFound(normalized_operation_id)
            self._assert_operation_identity(
                session,
                normalized_operation_id,
                expected_version=expected_operation_version,
                expected_checksum=expected_operation_checksum,
            )
            live_lease = (
                row.status == "leased"
                and row.lease_expires_at is not None
                and _as_utc(row.lease_expires_at) > now
            )
            if live_lease or row.status == "completed":
                raise RecoveryLeaseBusy(normalized_operation_id)
            row.status = "leased"
            row.available_at = now
            row.lease_owner = owner
            row.lease_token = token
            row.lease_generation = int(row.lease_generation) + 1
            row.lease_expires_at = expires_at
            row.attempt_count = int(row.attempt_count) + 1
            row.updated_at = now
            session.flush()
            return RecoveryLease(item=_item(row), token=token)

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
        require_exact_reconciliation_lock: bool = True,
        bind_target_lock: bool = False,
        expected_operation_version: int | None = None,
        expected_operation_checksum: str | None = None,
        projector: Callable[[Session], Mapping[str, Any] | None] | None = None,
    ) -> tuple[OperationSnapshot, RecoveryItem]:
        if recovery_status not in {"leased", "pending", "retry_wait", "paused", "completed"}:
            raise ValueError(f"Unsupported post-observation recovery status: {recovery_status}")
        now = _as_utc(self._clock())
        with self._sessions() as session:
            row = self._locked_owned_row(session, lease, now=now)
            operation_row = session.scalar(
                select(OperationRecord)
                .where(OperationRecord.operation_id == lease.operation_id)
                .with_for_update()
            )
            if operation_row is None:
                raise RecoveryOperationConflict(lease.operation_id)
            if (
                expected_operation_version is not None
                and int(operation_row.version) != int(expected_operation_version)
            ) or (
                expected_operation_checksum is not None
                and str(operation_row.last_event_checksum) != str(expected_operation_checksum)
            ):
                raise RecoveryOperationConflict(lease.operation_id)
            if expected_statuses is not None and operation_row.status not in set(expected_statuses):
                raise OperationStateConflict(lease.operation_id, operation_row.status)
            if next_status is not None:
                ensure_operation_transition(operation_row.status, str(next_status))
            sanitized_details_patch = _sanitized(details_patch)
            sanitized_recovery_patch = _sanitized(recovery_details_patch)
            effective_recovery_details = (
                {**dict(row.details or {}), **sanitized_recovery_patch}
                if bind_target_lock
                else dict(row.details or {})
            )
            locks = self._exact_target_locks(
                session,
                operation_row,
                effective_recovery_details,
            )
            if bind_target_lock:
                self._assert_target_lock_binding_checkpoint(
                    operation_row,
                    current_recovery_details=dict(row.details or {}),
                    effective_recovery_details=effective_recovery_details,
                    operation_details_patch=sanitized_details_patch,
                    locks=locks,
                )
            if projector is not None and len(locks) != 1:
                raise ValueError(
                    f"Projected recovery target lock binding is not exact for operation {lease.operation_id}"
                )
            if release_target_lock and len(locks) != 1:
                raise ValueError(
                    f"Recovery target lock binding is not exact for operation {lease.operation_id}"
                )
            if next_status == "needs_reconciliation" and (
                len(locks) > 1 or (require_exact_reconciliation_lock and len(locks) != 1)
            ):
                raise ValueError(
                    f"Reconciliation target lock binding is not exact for operation {lease.operation_id}"
                )
            projection_result: Mapping[str, Any] = {}
            if projector is not None:
                candidate = projector(session)
                if candidate is not None and not isinstance(candidate, Mapping):
                    raise TypeError("Recovery projector must return a mapping or None")
                projection_result = candidate or {}
            projected_payload = _sanitized(projection_result.get("event_payload"))
            projected_details = _sanitized(projection_result.get("operation_details_patch"))
            projected_recovery_details = _sanitized(
                projection_result.get("recovery_details_patch")
            )
            operation = self._operations.append_in_session(
                session,
                lease.operation_id,
                next_status=next_status,
                event_type=event_type,
                stage=stage,
                payload={**_sanitized(payload), **projected_payload},
                details_patch={**sanitized_details_patch, **projected_details},
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
            row.details = {
                **dict(row.details or {}),
                **sanitized_recovery_patch,
                **projected_recovery_details,
            }
            row.updated_at = now
            row.completed_at = now if recovery_status == "completed" else None
            if release_target_lock:
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
            elif next_status == "needs_reconciliation":
                for lock in locks:
                    lock.status = "reconciliation_required"
                    lock.reason = "recovery_result_requires_reconciliation"
                    lock.evidence = {
                        **dict(lock.evidence or {}),
                        "recovery_operation_id": lease.operation_id,
                        "recovery_event_type": event_type,
                    }
                    lock.updated_at = now
            session.flush()
            return operation, _item(row)

    @classmethod
    def _assert_target_lock_binding_checkpoint(
        cls,
        operation: OperationRecord,
        *,
        current_recovery_details: Mapping[str, Any],
        effective_recovery_details: Mapping[str, Any],
        operation_details_patch: Mapping[str, Any],
        locks: Sequence[OperationLockRecord],
    ) -> None:
        """Allow a one-time exact lock binding for a pre-dispatch recovery item."""

        proposed_lock_id = str(effective_recovery_details.get("target_lock_id") or "").strip()
        proposed_cluster_id = str(effective_recovery_details.get("cluster_id") or "").strip()
        current_lock_id = str(current_recovery_details.get("target_lock_id") or "").strip()
        current_cluster_id = str(current_recovery_details.get("cluster_id") or "").strip()
        if (
            not proposed_lock_id
            or not proposed_cluster_id
            or current_lock_id not in {"", proposed_lock_id}
            or current_cluster_id not in {"", proposed_cluster_id}
            or len(locks) != 1
            or str(locks[0].status) != "active"
        ):
            raise ValueError(
                f"Recovery target lock binding checkpoint is not exact for operation {operation.operation_id}"
            )

        binding = operation_details_patch.get("target_operation_lock")
        binding = dict(binding) if isinstance(binding, Mapping) else {}
        durable = binding.get("durable") if isinstance(binding.get("durable"), Mapping) else {}
        match = re.fullmatch(r"vmid:(\d+)", operation.target_id)
        try:
            durable_vmid = int(durable.get("vmid") or 0)
        except (TypeError, ValueError):
            durable_vmid = 0
        exact_projection = bool(
            match is not None
            and str(binding.get("target_type") or "") == operation.target_type
            and str(binding.get("target_id") or "") == operation.target_id
            and str(binding.get("owner_id") or "") == operation.operation_id
            and str(durable.get("operation_lock_id") or "") == proposed_lock_id
            and str(durable.get("cluster_id") or "") == proposed_cluster_id
            and str(durable.get("owner_id") or "") == operation.operation_id
            and str(durable.get("operation_type") or "") == operation.operation_type
            and str(durable.get("scope_type") or "") == "proxmox_locator"
            and durable_vmid == int(match.group(1))
        )
        recorded = operation.details.get("target_operation_lock")
        recorded = dict(recorded) if isinstance(recorded, Mapping) else {}
        recorded_durable = (
            recorded.get("durable") if isinstance(recorded.get("durable"), Mapping) else {}
        )
        recorded_lock_id = str(
            recorded_durable.get("operation_lock_id") or recorded.get("lock_id") or ""
        ).strip()
        recorded_cluster_id = str(recorded_durable.get("cluster_id") or "").strip()
        if (
            not exact_projection
            or recorded_lock_id not in {"", proposed_lock_id}
            or recorded_cluster_id not in {"", proposed_cluster_id}
        ):
            raise ValueError(
                f"Operation target lock binding checkpoint is not exact for operation {operation.operation_id}"
            )

    @staticmethod
    def _exact_target_locks(
        session: Session,
        operation: OperationSnapshot | OperationRecord,
        recovery_details: Mapping[str, Any],
    ) -> list[OperationLockRecord]:
        if operation.target_type != "proxmox_vm":
            return []
        match = re.fullmatch(r"vmid:(\d+)", operation.target_id)
        if match is None:
            return []
        conditions = [
            OperationLockRecord.owner_id == operation.operation_id,
            OperationLockRecord.operation_type == operation.operation_type,
            OperationLockRecord.scope_type == "proxmox_locator",
            OperationLockRecord.vmid == int(match.group(1)),
            OperationLockRecord.status.in_(OPEN_LOCK_STATUSES),
        ]
        lock_id = str(recovery_details.get("target_lock_id") or "").strip()
        cluster_id = str(recovery_details.get("cluster_id") or "").strip()
        if not lock_id or not cluster_id:
            return []
        conditions.extend(
            [
                OperationLockRecord.operation_lock_id == lock_id,
                OperationLockRecord.cluster_id == cluster_id,
            ]
        )
        return list(
            session.scalars(
                select(OperationLockRecord)
                .where(*conditions)
                .with_for_update()
            ).all()
        )

    @staticmethod
    def _assert_operation_identity(
        session: Session,
        operation_id: str,
        *,
        expected_version: int | None,
        expected_checksum: str | None,
    ) -> None:
        operation = session.scalar(
            select(OperationRecord)
            .where(OperationRecord.operation_id == operation_id)
            .with_for_update()
        )
        if operation is None or (
            expected_version is not None and int(operation.version) != int(expected_version)
        ) or (
            expected_checksum is not None
            and str(operation.last_event_checksum) != str(expected_checksum)
        ):
            raise RecoveryOperationConflict(operation_id)

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
