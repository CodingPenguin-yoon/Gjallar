"""External contracts for Guided `qm` planning and verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.operations.core.ports import OperationStorePort
from app.operations.recovery.ports import RecoveryStorePort


class GuidedQmObservationFailure(RuntimeError):
    """Raised when authoritative Proxmox state cannot be observed."""


class GuidedQmObservationPort(Protocol):
    def has_node_task_audit(self, *, node: str) -> bool: ...

    def get_vm_config(self, *, node: str, vmid: int) -> dict[str, Any]: ...

    def list_active_vm_tasks(self, *, node: str, vmid: int) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class GuidedQmTargetLockHandle:
    token: Any
    evidence: dict[str, Any]


class GuidedQmTargetLockBusy(RuntimeError):
    def __init__(self, evidence: dict[str, Any]) -> None:
        self.evidence = dict(evidence)
        super().__init__("Guided qm target lock is busy")


class GuidedQmTargetLockPort(Protocol):
    def acquire(self, target_type: str, target_id: str, operation_id: str) -> GuidedQmTargetLockHandle: ...

    def current(self, target_type: str, target_id: str) -> dict[str, Any] | None: ...

    def release(self, handle: GuidedQmTargetLockHandle) -> None: ...

    def release_owned(self, target_type: str, target_id: str, operation_id: str) -> bool: ...




@dataclass(frozen=True)
class GuidedQmExecutionPorts:
    operations: OperationStorePort
    observation: GuidedQmObservationPort
    locks: GuidedQmTargetLockPort
    recovery: RecoveryStorePort | None = None
    recovery_lease_seconds: float = 60.0
