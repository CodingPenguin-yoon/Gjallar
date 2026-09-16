"""Repository tests for durable recovery lease fencing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import JobRunRecord, OperationLockRecord
from app.db.session import session_scope
from app.operations.core.domain import OperationActor, OperationSpec, operation_digest
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.locks.infrastructure.repository import SqlAlchemyDurableTargetLockRepository
from app.operations.recovery.domain import (
    PRE_DISPATCH_RECOVERY_CONTRACT,
    RecoveryLeaseLost,
    RecoverySpec,
)
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
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    exact_lock = locks.acquire(
        operation_type="vm_start",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id="operation-recovery-306",
        reason="vm_start_dispatch",
    )
    store = SqlAlchemyRecoveryStore(clock=clock)
    stale = store.prepare_and_claim(
        RecoverySpec(
            operation_id="operation-recovery-306",
            recovery_kind="vm_start_observation",
            details={
                "node_id": "node-a",
                "vmid": 306,
                "target_lock_id": exact_lock.lock_id,
                "cluster_id": "gjallar-mvp",
            },
        ),
        lease_owner="worker-a",
        lease_seconds=10,
    )

    clock.advance(11)
    claimed = store.claim_due(lease_owner="worker-b", lease_seconds=30)

    assert len(claimed) == 1
    assert claimed[0].generation == stale.generation + 1
    assert store.get(stale.operation_id).status == "leased"

    projector_calls: list[str] = []

    with pytest.raises(RecoveryLeaseLost):
        store.commit_observation(
            stale,
            event_type="stale_observation",
            stage="task_poll",
            recovery_status="retry_wait",
            projector=lambda _session: projector_calls.append("called"),
        )

    operation = SqlAlchemyOperationStore(clock=clock).get(stale.operation_id)
    assert operation is not None
    assert operation.version == 1
    assert projector_calls == []


def test_projector_failure_rolls_back_compatibility_write_and_keeps_fenced_state():
    clock = MutableClock()
    operation_id = "operation-recovery-projector-rollback"
    job_id = "job-recovery-projector-rollback"
    create_operation(clock, operation_id)
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    exact_lock = locks.acquire(
        operation_type="vm_start",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="vm_start_dispatch",
    )
    store = SqlAlchemyRecoveryStore(clock=clock)
    lease = store.prepare_and_claim(
        RecoverySpec(
            operation_id=operation_id,
            recovery_kind="vm_start_observation",
            details={
                "node_id": "node-a",
                "vmid": 306,
                "target_lock_id": exact_lock.lock_id,
                "cluster_id": "gjallar-mvp",
            },
        ),
        lease_owner="worker-a",
        lease_seconds=30,
    )

    def failing_projector(session):
        session.add(
            JobRunRecord(
                job_id=job_id,
                job_type="vm_start",
                status="succeeded",
                target_id="vmid:306",
                risk_level="medium",
                started_at="2026-07-21T12:00:00+00:00",
                finished_at="2026-07-21T12:00:01+00:00",
                current_stage="completed",
                message="must roll back",
                progress_percent=100,
                steps=[],
                risks=[],
                details={"projected": True},
                artifact_count=0,
                risk_count=0,
                updated_at="2026-07-21T12:00:01+00:00",
            )
        )
        session.flush()
        raise RuntimeError("injected projector failure")

    with pytest.raises(RuntimeError, match="injected projector failure"):
        store.commit_observation(
            lease,
            next_status="running",
            event_type="recovery_task_running",
            stage="task_poll",
            expected_statuses=["dispatching"],
            recovery_status="completed",
            release_target_lock=True,
            projector=failing_projector,
        )

    operation = SqlAlchemyOperationStore(clock=clock).get(operation_id)
    item = store.get(operation_id)
    retained = locks.current(cluster_id="gjallar-mvp", vmid=306)
    assert operation is not None and operation.status == "dispatching" and operation.version == 1
    assert item is not None and item.status == "leased" and item.lease_generation == lease.generation
    assert retained is not None and retained.lock_id == exact_lock.lock_id and retained.status == "active"
    with session_scope() as session:
        assert session.get(JobRunRecord, job_id) is None


def test_paused_recovery_is_not_claimed_automatically_after_it_becomes_due():
    clock = MutableClock()
    operation_id = "operation-recovery-paused"
    create_operation(clock, operation_id)
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    exact_lock = locks.acquire(
        operation_type="vm_start",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="vm_start_dispatch",
    )
    store = SqlAlchemyRecoveryStore(clock=clock)
    lease = store.prepare_and_claim(
        RecoverySpec(
            operation_id=operation_id,
            recovery_kind="vm_start_observation",
            details={
                "node_id": "node-a",
                "vmid": 306,
                "target_lock_id": exact_lock.lock_id,
                "cluster_id": "gjallar-mvp",
            },
        ),
        lease_owner="foreground-request",
        lease_seconds=30,
    )
    store.commit_observation(
        lease,
        next_status="needs_reconciliation",
        event_type="recovery_state_mismatch",
        stage="reconciliation",
        expected_statuses=["dispatching"],
        recovery_status="paused",
        error_code="VM_START_RECOVERY_STATE_MISMATCH",
    )

    clock.advance(3600)

    assert store.claim_due(lease_owner="automatic-runner", lease_seconds=60, limit=10) == []
    item = store.get(operation_id)
    assert item is not None and item.status == "paused"
    retained = locks.current(cluster_id="gjallar-mvp", vmid=306)
    assert retained is not None and retained.status == "reconciliation_required"


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
    lease = store.prepare_and_claim(
        RecoverySpec(
            operation_id=operation_id,
            recovery_kind="vm_start_observation",
            details={
                "node_id": "node-a",
                "vmid": 306,
                "target_lock_id": "lock-recovery-306",
                "cluster_id": "gjallar-mvp",
            },
        ),
        lease_owner="worker-a",
        lease_seconds=30,
    )
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


def test_prepared_recovery_binds_exact_target_lock_into_operation_and_item_atomically():
    clock = MutableClock()
    operation_id = "guided-recovery-bind-306"
    operations = SqlAlchemyOperationStore(clock=clock)
    operation = operations.create(
        OperationSpec(
            operation_id=operation_id,
            operation_type="guided_qm_vm_unlock",
            execution_mode="guided_manual",
            target_type="proxmox_vm",
            target_id="vmid:306",
            idempotency_key=operation_id,
            intent_digest=operation_digest({"operation": "guided_qm_vm_unlock", "vmid": 306}),
            plan_digest=operation_digest({"plan": "qm unlock 306"}),
            actor=OperationActor(user_id="user-1", username="operator", role="operator"),
            initial_status="planned",
            initial_stage="plan_preparation",
            details={
                "target": {"node_id": "node-a", "vmid": 306},
                "observed_before": {"config_lock": "backup"},
                "instruction_exposed": False,
                "recovery_contract": PRE_DISPATCH_RECOVERY_CONTRACT,
            },
        ),
        event_payload={"instruction_exposed": False},
    ).operation
    recovery = SqlAlchemyRecoveryStore(clock=clock)
    lease = recovery.prepare_and_claim(
        RecoverySpec(
            operation_id=operation_id,
            recovery_kind="guided_qm_unlock_observation",
            details={
                "operation_type": "guided_qm_vm_unlock",
                "execution_mode": "guided_manual",
                "target_type": "proxmox_vm",
                "target_id": "vmid:306",
                "node_id": "node-a",
                "vmid": 306,
                "original_config_lock": "backup",
                "target_lock_id": "",
                "cluster_id": "",
                "phase": "plan_prepared",
            },
        ),
        lease_owner="guided-foreground",
        lease_seconds=30,
        expected_operation_version=operation.version,
        expected_operation_checksum=operation.last_event_checksum,
    )
    exact_lock = SqlAlchemyDurableTargetLockRepository(clock=clock).acquire(
        operation_type="guided_qm_vm_unlock",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="guided_qm_vm_unlock_dispatch",
    )
    evidence = {
        "target_type": "proxmox_vm",
        "target_id": "vmid:306",
        "owner_id": operation_id,
        "lock_id": "compatibility-file-lock-id",
        "acquired_at": clock.now.isoformat(),
        "durable": exact_lock.to_dict(),
    }

    bound_operation, bound_item = recovery.commit_observation(
        lease,
        event_type="guided_plan_target_lock_bound",
        stage="plan_preparation",
        payload={"target_operation_lock": evidence},
        details_patch={"target_operation_lock": evidence},
        expected_statuses=["planned"],
        recovery_status="leased",
        recovery_details_patch={
            "phase": "lock_acquired",
            "target_lock_id": exact_lock.lock_id,
            "cluster_id": exact_lock.cluster_id,
        },
        bind_target_lock=True,
        expected_operation_version=operation.version,
        expected_operation_checksum=operation.last_event_checksum,
    )

    assert bound_operation.details["target_operation_lock"] == evidence
    assert bound_item.details["target_lock_id"] == exact_lock.lock_id
    assert bound_item.details["cluster_id"] == exact_lock.cluster_id
    assert bound_item.status == "leased"
    assert operations.list_events(operation_id)[-1].event_type == "guided_plan_target_lock_bound"
    retained = SqlAlchemyDurableTargetLockRepository(clock=clock).current(
        cluster_id="gjallar-mvp",
        vmid=306,
    )
    assert retained is not None and retained.lock_id == exact_lock.lock_id


def test_target_lock_binding_checkpoint_rejects_a_non_active_durable_row_atomically():
    clock = MutableClock()
    operation_id = "guided-recovery-bind-stale-306"
    operations = SqlAlchemyOperationStore(clock=clock)
    operation = operations.create(
        OperationSpec(
            operation_id=operation_id,
            operation_type="guided_qm_vm_unlock",
            execution_mode="guided_manual",
            target_type="proxmox_vm",
            target_id="vmid:306",
            idempotency_key=operation_id,
            intent_digest=operation_digest({"operation": "guided_qm_vm_unlock", "vmid": 306}),
            plan_digest=operation_digest({"plan": "qm unlock 306"}),
            actor=OperationActor(user_id="user-1", username="operator", role="operator"),
            initial_status="planned",
            initial_stage="plan_preparation",
        )
    ).operation
    recovery = SqlAlchemyRecoveryStore(clock=clock)
    lease = recovery.prepare_and_claim(
        RecoverySpec(
            operation_id=operation_id,
            recovery_kind="guided_qm_unlock_observation",
            details={"target_lock_id": "", "cluster_id": ""},
        ),
        lease_owner="guided-foreground",
        lease_seconds=30,
    )
    exact_lock = SqlAlchemyDurableTargetLockRepository(clock=clock).acquire(
        operation_type="guided_qm_vm_unlock",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="guided_qm_vm_unlock_dispatch",
    )
    with session_scope() as session:
        row = session.get(OperationLockRecord, exact_lock.lock_id)
        row.status = "stale"
        row.reason = "simulated_pre_bind_race"
    evidence = {
        "target_type": "proxmox_vm",
        "target_id": "vmid:306",
        "owner_id": operation_id,
        "lock_id": "compatibility-file-lock-id",
        "durable": {**exact_lock.to_dict(), "status": "active"},
    }

    with pytest.raises(ValueError, match="binding checkpoint is not exact"):
        recovery.commit_observation(
            lease,
            event_type="guided_plan_target_lock_bound",
            stage="plan_preparation",
            payload={"target_operation_lock": evidence},
            details_patch={"target_operation_lock": evidence},
            expected_statuses=["planned"],
            recovery_status="leased",
            recovery_details_patch={
                "phase": "lock_acquired",
                "target_lock_id": exact_lock.lock_id,
                "cluster_id": exact_lock.cluster_id,
            },
            bind_target_lock=True,
            expected_operation_version=operation.version,
            expected_operation_checksum=operation.last_event_checksum,
        )

    assert operations.get(operation_id).details.get("target_operation_lock") is None
    assert recovery.get(operation_id).details["target_lock_id"] == ""
    retained = SqlAlchemyDurableTargetLockRepository(clock=clock).current(
        cluster_id="gjallar-mvp",
        vmid=306,
    )
    assert retained is not None and retained.status == "stale"


def test_completion_without_exact_lock_id_cannot_release_same_owner_lock():
    clock = MutableClock()
    operation_id = "operation-recovery-missing-exact-lock-id"
    create_operation(clock, operation_id)
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    retained = locks.acquire(
        operation_type="vm_start",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="same_owner_replacement_lock",
    )
    store = SqlAlchemyRecoveryStore(clock=clock)
    lease = store.prepare_and_claim(
        RecoverySpec(
            operation_id=operation_id,
            recovery_kind="vm_start_observation",
            details={
                "node_id": "node-a",
                "vmid": 306,
                "cluster_id": "gjallar-mvp",
            },
        ),
        lease_owner="stale-worker",
        lease_seconds=30,
    )

    with pytest.raises(ValueError, match="not exact"):
        store.commit_observation(
            lease,
            next_status="failed",
            event_type="must_not_release_replacement_lock",
            stage="reconciliation",
            expected_statuses=["dispatching"],
            recovery_status="completed",
            release_target_lock=True,
        )

    assert SqlAlchemyOperationStore(clock=clock).get(operation_id).status == "dispatching"
    assert store.get(operation_id).status == "leased"
    current = locks.current(cluster_id="gjallar-mvp", vmid=306)
    assert current is not None and current.lock_id == retained.lock_id


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


def test_existing_reconciliation_operation_can_record_binding_failure_without_a_lock():
    clock = MutableClock()
    operation_id = "operation-recovery-missing-lock-evidence"
    create_operation(clock, operation_id)
    operations = SqlAlchemyOperationStore(clock=clock)
    operation = operations.transition(
        operation_id,
        next_status="needs_reconciliation",
        event_type="external_effect_ambiguous",
        stage="reconciliation",
        expected_statuses=["dispatching"],
    )
    store = SqlAlchemyRecoveryStore(clock=clock)
    lease = store.prepare_and_claim(
        recovery_spec(operation_id),
        lease_owner="operator-observer",
        lease_seconds=30,
        expected_operation_version=operation.version,
        expected_operation_checksum=operation.last_event_checksum,
    )

    updated, item = store.commit_observation(
        lease,
        event_type="recovery_binding_mismatch",
        stage="reconciliation",
        payload={"reason": "target_lock_owner_mismatch"},
        expected_statuses=["needs_reconciliation"],
        recovery_status="paused",
        error_code="OPERATION_RECOVERY_BINDING_MISMATCH",
        expected_operation_version=operation.version,
        expected_operation_checksum=operation.last_event_checksum,
    )

    assert updated.status == "needs_reconciliation"
    assert item.status == "paused"
    assert item.last_error_code == "OPERATION_RECOVERY_BINDING_MISMATCH"
    assert operations.list_events(operation_id)[-1].event_type == "recovery_binding_mismatch"


def test_completion_releases_only_the_exact_operation_target_lock():
    clock = MutableClock()
    operation_id = "operation-recovery-exact-lock"
    create_operation(clock, operation_id)
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    exact = locks.acquire(
        operation_type="vm_start",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="vm_start_dispatch",
    )
    locks.acquire(
        operation_type="vm_start",
        cluster_id="gjallar-mvp",
        vmid=307,
        owner_id=operation_id,
        reason="unrelated_test_lock",
    )
    store = SqlAlchemyRecoveryStore(clock=clock)
    lease = store.prepare_and_claim(
        RecoverySpec(
            operation_id=operation_id,
            recovery_kind="vm_start_observation",
            details={
                "node_id": "node-a",
                "vmid": 306,
                "target_type": "proxmox_vm",
                "target_id": "vmid:306",
                "target_lock_id": exact.lock_id,
                "cluster_id": "gjallar-mvp",
            },
        ),
        lease_owner="worker-a",
        lease_seconds=30,
    )

    store.commit_observation(
        lease,
        next_status="failed",
        event_type="verified_side_effect_free_failure",
        stage="reconciliation",
        expected_statuses=["dispatching"],
        recovery_status="completed",
        release_target_lock=True,
    )

    assert locks.current(cluster_id="gjallar-mvp", vmid=306) is None
    unrelated = locks.current(cluster_id="gjallar-mvp", vmid=307)
    assert unrelated is not None and unrelated.owner_id == operation_id


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
    assert detail["recovery_available_actions"][0]["action"] == "observe"
