"""Create VM common Operation application tests."""

from __future__ import annotations

import pytest

from app.operations.core.domain import OperationActor, OperationIntentConflict, verify_event_chain
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.vm_create.application import VmCreateOperationTracker
from app.operations.vm_create.domain import VmCreateOperationPlan, vm_create_plan_intent
from app.operations.vm_create.domain import compact_create_result


def operation_plan(*, suffix: str = "same", risk_level: str = "green") -> VmCreateOperationPlan:
    intent = {
        "draft_id": "draft-create-306",
        "job_id": "job-create-306",
        "profile_id": "general-vm",
        "vm_name": f"create-306-{suffix}",
        "vmid": 306,
        "target_node_id": "node-a",
        "access": {"ssh_public_key": "ssh-ed25519 secret-material"},
    }
    return VmCreateOperationPlan(
        operation_id="job-create-306",
        draft_id="draft-create-306",
        target_node_id="node-a",
        vmid=306,
        vm_name=f"create-306-{suffix}",
        profile_id="general-vm",
        plan_artifact_id="artifact-plan-job-create-306",
        plan_digest="sha256:" + "a" * 64,
        risk_level=risk_level,
        intent=vm_create_plan_intent(intent),
        actor=OperationActor(user_id="user-1", username="operator-a", role="operator"),
    )


def successful_result() -> dict:
    return {
        "success": True,
        "status": "completed",
        "message": "created",
        "task": {"upid": "UPID:node-a:1:create", "status": "stopped", "exitstatus": "OK"},
        "observed_after": {
            "exists": True,
            "status": "stopped",
            "fingerprint": {"hash": "sha256:" + "f" * 64},
            "token": "must-not-persist",
        },
        "observed_after_artifact": {
            "artifact_id": "artifact-observed-create-306",
            "checksum": "sha256:" + "b" * 64,
        },
        "side_effects": ["proxmox_clone_invoked", "proxmox_post_check_observed"],
    }


def test_compact_create_result_rejects_unknown_semantic_values():
    marker = "opaque-create-result-token"
    compact = compact_create_result(
        {
            "success": False,
            "status": marker,
            "message": marker,
            "task": {"upid": marker, "status": marker, "exitstatus": marker},
            "observed_after": {
                "vmid": 306,
                "target_node_id": "node-a",
                "status": marker,
                "post_check_status": marker,
                "message": marker,
                "power_policy": marker,
            },
            "side_effects": [marker],
        }
    )

    assert compact["status"] == "unknown"
    assert compact["task"]["upid"] == ""
    assert compact["task"]["status"] == "unknown"
    assert compact["task"]["exitstatus"] == "ERROR"
    assert compact["observed_after"]["status"] == "unknown"
    assert compact["observed_after"]["readiness"]["post_check_status"] == "needs_reconciliation"
    assert compact["side_effects"] == []
    assert marker not in repr(compact)


def test_tracker_records_approved_dispatch_verification_and_workload_linkage():
    store = SqlAlchemyOperationStore()
    tracker = VmCreateOperationTracker(operations=store)
    prepared = tracker.prepare(operation_plan())

    approved = tracker.record_approval(
        prepared.operation.operation_id,
        {
            "can_approve": True,
            "can_execute": True,
            "risk_level": "green",
            "reason": "green risk; approval gate is open",
            "approval_record": {
                "job_id": "job-create-306",
                "plan_artifact_id": "artifact-plan-job-create-306",
                "review_summary_checksum": "sha256:" + "a" * 64,
                "decision": "approved",
            },
        },
    )
    dispatching = tracker.record_dispatch_prepared(
        approved.operation_id,
        preview={"clone": {"endpoint": "/nodes/node-a/qemu/9000/clone"}},
        target_lock={"target_type": "proxmox_vm", "target_id": "vmid:306", "owner_id": "job-create-306"},
    )
    verifying = tracker.record_result_observed(
        dispatching.operation_id,
        successful_result(),
        side_effect_free_failure=False,
    )
    succeeded = tracker.record_succeeded(
        verifying.operation_id,
        result=successful_result(),
        request={"request_id": "job-create-306", "status": "completed"},
        workload={"vm_instance_id": "node-a:306", "node_id": "node-a", "vmid": 306},
    )
    events = store.list_events(succeeded.operation_id)

    assert prepared.created is True
    assert prepared.operation.status == "awaiting_approval"
    assert approved.status == "approved"
    assert dispatching.status == "dispatching"
    assert verifying.status == "verifying"
    assert succeeded.status == "succeeded"
    assert succeeded.details["workload"]["vm_instance_id"] == "node-a:306"
    assert [event.event_type for event in events] == [
        "operation_created",
        "approval_granted",
        "dispatch_prepared",
        "dispatch_result_observed",
        "task_and_state_observed",
        "verification_succeeded",
    ]
    assert verify_event_chain(events) is True
    assert "token" not in events[4].payload["observed_after"]


def test_tracker_maps_ambiguous_result_to_reconciliation_and_preserves_lock_evidence():
    store = SqlAlchemyOperationStore()
    tracker = VmCreateOperationTracker(operations=store)
    operation_id = tracker.prepare(operation_plan()).operation.operation_id
    tracker.record_approval(
        operation_id,
        {"can_approve": True, "can_execute": True, "risk_level": "green", "reason": "approved"},
    )
    tracker.record_dispatch_prepared(
        operation_id,
        preview={"clone": {"endpoint": "/clone"}},
        target_lock={"owner_id": operation_id, "status": "active"},
    )

    reconciled = tracker.record_result_observed(
        operation_id,
        {
            "success": False,
            "status": "apply_failed",
            "message": "task outcome unknown",
            "side_effects": ["proxmox_clone_invoked"],
        },
        side_effect_free_failure=False,
    )

    assert reconciled.status == "needs_reconciliation"
    assert reconciled.details["target_operation_lock"]["owner_id"] == operation_id
    assert store.list_events(operation_id)[-1].event_type == "reconciliation_required"


def test_current_result_observation_second_checkpoint_failure_leaves_first_checkpoint_durable(monkeypatch):
    store = SqlAlchemyOperationStore()
    tracker = VmCreateOperationTracker(operations=store)
    operation_id = tracker.prepare(operation_plan()).operation.operation_id
    tracker.record_approval(
        operation_id,
        {"can_approve": True, "can_execute": True, "risk_level": "green", "reason": "approved"},
    )
    tracker.record_dispatch_prepared(
        operation_id,
        preview={"clone": {"endpoint": "/clone"}},
        target_lock={"owner_id": operation_id, "status": "active"},
    )
    original_transition = store.transition

    def fail_second_checkpoint(operation_id: str, **kwargs):
        if kwargs.get("event_type") == "task_and_state_observed":
            raise RuntimeError("operation event store unavailable")
        return original_transition(operation_id, **kwargs)

    monkeypatch.setattr(store, "transition", fail_second_checkpoint)

    with pytest.raises(RuntimeError, match="operation event store unavailable"):
        tracker.record_result_observed(
            operation_id,
            successful_result(),
            side_effect_free_failure=False,
        )

    operation = store.get(operation_id)
    events = store.list_events(operation_id)
    assert operation is not None
    assert operation.status == "running"
    assert events[-1].event_type == "dispatch_result_observed"
    assert events[-1].payload["task"]["upid"] == "UPID:node-a:1:create"
    assert verify_event_chain(events) is True


def test_red_plan_is_terminally_blocked_and_same_scope_changed_intent_conflicts():
    store = SqlAlchemyOperationStore()
    tracker = VmCreateOperationTracker(operations=store)
    blocked = tracker.prepare(operation_plan(risk_level="red"))

    assert blocked.operation.status == "blocked"
    with pytest.raises(OperationIntentConflict):
        tracker.prepare(operation_plan(suffix="changed", risk_level="red"))
