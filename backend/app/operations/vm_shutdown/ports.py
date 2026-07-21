"""Explicit external boundaries used by graceful VM Shutdown."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from app.operations.core.ports import OperationStorePort
from app.operations.recovery.ports import RecoveryStorePort
from app.operations.vm_shutdown.domain import VmShutdownCommand


class VmShutdownMutationFailure(RuntimeError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        self.details = dict(details or {})
        super().__init__(message)


@dataclass(frozen=True)
class VmShutdownTargetLockHandle:
    token: Any
    evidence: dict[str, Any]


class VmShutdownTargetLockBusy(RuntimeError):
    def __init__(self, evidence: dict[str, Any]) -> None:
        self.evidence = dict(evidence)
        super().__init__("VM Shutdown target lock is busy")


class WorkloadInventoryPort(Protocol):
    def list_vms(self) -> list[Any]: ...

    def list_templates(self) -> list[Any]: ...


class VmShutdownMutationPort(Protocol):
    def redacted_connection_context(self) -> dict[str, Any]: ...

    def shutdown_vm(self, *, node: str, vmid: int) -> str: ...

    def wait_for_task(
        self,
        *,
        node: str,
        upid: str,
        heartbeat: Callable[[], None] | None = None,
    ) -> dict[str, Any]: ...

    def get_vm_status(self, *, node: str, vmid: int) -> dict[str, Any]: ...


class VmShutdownJobPort(Protocol):
    def get(self, job_id: str) -> dict[str, Any] | None: ...

    def record(self, **kwargs: Any) -> dict[str, Any]: ...


class VmShutdownEvidencePort(Protocol):
    def write_json(
        self,
        *,
        job_id: str,
        artifact_type: str,
        filename: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...


class VmShutdownLockPort(Protocol):
    def acquire_request(self, job_id: str) -> Any: ...

    def release_request(self, handle: Any, job_id: str) -> None: ...

    def acquire_target(self, target_type: str, target_id: str, operation_id: str) -> VmShutdownTargetLockHandle: ...

    def release_target(self, handle: VmShutdownTargetLockHandle) -> None: ...


@dataclass(frozen=True)
class VmShutdownExecutionPorts:
    operations: OperationStorePort
    workloads: WorkloadInventoryPort
    mutation_factory: Callable[[], VmShutdownMutationPort | None]
    jobs: VmShutdownJobPort
    evidence: VmShutdownEvidencePort
    locks: VmShutdownLockPort
    recovery: RecoveryStorePort | None = None
    recovery_lease_seconds: float = 60.0


class VmShutdownWorkflowPort(Protocol):
    def execute(self, command: VmShutdownCommand, ports: VmShutdownExecutionPorts) -> dict[str, Any]: ...
