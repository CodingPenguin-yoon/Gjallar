"""Repository tests for atomic Operation projection and event persistence."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.operations.core.domain import (
    InvalidOperationTransition,
    OperationActor,
    OperationIntentConflict,
    OperationSpec,
    OperationStateConflict,
    operation_digest,
    verify_event_chain,
)
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore


FIXED_NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


def operation_spec(*, intent_suffix: str = "same") -> OperationSpec:
    intent = {
        "operation": "vm_start",
        "target": {"node_id": "node-a", "vmid": 306},
        "expected": {"status": "stopped"},
        "suffix": intent_suffix,
    }
    return OperationSpec(
        operation_id="operation-vm-start-306",
        operation_type="vm_start",
        execution_mode="managed_api",
        target_type="proxmox_vm",
        target_id="vmid:306",
        idempotency_key="idem-1",
        intent_digest=operation_digest(intent),
        plan_digest=operation_digest({"intent": intent, "plan_version": 1}),
        actor=OperationActor(user_id="user-1", username="operator", role="operator"),
        details={"target": intent["target"]},
    )


def test_create_replay_transition_and_append_event_preserve_checksum_chain():
    store = SqlAlchemyOperationStore(clock=lambda: FIXED_NOW)
    spec = operation_spec()

    created = store.create(spec, event_payload={"token_secret": "must-not-persist"})
    replay = store.create(spec)
    dispatching = store.transition(
        spec.operation_id,
        next_status="dispatching",
        event_type="dispatch_prepared",
        stage="dispatch",
        payload={"attempt": 1},
        expected_statuses=["planned"],
    )
    observed = store.append_event(
        spec.operation_id,
        event_type="precheck_observed",
        stage="dispatch",
        payload={"status": "stopped"},
        details_patch={"last_observed_status": "stopped"},
        expected_statuses=["dispatching"],
    )
    events = store.list_events(spec.operation_id)

    assert created.created is True
    assert replay.created is False
    assert replay.operation.operation_id == created.operation.operation_id
    assert dispatching.status == "dispatching"
    assert observed.status == "dispatching"
    assert observed.version == 3
    assert observed.details["last_observed_status"] == "stopped"
    assert events[0].payload["token_secret"] == "[REDACTED]"
    assert [event.sequence for event in events] == [1, 2, 3]
    assert verify_event_chain(events) is True
    assert observed.last_event_checksum == events[-1].checksum


def test_same_scope_idempotency_with_different_intent_is_conflict():
    store = SqlAlchemyOperationStore(clock=lambda: FIXED_NOW)
    store.create(operation_spec())

    with pytest.raises(OperationIntentConflict) as raised:
        store.create(operation_spec(intent_suffix="changed"))

    assert raised.value.operation_id == "operation-vm-start-306"
    assert len(store.list_events("operation-vm-start-306")) == 1


def test_invalid_or_stale_transition_does_not_append_event():
    store = SqlAlchemyOperationStore(clock=lambda: FIXED_NOW)
    spec = operation_spec()
    store.create(spec)

    with pytest.raises(InvalidOperationTransition):
        store.transition(
            spec.operation_id,
            next_status="succeeded",
            event_type="invalid_skip",
            stage="verification",
        )
    with pytest.raises(OperationStateConflict):
        store.transition(
            spec.operation_id,
            next_status="dispatching",
            event_type="stale_dispatch",
            stage="dispatch",
            expected_statuses=["approved"],
        )

    assert store.get(spec.operation_id).version == 1
    assert len(store.list_events(spec.operation_id)) == 1


def test_projection_failure_rolls_back_event_append():
    store = SqlAlchemyOperationStore(clock=lambda: FIXED_NOW)
    spec = operation_spec()
    store.create(spec)

    with patch.object(store, "_apply_projection", side_effect=RuntimeError("projection failed")):
        with pytest.raises(RuntimeError):
            store.transition(
                spec.operation_id,
                next_status="dispatching",
                event_type="dispatch_prepared",
                stage="dispatch",
            )

    current = store.get(spec.operation_id)
    assert current.status == "planned"
    assert current.version == 1
    assert len(store.list_events(spec.operation_id)) == 1
