"""Restart recovery contracts for graceful VM Shutdown."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.operations.core.domain import OperationActor, OperationSpec, operation_digest
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.locks.infrastructure.repository import SqlAlchemyDurableTargetLockRepository
from app.operations.recovery.application import VmShutdownRecoveryHandler
from app.operations.recovery.domain import RecoverySpec
from app.operations.recovery.infrastructure.job_projection import SqlAlchemyVmShutdownRecoveryJobProjection
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.recovery.runtime import RecoveryRuntimeConfig, build_recovery_runner
from app.operations.target_lock import get_target_operation_lock


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class ObservationOnlyClient:
    def __init__(self, *, task=None, observed=None) -> None:
        self.task = task or {"status": "stopped", "exitstatus": "OK"}
        self.observed = observed or {"name": "app", "status": "stopped"}
        self.calls = []

    def get_task_status(self, *, node: str, upid: str):
        self.calls.append(("get_task_status", node, upid))
        return dict(self.task)

    def get_vm_status(self, *, node: str, vmid: int):
        self.calls.append(("get_vm_status", node, vmid))
        return dict(self.observed)


class Projection:
    def __init__(self, *, failure=None) -> None:
        self.failure = failure
        self.calls = []

    def record_terminal(self, **payload):
        self.calls.append(payload)
        if self.failure is not None:
            raise self.failure

    def record_terminal_in_transaction(self, _transaction, **payload):
        self.record_terminal(**payload)


def create_operation(clock: Clock, operation_id: str) -> None:
    intent = {"operation": "vm_shutdown", "target": {"node_id": "node-a", "vmid": 306}}
    SqlAlchemyOperationStore(clock=clock).create(
        OperationSpec(
            operation_id=operation_id,
            operation_type="vm_shutdown",
            execution_mode="managed_api",
            target_type="proxmox_vm",
            target_id="vmid:306",
            idempotency_key=f"idem-{operation_id}",
            intent_digest=operation_digest(intent),
            plan_digest=operation_digest({"intent": intent, "version": 1}),
            actor=OperationActor(user_id="user-1", username="operator", role="operator"),
            initial_status="dispatching",
            initial_stage="shutdown",
            details={
                "target": {"node_id": "node-a", "vmid": 306},
                "proxmox_upid": "UPID:node-a:2:qmshutdown",
            },
        )
    )


def claim_after_restart(clock: Clock, operation_id: str):
    recovery = SqlAlchemyRecoveryStore(clock=clock)
    current_lock = get_target_operation_lock("proxmox_vm", "vmid:306")
    assert current_lock is not None
    recovery.prepare_and_claim(
        RecoverySpec(
            operation_id=operation_id,
            recovery_kind="vm_shutdown_observation",
            details={
                "node_id": "node-a",
                "vmid": 306,
                "upid": "UPID:node-a:2:qmshutdown",
                "cluster_id": "gjallar-mvp",
                "target_lock_id": current_lock["lock_id"],
            },
        ),
        lease_owner="foreground",
        lease_seconds=10,
    )
    clock.advance(11)
    claimed = recovery.claim_due(lease_owner="restart", lease_seconds=60)
    assert len(claimed) == 1
    return recovery, claimed[0]


def test_shutdown_restart_observes_only_then_completes_and_releases_lock():
    clock = Clock()
    operation_id = "shutdown-restart-success"
    create_operation(clock, operation_id)
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    locks.acquire(
        operation_type="vm_shutdown",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="vm_shutdown_dispatch",
    )
    recovery, lease = claim_after_restart(clock, operation_id)
    client = ObservationOnlyClient(
        task={
            "status": "stopped",
            "exitstatus": "OK",
            "polls": [{"opaque": "opaque-shutdown-recovery-task-value"}],
        },
        observed={
            "name": "app",
            "status": "stopped",
            "opaque": "opaque-shutdown-recovery-status-value",
        },
    )
    projection = Projection()
    releases = []
    handler = VmShutdownRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: client,
        compatibility_projection=projection,

        target_lock_reader=get_target_operation_lock,
    )

    result = handler.handle(lease)

    assert result.outcome == "succeeded"
    assert SqlAlchemyOperationStore(clock=clock).get(operation_id).status == "succeeded"
    assert recovery.get(operation_id).status == "completed"
    assert locks.current(cluster_id="gjallar-mvp", vmid=306) is None
    assert client.calls == [
        ("get_task_status", "node-a", "UPID:node-a:2:qmshutdown"),
        ("get_vm_status", "node-a", 306),
    ]
    assert not hasattr(client, "shutdown_vm")
    operation_store = SqlAlchemyOperationStore(clock=clock)
    serialized = repr(
        {
            "operation": operation_store.get(operation_id),
            "events": operation_store.list_events(operation_id),
            "recovery": recovery.get(operation_id),
            "projection": projection.calls,
        }
    )
    assert "opaque-shutdown-recovery-task-value" not in serialized
    assert "opaque-shutdown-recovery-status-value" not in serialized
    assert "polls" not in serialized


def test_shutdown_restart_state_mismatch_pauses_and_retains_lock():
    clock = Clock()
    operation_id = "shutdown-restart-mismatch"
    create_operation(clock, operation_id)
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    locks.acquire(
        operation_type="vm_shutdown",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="vm_shutdown_dispatch",
    )
    recovery, lease = claim_after_restart(clock, operation_id)
    handler = VmShutdownRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: ObservationOnlyClient(observed={"status": "running"}),
        target_lock_reader=get_target_operation_lock,
    )

    result = handler.handle(lease)

    assert result.outcome == "paused_state_mismatch"
    assert SqlAlchemyOperationStore(clock=clock).get(operation_id).status == "needs_reconciliation"
    assert recovery.get(operation_id).status == "paused"
    assert locks.current(cluster_id="gjallar-mvp", vmid=306) is not None


def test_shutdown_unknown_task_status_is_bounded_before_retry_persistence():
    clock = Clock()
    operation_id = "shutdown-restart-opaque-task-status"
    create_operation(clock, operation_id)
    SqlAlchemyDurableTargetLockRepository(clock=clock).acquire(
        operation_type="vm_shutdown",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="vm_shutdown_dispatch",
    )
    recovery, lease = claim_after_restart(clock, operation_id)
    opaque_status = "opaque-shutdown-retry-status"
    client = ObservationOnlyClient(task={"status": opaque_status})
    handler = VmShutdownRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: client,
        target_lock_reader=get_target_operation_lock,
    )

    result = handler.handle(lease)

    operation = SqlAlchemyOperationStore(clock=clock).get(operation_id)
    item = recovery.get(operation_id)
    assert result.outcome == "retry_task_running"
    assert item.status == "retry_wait"
    assert item.details["last_task_status"] == "unknown"
    serialized = repr(
        {
            "operation": operation,
            "events": SqlAlchemyOperationStore(clock=clock).list_events(operation_id),
            "recovery": item,
        }
    )
    assert opaque_status not in serialized


def test_shutdown_recovery_rejects_mismatched_recovery_kind_before_observation():
    clock = Clock()
    operation_id = "shutdown-recovery-kind-mismatch"
    create_operation(clock, operation_id)
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    locks.acquire(
        operation_type="vm_shutdown",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="vm_shutdown_dispatch",
    )
    recovery = SqlAlchemyRecoveryStore(clock=clock)
    lease = recovery.prepare_and_claim(
        RecoverySpec(
            operation_id=operation_id,
            recovery_kind="vm_start_observation",
            details={"node_id": "node-a", "vmid": 306, "upid": "UPID:node-a:2:qmshutdown"},
        ),
        lease_owner="binding-test",
        lease_seconds=60,
    )
    client = ObservationOnlyClient()
    projection = Projection()
    handler = VmShutdownRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: client,
        compatibility_projection=projection,

        target_lock_reader=get_target_operation_lock,
    )

    try:
        handler.handle(lease)
    except Exception:
        # Direct rejection and a durable pause are both acceptable fail-closed
        # outcomes, provided the mismatched lease cannot observe or release.
        pass

    operation = SqlAlchemyOperationStore(clock=clock).get(operation_id)
    item = recovery.get(operation_id)
    assert client.calls == []
    assert operation is not None and operation.status in {"dispatching", "needs_reconciliation"}
    assert item is not None and item.status in {"leased", "paused"}
    assert locks.current(cluster_id="gjallar-mvp", vmid=306) is not None


def test_shutdown_recovery_rejects_cluster_mismatch_before_observation():
    clock = Clock()
    operation_id = "shutdown-recovery-cluster-mismatch"
    create_operation(clock, operation_id)
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    locks.acquire(
        operation_type="vm_shutdown",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="vm_shutdown_dispatch",
    )
    recovery = SqlAlchemyRecoveryStore(clock=clock)
    lease = recovery.prepare_and_claim(
        RecoverySpec(
            operation_id=operation_id,
            recovery_kind="vm_shutdown_observation",
            details={
                "node_id": "node-a",
                "vmid": 306,
                "upid": "UPID:node-a:2:qmshutdown",
                "cluster_id": "other-cluster",
            },
        ),
        lease_owner="binding-test",
        lease_seconds=60,
    )
    client = ObservationOnlyClient()
    projection = Projection()
    handler = VmShutdownRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: client,
        compatibility_projection=projection,

        target_lock_reader=get_target_operation_lock,
    )

    result = handler.handle(lease)

    assert result.outcome == "paused_binding_mismatch"
    assert client.calls == []
    assert projection.calls == []
    assert recovery.get(operation_id).details["binding_error"] == "target_lock_cluster_mismatch"
    assert locks.current(cluster_id="gjallar-mvp", vmid=306) is not None


def test_shutdown_recovery_rejects_missing_target_lock_reader_before_observation():
    clock = Clock()
    operation_id = "shutdown-recovery-lock-reader-unavailable"
    create_operation(clock, operation_id)
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    locks.acquire(
        operation_type="vm_shutdown",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="vm_shutdown_dispatch",
    )
    recovery, lease = claim_after_restart(clock, operation_id)
    client = ObservationOnlyClient()
    handler = VmShutdownRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: client,
    )

    result = handler.handle(lease)

    assert result.outcome == "paused_binding_mismatch"
    assert client.calls == []
    assert recovery.get(operation_id).details["binding_error"] == "target_lock_reader_unavailable"
    assert locks.current(cluster_id="gjallar-mvp", vmid=306) is not None


def test_shutdown_recovery_rejects_missing_exact_target_lock_id_before_observation():
    clock = Clock()
    operation_id = "shutdown-recovery-missing-exact-lock-id"
    create_operation(clock, operation_id)
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    locks.acquire(
        operation_type="vm_shutdown",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="same_owner_replacement_lock",
    )
    recovery = SqlAlchemyRecoveryStore(clock=clock)
    lease = recovery.prepare_and_claim(
        RecoverySpec(
            operation_id=operation_id,
            recovery_kind="vm_shutdown_observation",
            details={
                "node_id": "node-a",
                "vmid": 306,
                "upid": "UPID:node-a:2:qmshutdown",
                "cluster_id": "gjallar-mvp",
            },
        ),
        lease_owner="binding-test",
        lease_seconds=60,
    )
    client = ObservationOnlyClient()
    handler = VmShutdownRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: client,
        target_lock_reader=get_target_operation_lock,
    )

    result = handler.handle(lease)

    assert result.outcome == "paused_binding_mismatch"
    assert client.calls == []
    assert recovery.get(operation_id).details["binding_error"] == "target_lock_id_missing"
    assert locks.current(cluster_id="gjallar-mvp", vmid=306) is not None


def test_shutdown_projection_failure_retries_without_another_proxmox_read():
    clock = Clock()
    operation_id = "shutdown-restart-projection-retry"
    create_operation(clock, operation_id)
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    locks.acquire(
        operation_type="vm_shutdown",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="vm_shutdown_dispatch",
    )
    recovery, lease = claim_after_restart(clock, operation_id)
    client = ObservationOnlyClient()
    projection = Projection(failure=RuntimeError("jobs unavailable"))
    handler = VmShutdownRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: client,
        compatibility_projection=projection,

        target_lock_reader=get_target_operation_lock,
    )

    with pytest.raises(RuntimeError, match="jobs unavailable"):
        handler.handle(lease)
    first_calls = list(client.calls)
    assert SqlAlchemyOperationStore(clock=clock).get(operation_id).status == "succeeded"
    assert recovery.get(operation_id).status == "leased"
    assert locks.current(cluster_id="gjallar-mvp", vmid=306) is not None

    clock.advance(61)
    claimed = recovery.claim_due(lease_owner="projection-retry", lease_seconds=60)
    projection.failure = None
    result = handler.handle(claimed[0])

    assert result.outcome == "succeeded"
    assert client.calls == first_calls
    assert recovery.get(operation_id).status == "completed"
    assert locks.current(cluster_id="gjallar-mvp", vmid=306) is None





def test_shutdown_recovery_job_projection_updates_legacy_jobs():
    from app.jobs.runs import get_job_run, record_job_run

    operation_id = "shutdown-recovery-job-projection"
    record_job_run(
        job_id=operation_id,
        job_type="vm_shutdown",
        status="running",
        target_id="node-a:306:app",
        risk_level="high",
        stage="task_poll",
        step_status="running",
        message="Waiting for shutdown",
        details={"vm_shutdown_result": {"status": "running"}},
    )

    SqlAlchemyVmShutdownRecoveryJobProjection().record_terminal(
        operation_id=operation_id,
        operation_status="succeeded",
        target={"node_id": "node-a", "vmid": 306},
        task={"status": "stopped", "exitstatus": "OK"},
        observed_after={"status": "stopped"},
    )

    job = get_job_run(operation_id)
    assert job["status"] == "completed"
    assert job["details"]["vm_shutdown_result"]["recovered_after_restart"] is True
    assert job["details"]["vm_shutdown_result"]["forced_stop_enabled"] is False


def test_shutdown_pre_dispatch_projection_can_create_missing_no_effect_job():
    from app.jobs.runs import get_job_run

    operation_id = "vm-shutdown-missing-pre-dispatch-projection"

    SqlAlchemyVmShutdownRecoveryJobProjection().record_terminal(
        operation_id=operation_id,
        operation_status="blocked",
        target={"node_id": "node-a", "vmid": 306},
        task={},
        observed_after={},
        mutation_dispatched=False,
    )

    job = get_job_run(operation_id)
    result = job["details"]["vm_shutdown_result"]
    assert job["status"] == "blocked"
    assert result["recovered_pre_dispatch"] is True
    assert result["proxmox_shutdown_ran"] is False
    assert result["proxmox_mutation_enabled"] is False
    assert result["side_effects"] == []


def test_runtime_allowlists_start_and_shutdown_observation_handlers():
    runner = build_recovery_runner(
        config=RecoveryRuntimeConfig(enabled=True, poll_seconds=5, lease_seconds=60)
    )

    assert set(runner._handlers) == {
        "guided_qm_unlock_observation",
        "vm_create_observation",
        "vm_compute_observation",
        "vm_disk_observation",
        "vm_network_observation",
        "vm_clone_observation",
        "vm_delete_observation",
        "vm_template_observation",
        "vm_image_build_observation",
        "vm_image_cleanup_observation",
        "vm_backup_observation",
        "vm_restore_observation",
        "vm_migrate_observation",
        "host_storage_observation",
        "host_network_observation",
        "vm_shutdown_observation",
        "vm_start_observation",
    }
