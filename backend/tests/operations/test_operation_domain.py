"""Unit tests for common Operation domain invariants."""

from datetime import datetime, timezone

import pytest

from app.operations.core.domain import (
    InvalidOperationTransition,
    OperationActor,
    OperationEvent,
    ensure_operation_transition,
    operation_digest,
    verify_event_chain,
)


def test_operation_digest_is_stable_for_mapping_order():
    first = operation_digest({"target": {"vmid": 306, "node": "node-a"}, "action": "vm_start"})
    second = operation_digest({"action": "vm_start", "target": {"node": "node-a", "vmid": 306}})

    assert first == second
    assert first.startswith("sha256:")


def test_transition_matrix_supports_managed_and_guided_lifecycles():
    for current, following in (
        ("planned", "dispatching"),
        ("dispatching", "running"),
        ("running", "verifying"),
        ("verifying", "succeeded"),
        ("planned", "awaiting_operator"),
        ("awaiting_operator", "awaiting_verification"),
        ("awaiting_verification", "verifying"),
        ("needs_reconciliation", "verifying"),
        ("expired", "needs_reconciliation"),
    ):
        ensure_operation_transition(current, following)


def test_terminal_and_skipped_transitions_are_rejected():
    for current, following in (("succeeded", "running"), ("planned", "succeeded"), ("running", "running")):
        with pytest.raises(InvalidOperationTransition):
            ensure_operation_transition(current, following)


def test_event_chain_rejects_sequence_or_checksum_tampering():
    actor = OperationActor(user_id="user-1", username="operator", role="operator")
    created_at = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    event = OperationEvent(
        event_id="event-1",
        operation_id="operation-1",
        sequence=2,
        event_type="operation_created",
        from_status=None,
        to_status="planned",
        stage="plan",
        actor=actor,
        payload={},
        previous_checksum="",
        checksum="sha256:invalid",
        created_at=created_at,
    )

    assert verify_event_chain([event]) is False
