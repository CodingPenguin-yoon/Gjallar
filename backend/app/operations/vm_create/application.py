"""Application service mapping Create VM compatibility flow to common Operations."""

from __future__ import annotations

from typing import Any, Mapping

from app.operations.core.domain import (
    OperationActor,
    OperationCreateResult,
    OperationIntentConflict,
    OperationSnapshot,
    OperationSpec,
    OperationStateConflict,
    operation_digest,
)
from app.operations.core.ports import OperationStorePort
from app.operations.recovery.domain import PRE_DISPATCH_RECOVERY_CONTRACT
from app.operations.vm_create.domain import (
    VM_CREATE_OPERATION_TYPE,
    VmCreateOperationPlan,
    compact_create_result,
)


class VmCreateOperationTracker:
    def __init__(self, *, operations: OperationStorePort) -> None:
        self._operations = operations

    def prepare(self, plan: VmCreateOperationPlan) -> OperationCreateResult:
        initial_status = "blocked" if plan.risk_level == "red" else "awaiting_approval"
        intent_digest = operation_digest(dict(plan.intent))
        spec = OperationSpec(
            operation_id=plan.operation_id,
            operation_type=VM_CREATE_OPERATION_TYPE,
            execution_mode="managed_api",
            target_type="proxmox_vm",
            target_id=plan.target_id,
            idempotency_key=plan.operation_id,
            intent_digest=intent_digest,
            plan_digest=plan.plan_digest,
            actor=plan.actor,
            initial_status=initial_status,
            initial_stage="preflight" if initial_status == "blocked" else "approval",
            details={
                "draft_id": plan.draft_id,
                "job_id": plan.operation_id,
                "target": {
                    "node_id": plan.target_node_id,
                    "vmid": plan.vmid,
                    "name": plan.vm_name,
                },
                "workload": {
                    "profile_id": plan.profile_id,
                    "node_id": plan.target_node_id,
                    "vmid": plan.vmid,
                    "name": plan.vm_name,
                },
                "plan_artifact_id": plan.plan_artifact_id,
                "risk_level": plan.risk_level,
                "template_source": {
                    "node_id": dict(plan.intent.get("review_confirm") or {}).get("template_node_id"),
                    "vmid": dict(plan.intent.get("review_confirm") or {}).get("template_vmid"),
                },
                "power_policy": plan.intent.get("power_policy"),
                "recovery_contract": PRE_DISPATCH_RECOVERY_CONTRACT,
                "compatibility": {
                    "job_id": plan.operation_id,
                    "vm_create_request_id": plan.operation_id,
                },
            },
        )
        existing = self._operations.get(plan.operation_id)
        if existing is not None:
            same_identity = (
                existing.operation_type == VM_CREATE_OPERATION_TYPE
                and existing.target_type == "proxmox_vm"
                and existing.target_id == plan.target_id
                and existing.idempotency_key == plan.operation_id
                and existing.intent_digest == intent_digest
                and existing.plan_digest == plan.plan_digest
            )
            if not same_identity:
                raise OperationIntentConflict(existing.operation_id)
            return OperationCreateResult(operation=existing, created=False)
        return self._operations.create(
            spec,
            event_payload={
                "draft_id": plan.draft_id,
                "job_id": plan.operation_id,
                "target": {"node_id": plan.target_node_id, "vmid": plan.vmid},
                "plan_artifact_id": plan.plan_artifact_id,
                "plan_digest": plan.plan_digest,
                "risk_level": plan.risk_level,
                "preflight_status": "blocked" if initial_status == "blocked" else "completed",
                "recovery_contract": PRE_DISPATCH_RECOVERY_CONTRACT,
            },
        )

    def record_approval(
        self,
        operation_id: str,
        decision: Mapping[str, Any],
        *,
        actor: OperationActor | None = None,
    ) -> OperationSnapshot:
        operation = self._required(operation_id)
        payload = {
            "can_approve": decision.get("can_approve") is True,
            "can_execute": decision.get("can_execute") is True,
            "risk_level": str(decision.get("risk_level") or "unknown"),
            "requires_yellow_ack": decision.get("requires_yellow_ack") is True,
            "reason": str(decision.get("reason") or "")[:1000],
            "approval_record": dict(decision.get("approval_record") or {}),
            "approval_artifact": dict(decision.get("approval_artifact") or {}),
        }
        if payload["can_execute"]:
            if operation.status == "awaiting_approval":
                return self._operations.transition(
                    operation_id,
                    next_status="approved",
                    event_type="approval_granted",
                    stage="approval",
                    payload=payload,
                    details_patch={"approval": payload},
                    actor=actor,
                    expected_statuses=["awaiting_approval"],
                )
            if operation.status in {
                "approved",
                "dispatching",
                "running",
                "verifying",
                "succeeded",
                "needs_reconciliation",
            }:
                return operation
            raise OperationStateConflict(operation_id, operation.status)
        if operation.status in {"awaiting_approval", "blocked"}:
            return self._operations.append_event(
                operation_id,
                event_type="approval_blocked",
                stage="approval",
                payload=payload,
                details_patch={"approval": payload},
                actor=actor,
                expected_statuses=[operation.status],
            )
        return operation

    def record_preview(
        self,
        operation_id: str,
        preview: Mapping[str, Any],
        *,
        actor: OperationActor | None = None,
    ) -> OperationSnapshot:
        operation = self._required(operation_id)
        if operation.status not in {"approved", "dispatching", "running", "verifying", "succeeded"}:
            raise OperationStateConflict(operation_id, operation.status)
        return self._operations.append_event(
            operation_id,
            event_type="proxmox_preview_generated",
            stage="approval",
            payload={
                "clone_endpoint": str(dict(preview.get("clone") or {}).get("endpoint") or ""),
                "post_check": dict(preview.get("post_check") or {}),
                "side_effects": list(preview.get("side_effects") or []),
            },
            actor=actor,
            expected_statuses=[operation.status],
        )

    def record_dispatch_prepared(
        self,
        operation_id: str,
        *,
        preview: Mapping[str, Any],
        target_lock: Mapping[str, Any],
        actor: OperationActor | None = None,
    ) -> OperationSnapshot:
        return self._operations.transition(
            operation_id,
            next_status="dispatching",
            event_type="dispatch_prepared",
            stage="create",
            payload={
                "clone_endpoint": str(dict(preview.get("clone") or {}).get("endpoint") or ""),
                "target_lock": dict(target_lock),
            },
            details_patch={"target_operation_lock": dict(target_lock)},
            actor=actor,
            expected_statuses=["approved"],
        )

    def record_result_observed(
        self,
        operation_id: str,
        result: Mapping[str, Any],
        *,
        side_effect_free_failure: bool,
        actor: OperationActor | None = None,
    ) -> OperationSnapshot:
        evidence = compact_create_result(result)
        if evidence["success"] and evidence["observed_after_artifact"]["artifact_id"]:
            running = self._operations.transition(
                operation_id,
                next_status="running",
                event_type="dispatch_result_observed",
                stage="task_poll",
                payload={"task": evidence["task"], "side_effects": evidence["side_effects"]},
                actor=actor,
                expected_statuses=["dispatching"],
            )
            return self._operations.transition(
                running.operation_id,
                next_status="verifying",
                event_type="task_and_state_observed",
                stage="post_check",
                payload=evidence,
                actor=actor,
                expected_statuses=["running"],
            )

        next_status = "failed" if side_effect_free_failure else "needs_reconciliation"
        event_type = "dispatch_rejected" if side_effect_free_failure else "reconciliation_required"
        return self._operations.transition(
            operation_id,
            next_status=next_status,
            event_type=event_type,
            stage="create",
            payload=evidence,
            details_patch={"result_status": evidence["status"]},
            actor=actor,
            expected_statuses=["dispatching"],
        )

    def record_succeeded(
        self,
        operation_id: str,
        *,
        result: Mapping[str, Any],
        request: Mapping[str, Any],
        workload: Mapping[str, Any],
        actor: OperationActor | None = None,
    ) -> OperationSnapshot:
        evidence = compact_create_result(result)
        return self._operations.transition(
            operation_id,
            next_status="succeeded",
            event_type="verification_succeeded",
            stage="post_check",
            payload={
                **evidence,
                "vm_create_request": dict(request),
                "workload": dict(workload),
            },
            details_patch={
                "result_status": "completed",
                "vm_create_request": dict(request),
                "workload": dict(workload),
            },
            actor=actor,
            expected_statuses=["verifying"],
        )

    def record_compatibility_replay(
        self,
        operation_id: str,
        *,
        result: Mapping[str, Any],
        request: Mapping[str, Any],
        workload: Mapping[str, Any],
        actor: OperationActor | None = None,
    ) -> OperationSnapshot:
        operation = self._required(operation_id)
        if operation.status == "succeeded":
            return self._operations.append_event(
                operation_id,
                event_type="idempotent_replay_returned",
                stage="post_check",
                payload={"compatibility_request_id": str(request.get("request_id") or operation_id)},
                actor=actor,
                expected_statuses=["succeeded"],
            )
        if operation.status not in {"approved", "dispatching", "running", "verifying"}:
            raise OperationStateConflict(operation_id, operation.status)
        if operation.status == "approved":
            operation = self._operations.transition(
                operation_id,
                next_status="dispatching",
                event_type="compatibility_result_adopted",
                stage="create",
                payload={"historical": True, "mutation_replayed": False},
                actor=actor,
                expected_statuses=["approved"],
            )
        if operation.status == "dispatching":
            operation = self._operations.transition(
                operation_id,
                next_status="running",
                event_type="compatibility_task_adopted",
                stage="task_poll",
                payload={"task": compact_create_result(result)["task"], "historical": True},
                actor=actor,
                expected_statuses=["dispatching"],
            )
        if operation.status == "running":
            operation = self._operations.transition(
                operation_id,
                next_status="verifying",
                event_type="compatibility_verification_adopted",
                stage="post_check",
                payload={**compact_create_result(result), "historical": True},
                actor=actor,
                expected_statuses=["running"],
            )
        return self.record_succeeded(
            operation_id,
            result=result,
            request=request,
            workload=workload,
            actor=actor,
        )

    def append_guard_blocked(
        self,
        operation_id: str,
        detail: Mapping[str, Any],
        *,
        actor: OperationActor | None = None,
    ) -> OperationSnapshot:
        operation = self._required(operation_id)
        return self._operations.append_event(
            operation_id,
            event_type="compatibility_guard_blocked",
            stage="precheck",
            payload={
                "code": str(detail.get("code") or ""),
                "message": str(detail.get("message") or "")[:1000],
                "existing_status": str(detail.get("existing_status") or ""),
                "request_id": str(detail.get("request_id") or ""),
            },
            actor=actor,
            expected_statuses=[operation.status],
        )

    def get(self, operation_id: str) -> OperationSnapshot:
        return self._required(operation_id)

    def _required(self, operation_id: str) -> OperationSnapshot:
        operation = self._operations.get(operation_id)
        if operation is None:
            raise LookupError(f"Create VM operation was not found: {operation_id}")
        return operation
