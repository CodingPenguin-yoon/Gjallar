"""SQLAlchemy repository for cross-operation Proxmox locator locks."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import OperationLockRecord
from app.db.session import session_scope
from app.operations.locks.domain import (
    OPEN_TARGET_LOCK_STATUSES,
    SUPPORTED_TARGET_OPERATION_TYPES,
    DurableTargetLock,
    DurableTargetLockBusy,
    locator_scope_key,
)


SessionScope = Callable[[], AbstractContextManager[Session]]
Clock = Callable[[], datetime]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _lock(row: OperationLockRecord) -> DurableTargetLock:
    return DurableTargetLock(
        lock_id=row.operation_lock_id,
        operation_type=row.operation_type,
        cluster_id=row.cluster_id,
        vmid=int(row.vmid or 0),
        owner_id=str(row.owner_id or ""),
        scope_key=row.scope_key,
        status=row.status,
        created_at=_as_utc(row.created_at),
    )


class SqlAlchemyDurableTargetLockRepository:
    def __init__(self, *, sessions: SessionScope = session_scope, clock: Clock = _now_utc) -> None:
        self._sessions = sessions
        self._clock = clock

    def acquire(
        self,
        *,
        operation_type: str,
        cluster_id: str,
        vmid: int,
        owner_id: str,
        reason: str,
    ) -> DurableTargetLock:
        if operation_type not in SUPPORTED_TARGET_OPERATION_TYPES:
            raise ValueError(f"Unsupported target lock operation type: {operation_type}")
        normalized_cluster = str(cluster_id).strip() or "gjallar-mvp"
        normalized_owner = str(owner_id).strip()
        if not normalized_owner:
            raise ValueError("Durable target lock owner_id is required")
        normalized_vmid = int(vmid)
        scope_key = locator_scope_key(normalized_cluster, normalized_vmid)
        existing = self.current(cluster_id=normalized_cluster, vmid=normalized_vmid)
        if existing is not None:
            raise DurableTargetLockBusy(scope_key=scope_key, existing=existing.to_dict())
        now = _as_utc(self._clock())
        row = OperationLockRecord(
            operation_lock_id=f"operation-lock-{uuid.uuid4().hex}",
            operation_type=operation_type,
            scope_type="proxmox_locator",
            scope_key=scope_key,
            status="active",
            cluster_id=normalized_cluster,
            vmid=normalized_vmid,
            owner_id=normalized_owner,
            reason=str(reason).strip() or f"{operation_type}_target_lock",
            evidence={"operation_id": normalized_owner, "target_type": "proxmox_vm", "target_id": f"vmid:{normalized_vmid}"},
            created_at=now,
            updated_at=now,
        )
        try:
            with self._sessions() as session:
                from app.setup_integration.contracts import SetupError
                from app.setup_integration.runtime import admit_mutation

                try:
                    admit_mutation(session, cluster_id=normalized_cluster, vmid=normalized_vmid,
                                   operation_type=operation_type)
                except SetupError as exc:
                    raise DurableTargetLockBusy(scope_key=scope_key, existing={"reason": exc.code}) from None
                session.add(row)
                session.flush()
                return _lock(row)
        except IntegrityError as exc:
            existing = self.current(cluster_id=normalized_cluster, vmid=normalized_vmid)
            raise DurableTargetLockBusy(
                scope_key=scope_key,
                existing=existing.to_dict() if existing else {},
            ) from exc

    def current(self, *, cluster_id: str, vmid: int) -> DurableTargetLock | None:
        scope_key = locator_scope_key(cluster_id, int(vmid))
        with self._sessions() as session:
            row = session.scalar(
                select(OperationLockRecord)
                .where(
                    OperationLockRecord.scope_type == "proxmox_locator",
                    OperationLockRecord.scope_key == scope_key,
                    OperationLockRecord.status.in_(OPEN_TARGET_LOCK_STATUSES),
                )
                .order_by(OperationLockRecord.created_at.asc(), OperationLockRecord.operation_lock_id.asc())
            )
            return _lock(row) if row is not None else None

    def release(self, lock: DurableTargetLock, *, reason: str) -> bool:
        now = _as_utc(self._clock())
        with self._sessions() as session:
            row = session.scalar(
                select(OperationLockRecord)
                .where(OperationLockRecord.operation_lock_id == lock.lock_id)
                .with_for_update()
            )
            if row is None or (
                row.status not in OPEN_TARGET_LOCK_STATUSES
                or row.owner_id != lock.owner_id
                or row.scope_key != lock.scope_key
            ):
                return False
            row.status = "released"
            row.reason = str(reason).strip() or "verified_operation_completed"
            row.released_at = now
            row.updated_at = now
            session.flush()
            return True

    def release_owned(self, *, cluster_id: str, vmid: int, owner_id: str, reason: str) -> bool:
        scope_key = locator_scope_key(cluster_id, int(vmid))
        now = _as_utc(self._clock())
        with self._sessions() as session:
            row = session.scalar(
                select(OperationLockRecord)
                .where(
                    OperationLockRecord.scope_type == "proxmox_locator",
                    OperationLockRecord.scope_key == scope_key,
                    OperationLockRecord.owner_id == str(owner_id),
                    OperationLockRecord.status.in_(OPEN_TARGET_LOCK_STATUSES),
                )
                .with_for_update()
            )
            if row is None:
                return False
            row.status = "released"
            row.reason = str(reason).strip() or "verified_operation_completed"
            row.released_at = now
            row.updated_at = now
            session.flush()
            return True


__all__ = ["SqlAlchemyDurableTargetLockRepository"]
