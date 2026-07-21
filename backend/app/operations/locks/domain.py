"""Infrastructure-free durable target-lock contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


SUPPORTED_TARGET_OPERATION_TYPES = frozenset(
    {"drs_migration", "vm_start", "vm_create", "guided_qm_vm_unlock", "vm_shutdown"}
)
OPEN_TARGET_LOCK_STATUSES = frozenset({"active", "stale", "reconciliation_required"})


class DurableTargetLockBusy(RuntimeError):
    def __init__(self, *, scope_key: str, existing: dict[str, Any] | None = None) -> None:
        self.scope_key = str(scope_key)
        self.existing = dict(existing or {})
        super().__init__(f"Durable target lock is busy: {self.scope_key}")


@dataclass(frozen=True)
class DurableTargetLock:
    lock_id: str
    operation_type: str
    cluster_id: str
    vmid: int
    owner_id: str
    scope_key: str
    status: str
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_lock_id": self.lock_id,
            "operation_type": self.operation_type,
            "scope_type": "proxmox_locator",
            "scope_key": self.scope_key,
            "status": self.status,
            "cluster_id": self.cluster_id,
            "vmid": self.vmid,
            "owner_id": self.owner_id,
            "created_at": self.created_at.isoformat(),
        }


def locator_scope_key(cluster_id: str, vmid: int) -> str:
    normalized_cluster = str(cluster_id).strip().replace("|", "-") or "gjallar-mvp"
    return f"{normalized_cluster}|proxmox_locator|{int(vmid)}"
