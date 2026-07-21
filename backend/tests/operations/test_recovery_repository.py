"""Repository tests for durable recovery lease fencing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import OperationLockRecord
from app.db.session import session_scope
from app.operations.core.domain import OperationActor, OperationSpec, operation_digest
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.recovery.domain import RecoveryLeaseLost, RecoverySpec
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.facade import get_operation


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def create_operation(clock: MutableClock, operation_id: str = "operation-recovery-306") -> None:
    intent = {"operation": "vm_start", "target": {"node_id": "node-a", "vmid": 306}}
    SqlAlchemyOperationStore(clock=clock).create(
        OperationSpec(
            operation_id=operation_id,
            operation_type="vm_start",
            execution_mode="managed_api",
            target_type="proxmox_vm",
            target_id="vmid:306",
            idempotency_key="idem-recovery-306",
            intent_digest=operation_digest(intent),
            plan_digest=operation_digest({"intent": intent, "version": 1}),
            actor=OperationActor(user_id="user-1", username="operator", role="operator"),
            initial_status="dispatching",
            initial_stage="start",
            details={"target": {"node_id": "node-a", "vmid": 306}, "proxmox_upid": "UPID:node-a:1:start"},
        )
    )


def recovery_spec(operation_id: str = "operation-recovery-306") -> RecoverySpec:
    return RecoverySpec(
        operation_id=operation_id,
        recovery_kind="vm_start_observation",
        details={"node_id": "node-a", "vmid": 306, "token_secret": "must-not-persist"},
    )


def test_prepare_heartbeat_and_public_item_redact_private_payload():
    clock = MutableClock()
    create_operation(clock)
    store = SqlAlchemyRecoveryStore(clock=clock)

    lease = store.prepare_and_claim(recovery_spec(), lease_owner="request-1", lease_seconds=30)
    clock.advance(10)
    renewed = store.heartbeat(lease, lease_seconds=30)
    item = store.get(lease.operation_id)

    assert item is not None
    assert item.status == "leased"
    assert item.lease_owner == "request-1"
    assert item.lease_generation == 1
    assert item.attempt_count == 1
    assert item.details["token_secret"] == "[REDACTED]"
    assert renewed.item.lease_expires_at == clock.now + timedelta(seconds=30)


def test_expired_lease_can_be_claimed_but_stale_worker_is_fenced():
    clock = MutableClock()
    create_operation(clock)
    store = SqlAlchemyRecoveryStore(clock=clock)
    stale = store.prepare_and_claim(recovery_spec(), lease_owner="worker-a", lease_seconds=10)

    clock.advance(11)
    claimed = store.claim_due(lease_owner="worker-b", lease_seconds=30)

    assert len(claimed) == 1
    assert claimed[0].generation == stale.generation + 1
    assert store.get(stale.operation_id).status == "leased"

    with pytest.raises(RecoveryLeaseLost):
        store.commit_observation(
            stale,
            event_type="stale_observation",
            stage="task_poll",
            recovery_status="retry_wait",
        )

    operation = SqlAlchemyOperationStore(clock=clock).get(stale.operation_id)
    assert operation is not None
    assert operation.version == 1


def test_fenced_completion_updates_operation_recovery_and_target_lock_atomically():
    clock = MutableClock()
    operation_id = "operation-recovery-306"
    create_operation(clock, operation_id)
    with session_scope() as session:
        session.add(
            OperationLockRecord(
                operation_lock_id="lock-recovery-306",
                operation_type="vm_start",
                scope_type="proxmox_locator",
                scope_key="gjallar-mvp|proxmox_locator|306",
                status="active",
                cluster_id="gjallar-mvp",
                vmid=306,
                owner_id=operation_id,
                reason="vm_start_dispatch",
                evidence={"operation_id": operation_id},
                created_at=clock.now,
                updated_at=clock.now,
            )
        )

    store = SqlAlchemyRecoveryStore(clock=clock)
    lease = store.prepare_and_claim(recovery_spec(operation_id), lease_owner="worker-a", lease_seconds=30)
    operation, item = store.commit_observation(
        lease,
        next_status="running",
        event_type="recovery_task_running",
        stage="task_poll",
        payload={"task": {"status": "running"}},
        details_patch={"recovery_observed": True},
        expected_statuses=["dispatching"],
        recovery_status="completed",
        release_target_lock=True,
    )

    assert operation.status == "running"
    assert operation.details["recovery_observed"] is True
    assert item.status == "completed"
    assert item.lease_owner is None
    with session_scope() as session:
        lock = session.get(OperationLockRecord, "lock-recovery-306")
        assert lock.status == "released"
        assert lock.reason == "verified_recovery_completed"


def test_invalid_operation_transition_rolls_back_recovery_and_lock_changes():
    clock = MutableClock()
    create_operation(clock)
    store = SqlAlchemyRecoveryStore(clock=clock)
    lease = store.prepare_and_claim(recovery_spec(), lease_owner="worker-a", lease_seconds=30)

    with pytest.raises(Exception):
        store.commit_observation(
            lease,
            next_status="succeeded",
            event_type="invalid_skip",
            stage="post_check",
            recovery_status="completed",
            release_target_lock=True,
        )

    item = store.get(lease.operation_id)
    operation = SqlAlchemyOperationStore(clock=clock).get(lease.operation_id)
    assert item.status == "leased"
    assert operation.status == "dispatching"


def test_operation_detail_exposes_recovery_and_target_lock_without_lease_token(monkeypatch):
    clock = MutableClock()
    operation_id = "operation-recovery-query"
    create_operation(clock, operation_id)
    with session_scope() as session:
        session.add(
            OperationLockRecord(
                operation_lock_id="lock-recovery-query",
                operation_type="vm_start",
                scope_type="proxmox_locator",
                scope_key="cluster-query|proxmox_locator|306",
                status="active",
                cluster_id="cluster-query",
                vmid=306,
                owner_id=operation_id,
                reason="vm_start_dispatch",
                evidence={"operation_id": operation_id},
                created_at=clock.now,
                updated_at=clock.now,
            )
        )
    SqlAlchemyRecoveryStore(clock=clock).prepare_and_claim(
        recovery_spec(operation_id),
        lease_owner="foreground-query",
        lease_seconds=30,
    )
    monkeypatch.setenv("GJALLAR_CLUSTER_ID", "cluster-query")

    detail = get_operation(operation_id)

    assert detail["recovery"]["status"] == "leased"
    assert detail["recovery"]["lease_owner"] == "foreground-query"
    assert "lease_token" not in detail["recovery"]
    assert detail["recovery"]["details"]["token_secret"] == "[REDACTED]"
    assert detail["target_lock"]["owner_id"] == operation_id
    assert detail["target_lock"]["durable"]["operation_type"] == "vm_start"
