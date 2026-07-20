"""Compatibility-friendly composition facade for Guided `qm` API handlers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Mapping

from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.guided_qm.application import GuidedQmUnlockUseCase
from app.operations.guided_qm.domain import (
    AttestGuidedQmCommand,
    PlanGuidedQmUnlockCommand,
    VerifyGuidedQmCommand,
)
from app.operations.guided_qm.errors import GuidedQmError
from app.operations.guided_qm.infrastructure.adapters import (
    ProxmoxGuidedQmObservationAdapter,
    SharedGuidedQmTargetLockAdapter,
)
from app.operations.guided_qm.ports import GuidedQmExecutionPorts, GuidedQmObservationFailure
from app.proxmox.client import ProxmoxMutationError, ProxmoxMutationClient, get_default_proxmox_mutation_client


class _UnusedObservationAdapter:
    def has_node_task_audit(self, *, node: str) -> bool:
        raise GuidedQmObservationFailure("Observation is not available for this operation")

    def get_vm_config(self, *, node: str, vmid: int) -> dict[str, Any]:
        raise GuidedQmObservationFailure("Observation is not available for this operation")

    def list_active_vm_tasks(self, *, node: str, vmid: int) -> list[dict[str, Any]]:
        raise GuidedQmObservationFailure("Observation is not available for this operation")


def _client_from_factory(factory: Callable[[], ProxmoxMutationClient]) -> ProxmoxMutationClient:
    try:
        return factory()
    except ProxmoxMutationError as exc:
        raise GuidedQmError(
            "GUIDED_QM_OBSERVATION_UNAVAILABLE",
            "The Proxmox API client is unavailable for Guided qm observation",
            status_code=503,
        ) from exc
    except Exception as exc:
        raise GuidedQmError(
            "GUIDED_QM_OBSERVATION_UNAVAILABLE",
            "The Proxmox API client is unavailable for Guided qm observation",
            status_code=503,
        ) from exc


def _use_case(
    *,
    client: Any | None = None,
    store: Any | None = None,
    clock: Callable[[], datetime] | None = None,
) -> GuidedQmUnlockUseCase:
    ports = GuidedQmExecutionPorts(
        operations=store or SqlAlchemyOperationStore(),
        observation=ProxmoxGuidedQmObservationAdapter(client) if client is not None else _UnusedObservationAdapter(),
        locks=SharedGuidedQmTargetLockAdapter(),
    )
    kwargs: dict[str, Any] = {"ports": ports}
    if clock is not None:
        kwargs["clock"] = clock
    return GuidedQmUnlockUseCase(**kwargs)


def plan_guided_qm_unlock(
    *,
    payload: Mapping[str, Any] | None,
    actor: Mapping[str, Any] | None,
    client: Any | None = None,
    client_factory: Callable[[], ProxmoxMutationClient] = get_default_proxmox_mutation_client,
) -> dict[str, Any]:
    command = PlanGuidedQmUnlockCommand.from_request(payload, actor=actor)
    observation_client = client if client is not None else _client_from_factory(client_factory)
    return _use_case(client=observation_client).plan_unlock(command)


def attest_guided_qm_operation(
    *,
    operation_id: str,
    payload: Mapping[str, Any] | None,
    actor: Mapping[str, Any] | None,
) -> dict[str, Any]:
    command = AttestGuidedQmCommand.from_request(operation_id, payload, actor=actor)
    return _use_case().attest(command)


def verify_guided_qm_operation(
    *,
    operation_id: str,
    payload: Mapping[str, Any] | None,
    actor: Mapping[str, Any] | None,
    client: Any | None = None,
    client_factory: Callable[[], ProxmoxMutationClient] = get_default_proxmox_mutation_client,
) -> dict[str, Any]:
    command = VerifyGuidedQmCommand.from_request(operation_id, payload, actor=actor)
    observation_client = client if client is not None else _client_from_factory(client_factory)
    return _use_case(client=observation_client).verify(command)


def get_operation(operation_id: str) -> dict[str, Any]:
    return _use_case().get(operation_id)


__all__ = [
    "GuidedQmError",
    "attest_guided_qm_operation",
    "get_operation",
    "plan_guided_qm_unlock",
    "verify_guided_qm_operation",
]
