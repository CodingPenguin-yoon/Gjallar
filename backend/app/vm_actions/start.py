"""Compatibility facade and concrete adapters for verified VM Start."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from app.auth.roles import actor_evidence
from app.core.redaction import redact_secrets
from app.jobs.artifacts import write_json_artifact
from app.jobs.runs import get_job_run, record_job_run, run_dir
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.target_lock import (
    TargetOperationLockBusy,
    acquire_target_operation_lock,
    release_target_operation_lock,
)
from app.operations.vm_start.application import VmStartUseCase
from app.operations.vm_start.domain import VmStartCommand, build_vm_start_job_id as build_operation_job_id
from app.operations.vm_start.errors import VmStartError
from app.operations.vm_start.ports import (
    VmStartExecutionPorts,
    VmStartMutationFailure,
    VmStartMutationPort,
    VmStartTargetLockBusy,
    VmStartTargetLockHandle,
)
from app.operations.vm_start.workflow import VerifiedVmStartWorkflow
from app.proxmox.client import ProxmoxMutationClient, ProxmoxMutationError


def build_vm_start_job_id(*, node_id: str, vmid: int, idempotency_key: str) -> str:
    return build_operation_job_id(node_id=node_id, vmid=vmid, idempotency_key=idempotency_key)


def _acquire_request_lock(lock_path: Path) -> int:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise VmStartError(
            "VM_START_IN_PROGRESS",
            "A VM start operation with this idempotency key is already in progress",
            details={"job_id": lock_path.parent.name, "proxmox_mutation_enabled": False, "side_effects": []},
        ) from exc
    os.write(fd, str(os.getpid()).encode("utf-8"))
    return fd


def _release_request_lock(handle: int | None, lock_path: Path) -> None:
    if handle is None:
        return
    os.close(handle)
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


class _CurrentVmStartJobAdapter:
    def get(self, job_id: str) -> dict[str, Any] | None:
        return get_job_run(job_id)

    def record(self, **kwargs: Any) -> dict[str, Any]:
        if isinstance(kwargs.get("details"), dict):
            kwargs["details"] = redact_secrets(kwargs["details"])
        return record_job_run(**kwargs)


class _CurrentVmStartEvidenceAdapter:
    def write_json(
        self,
        *,
        job_id: str,
        artifact_type: str,
        filename: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return write_json_artifact(
            run_dir=run_dir(job_id),
            job_id=job_id,
            artifact_type=artifact_type,
            filename=filename,
            payload=payload,
        ).to_dict()


class _CurrentVmStartLockAdapter:
    @staticmethod
    def _request_lock_path(job_id: str) -> Path:
        return run_dir(job_id) / "vm_start.lock"

    def acquire_request(self, job_id: str) -> int:
        return _acquire_request_lock(self._request_lock_path(job_id))

    def release_request(self, handle: int | None, job_id: str) -> None:
        _release_request_lock(handle, self._request_lock_path(job_id))

    def acquire_target(self, target_type: str, target_id: str, operation_id: str) -> VmStartTargetLockHandle:
        try:
            handle = acquire_target_operation_lock(target_type, target_id, operation_id)
        except TargetOperationLockBusy as exc:
            raise VmStartTargetLockBusy(exc.to_dict()) from exc
        return VmStartTargetLockHandle(token=handle, evidence=handle.to_dict())

    def release_target(self, handle: VmStartTargetLockHandle) -> None:
        release_target_operation_lock(handle.token)


class _CurrentVmStartMutationAdapter:
    def __init__(self, client: ProxmoxMutationClient) -> None:
        self._client = client

    def redacted_connection_context(self) -> dict[str, Any]:
        return self._client.redacted_connection_context()

    def start_vm(self, *, node: str, vmid: int) -> str:
        try:
            return self._client.start_vm(node=node, vmid=vmid)
        except ProxmoxMutationError as exc:
            raise VmStartMutationFailure(str(exc), details=exc.details) from exc

    def wait_for_task(self, *, node: str, upid: str) -> dict[str, Any]:
        try:
            return self._client.wait_for_task(node=node, upid=upid)
        except ProxmoxMutationError as exc:
            raise VmStartMutationFailure(str(exc), details=exc.details) from exc

    def get_vm_status(self, *, node: str, vmid: int) -> dict[str, Any]:
        try:
            return self._client.get_vm_status(node=node, vmid=vmid)
        except ProxmoxMutationError as exc:
            raise VmStartMutationFailure(str(exc), details=exc.details) from exc


def _build_current_mutation_adapter(
    factory: Callable[[], ProxmoxMutationClient],
) -> VmStartMutationPort | None:
    try:
        client = factory()
    except ProxmoxMutationError as exc:
        raise VmStartMutationFailure(str(exc), details=exc.details) from exc
    return _CurrentVmStartMutationAdapter(client) if client is not None else None


def run_vm_start(
    *,
    node_id: str,
    vmid: int,
    payload: dict[str, Any] | None,
    inventory_adapter: Any,
    actor: dict[str, Any] | None = None,
    client: ProxmoxMutationClient | None = None,
    client_factory: Callable[[], ProxmoxMutationClient] | None = None,
) -> dict[str, Any]:
    """Preserve the public service facade while routing through the Operations use case."""
    command = VmStartCommand.from_request(
        node_id=node_id,
        vmid=vmid,
        payload=payload,
        actor=actor_evidence(actor) if actor is not None else None,
    )
    if client is not None:
        mutation_factory: Callable[[], VmStartMutationPort | None] = lambda: _CurrentVmStartMutationAdapter(client)
    elif client_factory is not None:
        mutation_factory = lambda: _build_current_mutation_adapter(client_factory)
    else:
        mutation_factory = lambda: None

    ports = VmStartExecutionPorts(
        operations=SqlAlchemyOperationStore(),
        workloads=inventory_adapter,
        mutation_factory=mutation_factory,
        jobs=_CurrentVmStartJobAdapter(),
        evidence=_CurrentVmStartEvidenceAdapter(),
        locks=_CurrentVmStartLockAdapter(),
    )
    return VmStartUseCase(
        workflow=VerifiedVmStartWorkflow(),
        ports=ports,
    ).execute(command)


__all__ = ["VmStartError", "build_vm_start_job_id", "run_vm_start"]
