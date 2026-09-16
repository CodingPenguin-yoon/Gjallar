"""Admission and terminal failures must respect the current locator/recovery owner."""

import pytest

from app.operations.core.domain import OperationActor, OperationSpec
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.locks.infrastructure.repository import SqlAlchemyDurableTargetLockRepository
from app.operations.recovery.domain import RecoveryOperationConflict, RecoverySpec
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore


def _operation(store):
    return store.create(OperationSpec(
        operation_id="conflict-request", operation_type="vm_start", execution_mode="managed_api",
        target_type="proxmox_vm", target_id="vmid:306", idempotency_key="conflict-request",
        intent_digest="intent", plan_digest="plan", actor=OperationActor(role="operator"),
    )).operation


def _conflict(store, lock):
    return store.transition_for_target_lock_conflict(
        "conflict-request", conflicting_lock_id=lock.lock_id, conflicting_owner_id=lock.owner_id,
        next_status="blocked", event_type="target_lock_blocked", stage="precheck",
        payload={"target_operation_lock": lock.to_dict()},
        details_patch={"conflicting_operation_id": lock.owner_id},
    )


def test_delayed_foreign_conflict_preserves_new_same_request_owner():
    store = SqlAlchemyOperationStore()
    original = _operation(store)
    locks = SqlAlchemyDurableTargetLockRepository()
    previous = locks.acquire(operation_type="vm_shutdown", cluster_id="test", vmid=306,
                             owner_id="previous-request", reason="test")
    locks.release(previous, reason="completed")
    current = locks.acquire(operation_type="vm_start", cluster_id="test", vmid=306,
                            owner_id=original.operation_id, reason="test")

    result = _conflict(store, previous)

    assert result == original
    assert store.get(original.operation_id) == original
    assert len(store.list_events(original.operation_id)) == 1
    assert locks.current(cluster_id="test", vmid=306) == current


def test_same_foreign_conflict_records_one_terminal_event():
    store = SqlAlchemyOperationStore()
    original = _operation(store)
    locks = SqlAlchemyDurableTargetLockRepository()
    foreign = locks.acquire(operation_type="vm_shutdown", cluster_id="test", vmid=306,
                            owner_id="other-request", reason="test")

    first = _conflict(store, foreign)
    second = _conflict(store, foreign)

    assert first.status == "blocked"
    assert second == first
    assert len(store.list_events(original.operation_id)) == 2
    assert locks.current(cluster_id="test", vmid=306) == foreign


def test_same_owner_conflict_does_not_block_running_request():
    store = SqlAlchemyOperationStore()
    original = _operation(store)
    locks = SqlAlchemyDurableTargetLockRepository()
    own = locks.acquire(operation_type="vm_start", cluster_id="test", vmid=306,
                        owner_id=original.operation_id, reason="test")

    assert _conflict(store, own) == original
    assert len(store.list_events(original.operation_id)) == 1
    assert locks.current(cluster_id="test", vmid=306) == own


def _no_effect(store, lock):
    return store.transition_pre_dispatch_failure(
        "conflict-request", target_lock_id=lock.lock_id,
        event_type="mutation_client_unavailable", stage="start",
        details_patch={"pre_dispatch_terminal_no_effect": True, "mutation_dispatched": False,
                       "target_lock_id": lock.lock_id, "cluster_id": lock.cluster_id},
    )


def _replay_spec(lock):
    return RecoverySpec(operation_id="conflict-request", recovery_kind="vm_start_observation",
                        details={"node_id": "node-pg", "vmid": 306,
                                 "target_lock_id": lock.lock_id, "cluster_id": lock.cluster_id})


def test_no_effect_foreground_defers_to_claimed_replay_and_keeps_lock():
    store = SqlAlchemyOperationStore()
    original = _operation(store)
    locks = SqlAlchemyDurableTargetLockRepository()
    own = locks.acquire(operation_type="vm_start", cluster_id="test", vmid=306,
                        owner_id=original.operation_id, reason="test")
    recovery = SqlAlchemyRecoveryStore()
    lease = recovery.prepare_and_claim(_replay_spec(own), lease_owner="replay", lease_seconds=60)

    assert _no_effect(store, own) is False
    assert store.get(original.operation_id) == original
    assert locks.current(cluster_id="test", vmid=306) == own
    operation, item = recovery.commit_observation(
        lease, next_status="failed", event_type="replayed_pre_dispatch_failure_closed",
        stage="reconciliation", expected_statuses=["planned"], recovery_status="completed",
        release_target_lock=True, expected_operation_version=original.version,
        expected_operation_checksum=original.last_event_checksum,
    )
    assert operation.status == "failed"
    assert item.status == "completed"
    assert locks.current(cluster_id="test", vmid=306) is None
    assert _no_effect(store, own) is False
    assert len(store.list_events(original.operation_id)) == 2


def test_no_effect_foreground_completion_invalidates_late_replay_before_lease_creation():
    store = SqlAlchemyOperationStore()
    original = _operation(store)
    locks = SqlAlchemyDurableTargetLockRepository()
    own = locks.acquire(operation_type="vm_start", cluster_id="test", vmid=306,
                        owner_id=original.operation_id, reason="test")

    assert _no_effect(store, own) is True
    assert store.get(original.operation_id).status == "failed"
    recovery = SqlAlchemyRecoveryStore()
    with pytest.raises(RecoveryOperationConflict):
        recovery.prepare_and_claim(
            _replay_spec(own), lease_owner="replay", lease_seconds=60,
            expected_operation_version=original.version,
            expected_operation_checksum=original.last_event_checksum,
        )
    assert recovery.get(original.operation_id) is None
    assert locks.release(own, reason="foreground_completed") is True
