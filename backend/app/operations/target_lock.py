"""PostgreSQL target locks shared by all verified Proxmox actions."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from app.operations.locks.domain import DurableTargetLock, DurableTargetLockBusy
from app.operations.locks.infrastructure.repository import SqlAlchemyDurableTargetLockRepository


class TargetOperationLockBusy(RuntimeError):
    def __init__(self, *, target_type: str, target_id: str, owner_id: str, existing: dict[str, Any] | None = None) -> None:
        self.target_type = target_type
        self.target_id = target_id
        self.owner_id = owner_id
        self.existing = dict(existing or {})
        super().__init__(f"Target operation lock is busy: {target_type}:{target_id}")

    def to_dict(self) -> dict[str, Any]:
        return {"target_type": self.target_type, "target_id": self.target_id,
                "requested_owner_id": self.owner_id, "existing": self.existing}


@dataclass(frozen=True)
class TargetOperationLockHandle:
    target_type: str
    target_id: str
    owner_id: str
    durable: DurableTargetLock

    @property
    def lock_id(self) -> str:
        return self.durable.lock_id

    def to_dict(self) -> dict[str, Any]:
        return {"target_type": self.target_type, "target_id": self.target_id,
                "owner_id": self.owner_id, "lock_id": self.lock_id,
                "acquired_at": self.durable.created_at.isoformat(), "durable": self.durable.to_dict()}


def _locator(target_type: str, target_id: str) -> int:
    match = re.fullmatch(r"vmid:([1-9][0-9]*)", target_id)
    if target_type != "proxmox_vm" or match is None:
        raise ValueError("Target lock requires an exact Proxmox VM locator")
    return int(match.group(1))


def _cluster() -> str:
    return str(os.getenv("GJALLAR_CLUSTER_ID") or "gjallar-mvp").strip()


def acquire_target_operation_lock(target_type: str, target_id: str, owner_id: str, *, operation_type: str, cluster_id: str | None = None) -> TargetOperationLockHandle:
    vmid = _locator(target_type, target_id)
    try:
        durable = SqlAlchemyDurableTargetLockRepository().acquire(
            operation_type=operation_type, cluster_id=cluster_id or _cluster(), vmid=vmid,
            owner_id=owner_id, reason=f"{operation_type}_dispatch",
        )
    except DurableTargetLockBusy as exc:
        raise TargetOperationLockBusy(target_type=target_type, target_id=target_id, owner_id=owner_id, existing=exc.existing) from exc
    return TargetOperationLockHandle(target_type, target_id, owner_id, durable)


def release_target_operation_lock(handle: TargetOperationLockHandle) -> None:
    SqlAlchemyDurableTargetLockRepository().release(handle.durable, reason="verified_operation_completed")


def get_target_operation_lock(target_type: str, target_id: str) -> dict[str, Any] | None:
    if target_type == 'proxmox_connection':
        # Registration serializes connection transactions separately from VM/host locks.
        return None
    if target_type in {'proxmox_storage', 'proxmox_network'}:
        from app.operations.host_config.infrastructure import ConfigurationLockRepository
        held = ConfigurationLockRepository().current(cluster_id=_cluster())
        if held is None or (held.target_type, held.target_id) != (target_type, target_id):
            return None
        return {'target_type': target_type, 'target_id': target_id, 'owner_id': held.owner_id,
                'lock_id': held.lock_id, 'durable': held.to_dict()}
    durable = SqlAlchemyDurableTargetLockRepository().current(cluster_id=_cluster(), vmid=_locator(target_type, target_id))
    return TargetOperationLockHandle(target_type, target_id, durable.owner_id, durable).to_dict() if durable else None


def release_target_operation_lock_for_owner(target_type: str, target_id: str, owner_id: str) -> bool:
    return SqlAlchemyDurableTargetLockRepository().release_owned(
        cluster_id=_cluster(), vmid=_locator(target_type, target_id), owner_id=owner_id,
        reason="verified_operation_completed",
    )
