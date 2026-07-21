"""Explicit external boundaries used by the VM Start application slice."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from app.operations.core.ports import OperationStorePort
from app.operations.recovery.ports import RecoveryStorePort
from app.operations.vm_start.domain import VmStartCommand


class VmStartMutationFailure(RuntimeError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        self.details = dict(details or {})
        super().__init__(message)


@dataclass(frozen=True)
class VmStartTargetLockHandle:
    token: Any
    evidence: dict[str, Any]


class VmStartTargetLockBusy(RuntimeError):
    def __init__(self, evidence: dict[str, Any]) -> None:
        self.evidence = dict(evidence)
        super().__init__("VM Start target lock is busy")


class WorkloadInventoryPort(Protocol):
    def list_vms(self) -> list[Any]: ...

    def list_templates(self) -> list[Any]: ...


class VmStartMutationPort(Protocol):
    def redacted_connection_context(self) -> dict[str, Any]: ...

    def start_vm(self, *, node: str, vmid: int) -> str: ...

    def wait_for_task(
        self,
        *,
        node: str,
        upid: str,
        heartbeat: Callable[[], None] | None = None,
    ) -> dict[str, Any]: ...

    def get_vm_status(self, *, node: str, vmid: int) -> dict[str, Any]: ...


class VmStartJobPort(Protocol):
    def get(self, job_id: str) -> dict[str, Any] | None: ...

    def record(self, **kwargs: Any) -> dict[str, Any]: ...


class VmStartEvidencePort(Protocol):
    def write_json(
        self,
        *,
        job_id: str,
        artifact_type: str,
        filename: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...


class VmStartLockPort(Protocol):
    def acquire_request(self, job_id: str) -> Any: ...

    def release_request(self, handle: Any, job_id: str) -> None: ...

    def acquire_target(self, target_type: str, target_id: str, operation_id: str) -> VmStartTargetLockHandle: ...

    def release_target(self, handle: VmStartTargetLockHandle) -> None: ...


@dataclass(frozen=True)
class VmStartExecutionPorts:
    operations: OperationStorePort
    workloads: WorkloadInventoryPort
    mutation_factory: Callable[[], VmStartMutationPort | None]
    jobs: VmStartJobPort
    evidence: VmStartEvidencePort
    locks: VmStartLockPort
    recovery: RecoveryStorePort | None = None
    recovery_lease_seconds: float = 60.0


class VmStartWorkflowPort(Protocol):
    def execute(self, command: VmStartCommand, ports: VmStartExecutionPorts) -> dict[str, Any]: ...
