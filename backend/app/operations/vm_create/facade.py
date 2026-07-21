"""Composition facade for Create VM common Operation tracking."""

from __future__ import annotations

from typing import Any, Mapping

from app.auth.roles import actor_evidence
from app.operations.core.domain import OperationActor, OperationCreateResult, OperationSnapshot
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.core.read_models import operation_payload
from app.operations.vm_create.application import VmCreateOperationTracker
from app.operations.vm_create.domain import VmCreateOperationPlan, vm_create_plan_intent


def _tracker() -> VmCreateOperationTracker:
    return VmCreateOperationTracker(operations=SqlAlchemyOperationStore())


def _operation_actor(actor: Any = None) -> OperationActor | None:
    if actor is None:
        return None
    return OperationActor.from_mapping(actor_evidence(actor))


def _operation_plan(plan: Any, actor: Any = None) -> VmCreateOperationPlan:
    review = dict(plan.review_confirm or {})
    actor_payload = actor_evidence(actor) if actor is not None else {}
    return VmCreateOperationPlan(
        operation_id=str(plan.job_id),
        draft_id=str(plan.draft_id),
        target_node_id=str(plan.target_node_id),
        vmid=int(plan.vmid),
        vm_name=str(plan.vm_name),
        profile_id=str(plan.profile_id),
        plan_artifact_id=str(review.get("plan_artifact_id") or ""),
        plan_digest=str(review.get("review_summary_checksum") or ""),
        risk_level=str(dict(plan.risk_summary or {}).get("level") or "unknown"),
        intent=vm_create_plan_intent(plan),
        actor=OperationActor.from_mapping(actor_payload),
    )


def prepare_vm_create_operation(plan: Any, *, actor: Any = None) -> OperationCreateResult:
    return _tracker().prepare(_operation_plan(plan, actor))


def record_vm_create_approval(operation_id: str, decision: Mapping[str, Any], *, actor: Any = None) -> OperationSnapshot:
    return _tracker().record_approval(operation_id, decision, actor=_operation_actor(actor))


def record_vm_create_preview(operation_id: str, preview: Mapping[str, Any], *, actor: Any = None) -> OperationSnapshot:
    return _tracker().record_preview(operation_id, preview, actor=_operation_actor(actor))


def record_vm_create_dispatch_prepared(
    operation_id: str,
    *,
    preview: Mapping[str, Any],
    target_lock: Mapping[str, Any],
    actor: Any = None,
) -> OperationSnapshot:
    return _tracker().record_dispatch_prepared(
        operation_id,
        preview=preview,
        target_lock=target_lock,
        actor=_operation_actor(actor),
    )


def record_vm_create_result(
    operation_id: str,
    result: Mapping[str, Any],
    *,
    side_effect_free_failure: bool,
    actor: Any = None,
) -> OperationSnapshot:
    return _tracker().record_result_observed(
        operation_id,
        result,
        side_effect_free_failure=side_effect_free_failure,
        actor=_operation_actor(actor),
    )


def record_vm_create_succeeded(
    operation_id: str,
    *,
    result: Mapping[str, Any],
    request: Mapping[str, Any],
    workload: Mapping[str, Any],
    actor: Any = None,
) -> OperationSnapshot:
    return _tracker().record_succeeded(
        operation_id,
        result=result,
        request=request,
        workload=workload,
        actor=_operation_actor(actor),
    )


def record_vm_create_compatibility_replay(
    operation_id: str,
    *,
    result: Mapping[str, Any],
    request: Mapping[str, Any],
    workload: Mapping[str, Any],
    actor: Any = None,
) -> OperationSnapshot:
    return _tracker().record_compatibility_replay(
        operation_id,
        result=result,
        request=request,
        workload=workload,
        actor=_operation_actor(actor),
    )


def record_vm_create_guard_blocked(operation_id: str, detail: Mapping[str, Any], *, actor: Any = None) -> OperationSnapshot:
    return _tracker().append_guard_blocked(operation_id, detail, actor=_operation_actor(actor))


def get_vm_create_operation(operation_id: str) -> OperationSnapshot:
    return _tracker().get(operation_id)


def vm_create_operation_link(operation: OperationSnapshot) -> dict[str, Any]:
    return operation_payload(operation)
