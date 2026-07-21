"""Application tests for the allowlisted observation-only recovery runner."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.operations.core.domain import OperationActor, OperationSpec, operation_digest
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.locks.infrastructure.repository import SqlAlchemyDurableTargetLockRepository
from app.operations.recovery.application import OperationRecoveryRunner, VmStartRecoveryHandler
from app.operations.recovery.domain import RecoverySpec
from app.operations.recovery.infrastructure.job_projection import SqlAlchemyVmStartRecoveryJobProjection
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.recovery.runtime import RecoveryRuntimeConfig
from app.operations.recovery import runtime as recovery_runtime


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class ObservationClient:
    def __init__(self, *, task: dict | None = None, vm: dict | None = None, failure: Exception | None = None) -> None:
        self.task = task or {"status": "stopped", "exitstatus": "OK"}
        self.vm = vm or {"name": "vm-306", "status": "running"}
        self.failure = failure
        self.calls: list[tuple] = []

    def get_task_status(self, *, node: str, upid: str) -> dict:
        self.calls.append(("get_task_status", node, upid))
        if self.failure is not None:
            raise self.failure
        return dict(self.task)

    def get_vm_status(self, *, node: str, vmid: int) -> dict:
        self.calls.append(("get_vm_status", node, vmid))
        return dict(self.vm)


class RecordingProjection:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[dict] = []

    def record_terminal(self, **payload) -> None:
        self.calls.append(payload)
        if self.failure is not None:
            raise self.failure


def create_vm_start_operation(
    clock: MutableClock,
    *,
    operation_id: str,
    include_upid: bool = True,
) -> None:
    intent = {"operation": "vm_start", "target": {"node_id": "node-a", "vmid": 306}}
    details = {"target": {"node_id": "node-a", "vmid": 306}}
    if include_upid:
        details["proxmox_upid"] = "UPID:node-a:1:start"
    SqlAlchemyOperationStore(clock=clock).create(
        OperationSpec(
            operation_id=operation_id,
            operation_type="vm_start",
            execution_mode="managed_api",
            target_type="proxmox_vm",
            target_id="vmid:306",
            idempotency_key=f"idem-{operation_id}",
            intent_digest=operation_digest(intent),
            plan_digest=operation_digest({"intent": intent, "version": 1}),
            actor=OperationActor(user_id="user-1", username="operator", role="operator"),
            initial_status="dispatching",
            initial_stage="start",
            details=details,
        )
    )


def expired_restart_lease(
    clock: MutableClock,
    *,
    operation_id: str,
    details: dict | None = None,
):
    recovery = SqlAlchemyRecoveryStore(clock=clock)
    recovery.prepare_and_claim(
        RecoverySpec(
            operation_id=operation_id,
            recovery_kind="vm_start_observation",
            details=details or {"node_id": "node-a", "vmid": 306, "upid": "UPID:node-a:1:start"},
        ),
        lease_owner="foreground-request",
        lease_seconds=10,
    )
    clock.advance(11)
    leases = recovery.claim_due(lease_owner="restart-runner", lease_seconds=60)
    assert len(leases) == 1
    return recovery, leases[0]


def test_vm_start_recovery_observes_task_and_status_then_completes_and_releases_lock():
    clock = MutableClock()
    operation_id = "operation-restart-success"
    create_vm_start_operation(clock, operation_id=operation_id)
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    locks.acquire(
        operation_type="vm_start",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="vm_start_dispatch",
    )
    recovery, lease = expired_restart_lease(clock, operation_id=operation_id)
    client = ObservationClient()
    projection = RecordingProjection()
    file_releases: list[tuple[str, str, str]] = []
    handler = VmStartRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: client,
        compatibility_projection=projection,
        release_compatibility_lock=lambda *args: file_releases.append(args) or True,
    )

    result = handler.handle(lease)

    operation = SqlAlchemyOperationStore(clock=clock).get(operation_id)
    item = recovery.get(operation_id)
    assert result.outcome == "succeeded"
    assert operation is not None and operation.status == "succeeded"
    assert operation.details["recovered_after_restart"] is True
    assert item is not None and item.status == "completed"
    assert locks.current(cluster_id="gjallar-mvp", vmid=306) is None
    assert file_releases == [("proxmox_vm", "vmid:306", operation_id)]
    assert projection.calls[0]["operation_status"] == "succeeded"
    assert client.calls == [
        ("get_task_status", "node-a", "UPID:node-a:1:start"),
        ("get_vm_status", "node-a", 306),
    ]


def test_terminal_projection_failure_keeps_lock_and_retries_without_a_second_proxmox_read():
    clock = MutableClock()
    operation_id = "operation-restart-projection-retry"
    create_vm_start_operation(clock, operation_id=operation_id)
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    locks.acquire(
        operation_type="vm_start",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="vm_start_dispatch",
    )
    recovery, lease = expired_restart_lease(clock, operation_id=operation_id)
    client = ObservationClient()
    projection = RecordingProjection(failure=RuntimeError("job projection unavailable"))
    handler = VmStartRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: client,
        compatibility_projection=projection,
    )

    with pytest.raises(RuntimeError, match="job projection unavailable"):
        handler.handle(lease)

    assert SqlAlchemyOperationStore(clock=clock).get(operation_id).status == "succeeded"
    assert recovery.get(operation_id).status == "leased"
    assert locks.current(cluster_id="gjallar-mvp", vmid=306) is not None
    first_calls = list(client.calls)

    clock.advance(61)
    claimed = recovery.claim_due(lease_owner="projection-retry", lease_seconds=60)
    projection.failure = None
    result = handler.handle(claimed[0])

    assert result.outcome == "succeeded"
    assert recovery.get(operation_id).status == "completed"
    assert locks.current(cluster_id="gjallar-mvp", vmid=306) is None
    assert client.calls == first_calls


def test_vm_start_recovery_running_task_waits_without_redispatching():
    clock = MutableClock()
    operation_id = "operation-restart-running"
    create_vm_start_operation(clock, operation_id=operation_id)
    recovery, lease = expired_restart_lease(clock, operation_id=operation_id)
    client = ObservationClient(task={"status": "running"})
    handler = VmStartRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: client,
    )

    result = handler.handle(lease)

    operation = SqlAlchemyOperationStore(clock=clock).get(operation_id)
    item = recovery.get(operation_id)
    assert result.outcome == "retry_task_running"
    assert operation is not None and operation.status == "dispatching"
    assert item is not None and item.status == "retry_wait"
    assert item.available_at == clock.now + timedelta(seconds=5)
    assert client.calls == [("get_task_status", "node-a", "UPID:node-a:1:start")]


def test_vm_start_recovery_missing_task_reference_pauses_for_reconciliation():
    clock = MutableClock()
    operation_id = "operation-restart-missing-upid"
    create_vm_start_operation(clock, operation_id=operation_id, include_upid=False)
    recovery, lease = expired_restart_lease(
        clock,
        operation_id=operation_id,
        details={"node_id": "node-a", "vmid": 306},
    )
    handler = VmStartRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: ObservationClient(),
    )

    result = handler.handle(lease)

    operation = SqlAlchemyOperationStore(clock=clock).get(operation_id)
    item = recovery.get(operation_id)
    assert result.outcome == "paused_missing_task_reference"
    assert operation is not None and operation.status == "needs_reconciliation"
    assert item is not None and item.status == "paused"
    assert item.last_error_code == "VM_START_RECOVERY_TASK_REFERENCE_MISSING"


def test_runner_turns_observation_failure_into_bounded_retry():
    clock = MutableClock()
    operation_id = "operation-restart-network-error"
    create_vm_start_operation(clock, operation_id=operation_id)
    recovery, _ = expired_restart_lease(clock, operation_id=operation_id)
    handler = VmStartRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: ObservationClient(failure=RuntimeError("network unavailable")),
    )
    clock.advance(61)
    runner = OperationRecoveryRunner(
        recovery=recovery,
        handlers={"vm_start_observation": handler},
        worker_id="runner-2",
        lease_seconds=60,
    )

    results = runner.run_once()

    item = recovery.get(operation_id)
    operation = SqlAlchemyOperationStore(clock=clock).get(operation_id)
    assert [result.outcome for result in results] == ["retry_observation_failed"]
    assert item is not None and item.status == "retry_wait"
    assert item.last_error_code == "OPERATION_RECOVERY_OBSERVATION_FAILED"
    assert operation is not None and operation.status == "dispatching"


def test_recovery_runtime_is_disabled_by_default_and_bounds_timing(monkeypatch):
    monkeypatch.delenv("GJALLAR_OPERATION_RECOVERY_ENABLED", raising=False)
    monkeypatch.setenv("GJALLAR_OPERATION_RECOVERY_POLL_SECONDS", "0")
    monkeypatch.setenv("GJALLAR_OPERATION_RECOVERY_LEASE_SECONDS", "9999")

    config = RecoveryRuntimeConfig.from_env()

    assert config.enabled is False
    assert config.poll_seconds == 1
    assert config.lease_seconds == 900


def test_vm_start_recovery_job_projection_updates_legacy_jobs_read_model():
    from app.jobs.runs import get_job_run, record_job_run

    operation_id = "operation-recovery-job-projection"
    record_job_run(
        job_id=operation_id,
        job_type="vm_start",
        status="running",
        target_id="node-a:306:vm-306",
        risk_level="unknown",
        stage="task_poll",
        step_status="running",
        message="Waiting for task",
        details={"vm_start_result": {"status": "running"}},
    )

    SqlAlchemyVmStartRecoveryJobProjection().record_terminal(
        operation_id=operation_id,
        operation_status="succeeded",
        target={"node_id": "node-a", "vmid": 306},
        task={"status": "stopped", "exitstatus": "OK"},
        observed_after={"status": "running"},
    )

    job = get_job_run(operation_id)
    assert job["status"] == "completed"
    assert job["details"]["vm_start_result"]["recovered_after_restart"] is True


def test_recovery_loop_survives_a_transient_iteration_failure(monkeypatch):
    class FlakyRunner:
        def __init__(self) -> None:
            self.calls = 0

        def run_once(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary database outage")
            return []

    runner = FlakyRunner()
    monkeypatch.setattr(recovery_runtime, "build_recovery_runner", lambda **_kwargs: runner)

    async def exercise() -> None:
        stop_event = asyncio.Event()
        task = asyncio.create_task(
            recovery_runtime.run_recovery_loop(
                stop_event,
                config=RecoveryRuntimeConfig(enabled=True, poll_seconds=0.01, lease_seconds=60),
            )
        )
        for _ in range(100):
            if runner.calls >= 2:
                break
            await asyncio.sleep(0.005)
        stop_event.set()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(exercise())

    assert runner.calls >= 2
