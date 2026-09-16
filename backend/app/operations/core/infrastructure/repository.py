"""SQLAlchemy adapter for atomic Operation projection and event persistence."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.redaction import redact_secrets
from app.db.models import OperationLockRecord
from app.db.session import session_scope
from app.operations.core.domain import (
    OperationActor,
    OperationCreateResult,
    OperationEvent,
    OperationIntentConflict,
    OperationNotFound,
    OperationSnapshot,
    OperationSpec,
    OperationStateConflict,
    ensure_operation_transition,
    event_checksum_payload,
    operation_digest,
)
from app.operations.core.infrastructure.models import OperationEventRecord, OperationRecord
from app.operations.locks.domain import OPEN_TARGET_LOCK_STATUSES
from app.operations.recovery.infrastructure.models import OperationRecoveryItemRecord


SessionScope = Callable[[], AbstractContextManager[Session]]
Clock = Callable[[], datetime]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _sanitized_mapping(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    redacted = redact_secrets(dict(payload or {}))
    return dict(redacted) if isinstance(redacted, dict) else {}


def _actor_from_record(row: OperationRecord | OperationEventRecord) -> OperationActor:
    return OperationActor(
        user_id=str(row.actor_user_id or ""),
        username=str(row.actor_username or ""),
        role=str(row.actor_role or ""),
    )


def _snapshot(row: OperationRecord) -> OperationSnapshot:
    return OperationSnapshot(
        operation_id=row.operation_id,
        operation_type=row.operation_type,
        execution_mode=row.execution_mode,
        status=row.status,
        target_type=row.target_type,
        target_id=row.target_id,
        idempotency_key=row.idempotency_key,
        intent_digest=row.intent_digest,
        plan_digest=row.plan_digest,
        current_stage=row.current_stage,
        actor=_actor_from_record(row),
        details=dict(row.details or {}),
        expires_at=_as_utc(row.expires_at) if row.expires_at is not None else None,
        version=int(row.version),
        last_event_checksum=row.last_event_checksum,
        created_at=_as_utc(row.created_at),
        updated_at=_as_utc(row.updated_at),
    )


def _event(row: OperationEventRecord) -> OperationEvent:
    return OperationEvent(
        event_id=row.event_id,
        operation_id=row.operation_id,
        sequence=int(row.sequence),
        event_type=row.event_type,
        from_status=row.from_status,
        to_status=row.to_status,
        stage=row.stage,
        actor=_actor_from_record(row),
        payload=dict(row.payload or {}),
        previous_checksum=row.previous_checksum,
        checksum=row.checksum,
        created_at=_as_utc(row.created_at),
    )


class SqlAlchemyOperationStore:
    """Persist immutable events and their current projection in one transaction."""

    def __init__(self, *, sessions: SessionScope = session_scope, clock: Clock = _now_utc) -> None:
        self._sessions = sessions
        self._clock = clock

    def create(
        self,
        spec: OperationSpec,
        *,
        event_payload: Mapping[str, Any] | None = None,
    ) -> OperationCreateResult:
        existing = self._get_by_scope(spec)
        if existing is not None:
            return self._resolve_existing(existing, spec)

        created_at = _as_utc(self._clock())
        payload = _sanitized_mapping(event_payload)
        checksum = self._event_checksum(
            operation_id=spec.operation_id,
            sequence=1,
            event_type="operation_created",
            from_status=None,
            to_status=spec.initial_status,
            stage=spec.initial_stage,
            actor=spec.actor,
            payload=payload,
            previous_checksum="",
            created_at=created_at,
        )
        row = OperationRecord(
            operation_id=spec.operation_id,
            operation_type=spec.operation_type,
            execution_mode=spec.execution_mode,
            status=spec.initial_status,
            target_type=spec.target_type,
            target_id=spec.target_id,
            idempotency_key=spec.idempotency_key,
            intent_digest=spec.intent_digest,
            plan_digest=spec.plan_digest,
            current_stage=spec.initial_stage,
            actor_user_id=spec.actor.user_id or None,
            actor_username=spec.actor.username or None,
            actor_role=spec.actor.role or None,
            details=_sanitized_mapping(spec.details),
            expires_at=spec.expires_at,
            version=1,
            last_event_checksum=checksum,
            created_at=created_at,
            updated_at=created_at,
        )
        event_row = self._new_event_row(
            operation_id=spec.operation_id,
            sequence=1,
            event_type="operation_created",
            from_status=None,
            to_status=spec.initial_status,
            stage=spec.initial_stage,
            actor=spec.actor,
            payload=payload,
            previous_checksum="",
            checksum=checksum,
            created_at=created_at,
        )
        try:
            with self._sessions() as session:
                session.add(row)
                # The ORM models deliberately have no relationship property, so
                # PostgreSQL FK ordering cannot be inferred from unit-of-work
                # dependencies. Flush the parent projection before its first
                # append-only event while keeping both writes in one transaction.
                session.flush()
                session.add(event_row)
                session.flush()
                result = _snapshot(row)
        except IntegrityError:
            existing = self._get_by_scope(spec)
            if existing is None:
                existing = self.get(spec.operation_id)
            if existing is None:
                raise
            return self._resolve_existing(existing, spec)
        return OperationCreateResult(operation=result, created=True)

    def get(self, operation_id: str) -> OperationSnapshot | None:
        with self._sessions() as session:
            row = session.get(OperationRecord, operation_id)
            return _snapshot(row) if row is not None else None

    def list(
        self,
        *,
        status: str | None = None,
        operation_type: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        limit: int = 50,
    ) -> list[OperationSnapshot]:
        statement = select(OperationRecord)
        if status:
            statement = statement.where(OperationRecord.status == status)
        if operation_type:
            statement = statement.where(OperationRecord.operation_type == operation_type)
        if target_type:
            statement = statement.where(OperationRecord.target_type == target_type)
        if target_id:
            statement = statement.where(OperationRecord.target_id == target_id)
        statement = statement.order_by(
            OperationRecord.updated_at.desc(),
            OperationRecord.operation_id.desc(),
        ).limit(max(1, min(int(limit), 200)))
        with self._sessions() as session:
            return [_snapshot(row) for row in session.scalars(statement).all()]

    def transition(
        self,
        operation_id: str,
        *,
        next_status: str,
        event_type: str,
        stage: str,
        payload: Mapping[str, Any] | None = None,
        details_patch: Mapping[str, Any] | None = None,
        actor: OperationActor | None = None,
        expected_statuses: Sequence[str] | None = None,
    ) -> OperationSnapshot:
        return self._append(
            operation_id,
            next_status=next_status,
            event_type=event_type,
            stage=stage,
            payload=payload,
            details_patch=details_patch,
            actor=actor,
            expected_statuses=expected_statuses,
            is_transition=True,
        )

    def transition_for_target_lock_conflict(
        self,
        operation_id: str,
        *,
        conflicting_lock_id: str,
        conflicting_owner_id: str,
        next_status: str,
        event_type: str,
        stage: str,
        payload: Mapping[str, Any] | None = None,
        details_patch: Mapping[str, Any] | None = None,
    ) -> OperationSnapshot:
        """Record a conflict only while that exact foreign lock still excludes dispatch."""
        with self._sessions() as session:
            # Match recovery's Operation -> target lock ordering. Holding the
            # foreign lock row prevents release/new admission before the event.
            operation = session.scalar(
                select(OperationRecord)
                .where(OperationRecord.operation_id == operation_id)
                .with_for_update()
            )
            if operation is None:
                raise OperationNotFound(operation_id)
            if operation.status != "planned":
                return _snapshot(operation)
            lock = session.scalar(
                select(OperationLockRecord)
                .where(OperationLockRecord.operation_lock_id == conflicting_lock_id)
                .with_for_update()
            )
            if (
                lock is None
                or lock.status not in OPEN_TARGET_LOCK_STATUSES
                or lock.owner_id != conflicting_owner_id
                or lock.owner_id == operation_id
                or lock.scope_type != "proxmox_locator"
                or operation.target_type != "proxmox_vm"
                or operation.target_id != f"vmid:{lock.vmid}"
            ):
                return _snapshot(operation)
            return self.append_in_session(
                session,
                operation_id,
                next_status=next_status,
                event_type=event_type,
                stage=stage,
                payload=payload,
                details_patch=details_patch,
                expected_statuses=["planned"],
                is_transition=True,
            )

    def transition_pre_dispatch_failure(
        self,
        operation_id: str,
        *,
        target_lock_id: str,
        event_type: str,
        stage: str,
        payload: Mapping[str, Any] | None = None,
        details_patch: Mapping[str, Any] | None = None,
    ) -> bool:
        """Return release permission only if no recovery has taken over closure."""
        with self._sessions() as session:
            operation = session.scalar(
                select(OperationRecord)
                .where(OperationRecord.operation_id == operation_id)
                .with_for_update()
            )
            if operation is None:
                raise OperationNotFound(operation_id)
            if operation.status != "planned":
                return False
            # Operation locking serializes first recovery creation. Do not
            # lock an existing recovery row here: recovery locks that row
            # before the Operation. Its owner must finish and release instead.
            if session.get(OperationRecoveryItemRecord, operation_id) is not None:
                return False
            lock = session.scalar(
                select(OperationLockRecord)
                .where(OperationLockRecord.operation_lock_id == target_lock_id)
                .with_for_update()
            )
            if (
                lock is None
                or lock.owner_id != operation_id
                or lock.status not in OPEN_TARGET_LOCK_STATUSES
                or lock.scope_type != "proxmox_locator"
                or operation.target_type != "proxmox_vm"
                or operation.target_id != f"vmid:{lock.vmid}"
            ):
                return False
            self.append_in_session(
                session, operation_id,
                next_status="failed", event_type=event_type, stage=stage,
                payload=payload, details_patch=details_patch,
                expected_statuses=["planned"], is_transition=True,
            )
            return True

    def append_event(
        self,
        operation_id: str,
        *,
        event_type: str,
        stage: str,
        payload: Mapping[str, Any] | None = None,
        details_patch: Mapping[str, Any] | None = None,
        actor: OperationActor | None = None,
        expected_statuses: Sequence[str] | None = None,
    ) -> OperationSnapshot:
        return self._append(
            operation_id,
            next_status=None,
            event_type=event_type,
            stage=stage,
            payload=payload,
            details_patch=details_patch,
            actor=actor,
            expected_statuses=expected_statuses,
            is_transition=False,
        )

    def list_events(self, operation_id: str) -> list[OperationEvent]:
        with self._sessions() as session:
            rows = session.scalars(
                select(OperationEventRecord)
                .where(OperationEventRecord.operation_id == operation_id)
                .order_by(OperationEventRecord.sequence.asc())
            ).all()
            return [_event(row) for row in rows]

    def _append(
        self,
        operation_id: str,
        *,
        next_status: str | None,
        event_type: str,
        stage: str,
        payload: Mapping[str, Any] | None,
        details_patch: Mapping[str, Any] | None,
        actor: OperationActor | None,
        expected_statuses: Sequence[str] | None,
        is_transition: bool,
    ) -> OperationSnapshot:
        if not str(event_type).strip() or not str(stage).strip():
            raise ValueError("Operation event_type and stage are required")
        with self._sessions() as session:
            return self.append_in_session(
                session,
                operation_id,
                next_status=next_status,
                event_type=event_type,
                stage=stage,
                payload=payload,
                details_patch=details_patch,
                actor=actor,
                expected_statuses=expected_statuses,
                is_transition=is_transition,
            )

    def append_in_session(
        self,
        session: Session,
        operation_id: str,
        *,
        next_status: str | None,
        event_type: str,
        stage: str,
        payload: Mapping[str, Any] | None = None,
        details_patch: Mapping[str, Any] | None = None,
        actor: OperationActor | None = None,
        expected_statuses: Sequence[str] | None = None,
        is_transition: bool,
    ) -> OperationSnapshot:
        """Append an event using a caller-owned transaction.

        Recovery uses this seam to fence a lease and change the canonical
        Operation projection in the same database transaction.
        """

        if not str(event_type).strip() or not str(stage).strip():
            raise ValueError("Operation event_type and stage are required")
        row = session.scalar(
            select(OperationRecord)
            .where(OperationRecord.operation_id == operation_id)
            .with_for_update()
        )
        if row is None:
            raise OperationNotFound(operation_id)
        if expected_statuses is not None and row.status not in set(expected_statuses):
            raise OperationStateConflict(operation_id, row.status)

        target_status = next_status if is_transition else row.status
        if is_transition:
            ensure_operation_transition(row.status, str(target_status))
        event_actor = actor or _actor_from_record(row)
        created_at = _as_utc(self._clock())
        sanitized_payload = _sanitized_mapping(payload)
        sequence = int(row.version) + 1
        checksum = self._event_checksum(
            operation_id=operation_id,
            sequence=sequence,
            event_type=event_type,
            from_status=row.status,
            to_status=str(target_status),
            stage=stage,
            actor=event_actor,
            payload=sanitized_payload,
            previous_checksum=row.last_event_checksum,
            created_at=created_at,
        )
        event_row = self._new_event_row(
            operation_id=operation_id,
            sequence=sequence,
            event_type=event_type,
            from_status=row.status,
            to_status=str(target_status),
            stage=stage,
            actor=event_actor,
            payload=sanitized_payload,
            previous_checksum=row.last_event_checksum,
            checksum=checksum,
            created_at=created_at,
        )
        session.add(event_row)
        session.flush()
        self._apply_projection(
            row,
            status=str(target_status),
            stage=stage,
            details_patch=_sanitized_mapping(details_patch),
            version=sequence,
            checksum=checksum,
            updated_at=created_at,
        )
        session.flush()
        return _snapshot(row)

    @staticmethod
    def _apply_projection(
        row: OperationRecord,
        *,
        status: str,
        stage: str,
        details_patch: Mapping[str, Any],
        version: int,
        checksum: str,
        updated_at: datetime,
    ) -> None:
        row.status = status
        row.current_stage = stage
        row.details = {**dict(row.details or {}), **dict(details_patch)}
        row.version = version
        row.last_event_checksum = checksum
        row.updated_at = updated_at

    def _get_by_scope(self, spec: OperationSpec) -> OperationSnapshot | None:
        with self._sessions() as session:
            row = session.scalar(
                select(OperationRecord).where(
                    OperationRecord.operation_type == spec.operation_type,
                    OperationRecord.target_type == spec.target_type,
                    OperationRecord.target_id == spec.target_id,
                    OperationRecord.idempotency_key == spec.idempotency_key,
                )
            )
            return _snapshot(row) if row is not None else None

    @staticmethod
    def _resolve_existing(existing: OperationSnapshot, spec: OperationSpec) -> OperationCreateResult:
        same_identity = (
            existing.operation_type == spec.operation_type
            and existing.execution_mode == spec.execution_mode
            and existing.target_type == spec.target_type
            and existing.target_id == spec.target_id
            and existing.idempotency_key == spec.idempotency_key
            and existing.intent_digest == spec.intent_digest
            and existing.plan_digest == spec.plan_digest
        )
        if not same_identity:
            raise OperationIntentConflict(existing.operation_id)
        return OperationCreateResult(operation=existing, created=False)

    @staticmethod
    def _event_checksum(**kwargs: Any) -> str:
        return operation_digest(event_checksum_payload(**kwargs))

    @staticmethod
    def _new_event_row(
        *,
        operation_id: str,
        sequence: int,
        event_type: str,
        from_status: str | None,
        to_status: str,
        stage: str,
        actor: OperationActor,
        payload: Mapping[str, Any],
        previous_checksum: str,
        checksum: str,
        created_at: datetime,
    ) -> OperationEventRecord:
        return OperationEventRecord(
            event_id=f"operation-event-{uuid.uuid4().hex}",
            operation_id=operation_id,
            sequence=sequence,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            stage=stage,
            actor_user_id=actor.user_id or None,
            actor_username=actor.username or None,
            actor_role=actor.role or None,
            payload=dict(payload),
            previous_checksum=previous_checksum,
            checksum=checksum,
            created_at=created_at,
        )
