"""Map VM Start intent and lifecycle events to the common Operation store."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from app.operations.core.domain import (
    OperationActor,
    OperationCreateResult,
    OperationSnapshot,
    OperationSpec,
    operation_digest,
)
from app.operations.core.ports import OperationStorePort
from app.operations.vm_start.domain import VmStartCommand, vm_start_target_lock_id


def prepare_vm_start_operation(
    store: OperationStorePort,
    *,
    command: VmStartCommand,
    operation_id: str,
    idempotency_key: str,
) -> OperationCreateResult:
    intent = command.stable_intent
    spec = OperationSpec(
        operation_id=operation_id,
        operation_type="vm_start",
        execution_mode="managed_api",
        target_type="proxmox_vm",
        target_id=vm_start_target_lock_id(command.vmid),
        idempotency_key=idempotency_key,
        intent_digest=operation_digest(intent),
        plan_digest=operation_digest({"schema": "vm_start_plan.v1", "intent": intent}),
        actor=OperationActor.from_mapping(command.actor),
        initial_status="planned",
        initial_stage="plan",
        details={
            "job_id": operation_id,
            "target": {"node_id": command.node_id, "vmid": command.vmid},
        },
    )
    return store.create(
        spec,
        event_payload={
            "job_id": operation_id,
            "intent": intent,
        },
    )


def transition_vm_start_operation(
    store: OperationStorePort,
    operation_id: str,
    *,
    next_status: str,
    event_type: str,
    stage: str,
    payload: Mapping[str, Any] | None = None,
    details_patch: Mapping[str, Any] | None = None,
    expected_statuses: Sequence[str] | None = None,
) -> OperationSnapshot:
    return store.transition(
        operation_id,
        next_status=next_status,
        event_type=event_type,
        stage=stage,
        payload=payload,
        details_patch=details_patch,
        expected_statuses=expected_statuses,
    )
