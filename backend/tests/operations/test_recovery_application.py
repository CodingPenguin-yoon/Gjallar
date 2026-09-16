"""Application tests for the allowlisted observation-only recovery runner."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.operations.core.domain import OperationActor, OperationSpec, operation_digest
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.locks.infrastructure.repository import SqlAlchemyDurableTargetLockRepository
from app.operations.recovery.application import (
    OperationRecoveryCoordinator,
    OperationRecoveryObserveError,
    OperationRecoveryRunner,
    RecoveryRunResult,
    VmShutdownRecoveryHandler,
    VmStartRecoveryHandler,
)
from app.operations.recovery.domain import PRE_DISPATCH_RECOVERY_CONTRACT, RecoverySpec
from app.operations.recovery.infrastructure.job_projection import SqlAlchemyVmStartRecoveryJobProjection
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.target_lock import get_target_operation_lock
from app.operations.vm_create.recovery import VmCreateRecoveryHandler
from app.operations.recovery.runtime import RecoveryRuntimeConfig
from app.operations.recovery import runtime as recovery_runtime


def _observe_digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


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

    def record_terminal_in_transaction(self, _transaction, **payload) -> None:
        self.record_terminal(**payload)


def create_vm_start_operation(
    clock: MutableClock,
    *,
    operation_id: str,
    include_upid: bool = True,
    operation_type: str = "vm_start",
    vmid: int = 306,
    include_recovery_contract: bool = True,
    initial_status: str = "dispatching",
    upid: str = "UPID:node-a:1:start",
) -> None:
    intent = {"operation": operation_type, "target": {"node_id": "node-a", "vmid": vmid}}
    details = {"target": {"node_id": "node-a", "vmid": vmid}}
    if include_recovery_contract:
        details["recovery_contract"] = PRE_DISPATCH_RECOVERY_CONTRACT
    if include_upid:
        details["proxmox_upid"] = upid
    SqlAlchemyOperationStore(clock=clock).create(
        OperationSpec(
            operation_id=operation_id,
            operation_type=operation_type,
            execution_mode="managed_api",
            target_type="proxmox_vm",
            target_id=f"vmid:{vmid}",
            idempotency_key=f"idem-{operation_id}",
            intent_digest=operation_digest(intent),
            plan_digest=operation_digest({"intent": intent, "version": 1}),
            actor=OperationActor(user_id="user-1", username="operator", role="operator"),
            initial_status=initial_status,
            initial_stage="start" if operation_type == "vm_start" else "shutdown",
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
    recovery_details = dict(details) if details is not None else {
        "node_id": "node-a",
        "vmid": 306,
        "upid": "UPID:node-a:1:start",
        "cluster_id": "gjallar-mvp",
    }
    current_lock = get_target_operation_lock(
        "proxmox_vm",
        f"vmid:{int(recovery_details.get('vmid') or 306)}",
    )
    if current_lock is not None:
        recovery_details.setdefault("target_lock_id", current_lock["lock_id"])
        recovery_details.setdefault(
            "cluster_id",
            str(dict(current_lock.get("durable") or {}).get("cluster_id") or ""),
        )
    recovery.prepare_and_claim(
        RecoverySpec(
            operation_id=operation_id,
            recovery_kind="vm_start_observation",
            details=recovery_details,
        ),
        lease_owner="foreground-request",
        lease_seconds=10,
    )
    clock.advance(11)
    leases = recovery.claim_due(lease_owner="restart-runner", lease_seconds=60)
    assert len(leases) == 1
    return recovery, leases[0]


def assert_recovery_binding_is_rejected(
    *,
    clock: MutableClock,
    operation_id: str,
    recovery: SqlAlchemyRecoveryStore,
    lease,
    client: ObservationClient,
    locks: SqlAlchemyDurableTargetLockRepository,
    locked_vmid: int,
) -> None:
    projection = RecordingProjection()
    handler = VmStartRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: client,
        compatibility_projection=projection,

        target_lock_reader=get_target_operation_lock,
    )

    result = handler.handle(lease)

    operation = SqlAlchemyOperationStore(clock=clock).get(operation_id)
    item = recovery.get(operation_id)
    assert result.outcome == "paused_binding_mismatch"
    assert client.calls == []
    assert projection.calls == []
    assert operation is not None and operation.status == "needs_reconciliation"
    assert item is not None and item.status == "paused"
    assert locks.current(cluster_id="gjallar-mvp", vmid=locked_vmid) is not None
    from app.operations.facade import get_operation

    detail = get_operation(operation_id)
    assert detail["recovery_available_actions"] == []
    assert detail["recovery"]["manual_action_required"] is True


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
    client = ObservationClient(
        task={
            "status": "stopped",
            "exitstatus": "OK",
            "polls": [{"opaque": "opaque-start-recovery-task-value"}],
        },
        vm={
            "name": "vm-306",
            "status": "running",
            "opaque": "opaque-start-recovery-status-value",
        },
    )
    projection = RecordingProjection()
    handler = VmStartRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: client,
        compatibility_projection=projection,

        target_lock_reader=get_target_operation_lock,
    )

    result = handler.handle(lease)

    operation = SqlAlchemyOperationStore(clock=clock).get(operation_id)
    item = recovery.get(operation_id)
    assert result.outcome == "succeeded"
    assert operation is not None and operation.status == "succeeded"
    assert operation.details["recovered_after_restart"] is True
    assert item is not None and item.status == "completed"
    assert locks.current(cluster_id="gjallar-mvp", vmid=306) is None
    assert projection.calls[0]["operation_status"] == "succeeded"
    assert client.calls == [
        ("get_task_status", "node-a", "UPID:node-a:1:start"),
        ("get_vm_status", "node-a", 306),
    ]
    serialized = repr(
        {
            "operation": operation,
            "events": SqlAlchemyOperationStore(clock=clock).list_events(operation_id),
            "recovery": item,
            "projection": projection.calls,
        }
    )
    assert "opaque-start-recovery-task-value" not in serialized
    assert "opaque-start-recovery-status-value" not in serialized
    assert "polls" not in serialized


@pytest.mark.parametrize(
    (
        "operation_type",
        "recovery_kind",
        "operation_vmid",
        "recovery_vmid",
        "lock_operation_type",
        "locked_vmid",
    ),
    [
        pytest.param("vm_start", "vm_shutdown_observation", 306, 306, "vm_start", 306, id="recovery-kind"),
        pytest.param("vm_shutdown", "vm_start_observation", 306, 306, "vm_shutdown", 306, id="operation-type"),
        pytest.param("vm_start", "vm_start_observation", 306, 307, "vm_start", 306, id="recovery-target"),
        pytest.param("vm_start", "vm_start_observation", 306, 306, "vm_start", 307, id="exact-lock"),
    ],
)
def test_vm_start_recovery_rejects_non_exact_binding_before_observation(
    operation_type,
    recovery_kind,
    operation_vmid,
    recovery_vmid,
    lock_operation_type,
    locked_vmid,
):
    clock = MutableClock()
    operation_id = f"operation-recovery-binding-{operation_type}-{recovery_kind}-{recovery_vmid}-{locked_vmid}"
    create_vm_start_operation(
        clock,
        operation_id=operation_id,
        operation_type=operation_type,
        vmid=operation_vmid,
    )
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    locks.acquire(
        operation_type=lock_operation_type,
        cluster_id="gjallar-mvp",
        vmid=locked_vmid,
        owner_id=operation_id,
        reason=f"{lock_operation_type}_dispatch",
    )
    recovery = SqlAlchemyRecoveryStore(clock=clock)
    lease = recovery.prepare_and_claim(
        RecoverySpec(
            operation_id=operation_id,
            recovery_kind=recovery_kind,
            details={"node_id": "node-a", "vmid": recovery_vmid, "upid": "UPID:node-a:1:start"},
        ),
        lease_owner="binding-test",
        lease_seconds=60,
    )

    assert_recovery_binding_is_rejected(
        clock=clock,
        operation_id=operation_id,
        recovery=recovery,
        lease=lease,
        client=ObservationClient(),
        locks=locks,
        locked_vmid=locked_vmid,
    )


@pytest.mark.parametrize(
    "recovery_details",
    [
        pytest.param(
            {"node_id": "node-b", "vmid": 306, "upid": "UPID:node-a:1:start"},
            id="node",
        ),
        pytest.param(
            {"node_id": "node-a", "vmid": 306, "upid": "UPID:node-a:2:other"},
            id="upid",
        ),
    ],
)
def test_vm_start_recovery_rejects_mismatched_observation_locator(recovery_details):
    clock = MutableClock()
    operation_id = f"operation-recovery-locator-{recovery_details['node_id']}-{recovery_details['upid']}"
    create_vm_start_operation(clock, operation_id=operation_id)
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    locks.acquire(
        operation_type="vm_start",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="vm_start_dispatch",
    )
    recovery = SqlAlchemyRecoveryStore(clock=clock)
    lease = recovery.prepare_and_claim(
        RecoverySpec(
            operation_id=operation_id,
            recovery_kind="vm_start_observation",
            details=recovery_details,
        ),
        lease_owner="binding-test",
        lease_seconds=60,
    )

    assert_recovery_binding_is_rejected(
        clock=clock,
        operation_id=operation_id,
        recovery=recovery,
        lease=lease,
        client=ObservationClient(),
        locks=locks,
        locked_vmid=306,
    )


def test_vm_start_recovery_rejects_cluster_mismatch_before_observation():
    clock = MutableClock()
    operation_id = "operation-recovery-cluster-mismatch"
    create_vm_start_operation(clock, operation_id=operation_id)
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    locks.acquire(
        operation_type="vm_start",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="vm_start_dispatch",
    )
    recovery = SqlAlchemyRecoveryStore(clock=clock)
    lease = recovery.prepare_and_claim(
        RecoverySpec(
            operation_id=operation_id,
            recovery_kind="vm_start_observation",
            details={
                "node_id": "node-a",
                "vmid": 306,
                "upid": "UPID:node-a:1:start",
                "cluster_id": "other-cluster",
            },
        ),
        lease_owner="binding-test",
        lease_seconds=60,
    )

    assert_recovery_binding_is_rejected(
        clock=clock,
        operation_id=operation_id,
        recovery=recovery,
        lease=lease,
        client=ObservationClient(),
        locks=locks,
        locked_vmid=306,
    )
    assert recovery.get(operation_id).details["binding_error"] == "target_lock_cluster_mismatch"


def test_vm_start_recovery_rejects_and_scrubs_invalid_stored_upid_before_observation():
    clock = MutableClock()
    operation_id = "operation-recovery-invalid-upid"
    opaque_locator = "opaque-secret?token=do-not-store"
    create_vm_start_operation(clock, operation_id=operation_id, upid=opaque_locator)
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    locks.acquire(
        operation_type="vm_start",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="vm_start_dispatch",
    )
    recovery, lease = expired_restart_lease(
        clock,
        operation_id=operation_id,
        details={
            "node_id": "node-a",
            "vmid": 306,
            "upid": opaque_locator,
            "cluster_id": "gjallar-mvp",
        },
    )
    client = ObservationClient()
    handler = VmStartRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: client,
        target_lock_reader=get_target_operation_lock,
    )

    result = handler.handle(lease)

    operation = SqlAlchemyOperationStore(clock=clock).get(operation_id)
    item = recovery.get(operation_id)
    assert result.outcome == "paused_binding_mismatch"
    assert client.calls == []
    assert operation.details["proxmox_upid"] == ""
    assert item.details["upid"] == ""
    assert item.details["binding_error"] == "operation_task_reference_invalid"
    assert opaque_locator not in json.dumps(
        {
            "operation": operation.details,
            "last_event": SqlAlchemyOperationStore(clock=clock).list_events(operation_id)[-1].payload,
            "recovery": item.details,
        },
        sort_keys=True,
    )


def test_vm_start_recovery_rejects_missing_target_lock_reader_before_observation():
    clock = MutableClock()
    operation_id = "operation-recovery-lock-reader-unavailable"
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
    handler = VmStartRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: client,
    )

    result = handler.handle(lease)

    assert result.outcome == "paused_binding_mismatch"
    assert client.calls == []
    assert recovery.get(operation_id).details["binding_error"] == "target_lock_reader_unavailable"
    assert locks.current(cluster_id="gjallar-mvp", vmid=306) is not None


def test_vm_start_recovery_rejects_missing_exact_target_lock_id_before_observation():
    clock = MutableClock()
    operation_id = "operation-recovery-missing-exact-lock-id"
    create_vm_start_operation(clock, operation_id=operation_id)
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    locks.acquire(
        operation_type="vm_start",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="same_owner_replacement_lock",
    )
    recovery, lease = expired_restart_lease(
        clock,
        operation_id=operation_id,
        details={
            "node_id": "node-a",
            "vmid": 306,
            "upid": "UPID:node-a:1:start",
            "cluster_id": "gjallar-mvp",
            "target_lock_id": "",
        },
    )
    client = ObservationClient()

    assert_recovery_binding_is_rejected(
        clock=clock,
        operation_id=operation_id,
        recovery=recovery,
        lease=lease,
        client=client,
        locks=locks,
        locked_vmid=306,
    )
    assert recovery.get(operation_id).details["binding_error"] == "target_lock_id_missing"


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

        target_lock_reader=get_target_operation_lock,
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
    SqlAlchemyDurableTargetLockRepository(clock=clock).acquire(
        operation_type="vm_start",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="vm_start_dispatch",
    )
    recovery, lease = expired_restart_lease(clock, operation_id=operation_id)
    opaque_status = "opaque-start-retry-status"
    client = ObservationClient(task={"status": opaque_status})
    handler = VmStartRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: client,
        target_lock_reader=get_target_operation_lock,
    )

    result = handler.handle(lease)

    operation = SqlAlchemyOperationStore(clock=clock).get(operation_id)
    item = recovery.get(operation_id)
    assert result.outcome == "retry_task_running"
    assert operation is not None and operation.status == "dispatching"
    assert item is not None and item.status == "retry_wait"
    assert item.details["last_task_status"] == "unknown"
    assert item.available_at == clock.now + timedelta(seconds=5)
    assert client.calls == [("get_task_status", "node-a", "UPID:node-a:1:start")]
    from app.operations.facade import get_operation

    assert [
        action["action"] for action in get_operation(operation_id)["recovery_available_actions"]
    ] == ["observe"]
    serialized = repr(
        {
            "operation": operation,
            "events": SqlAlchemyOperationStore(clock=clock).list_events(operation_id),
            "recovery": item,
        }
    )
    assert opaque_status not in serialized


def test_vm_start_recovery_missing_task_reference_pauses_for_reconciliation():
    clock = MutableClock()
    operation_id = "operation-restart-missing-upid"
    create_vm_start_operation(clock, operation_id=operation_id, include_upid=False)
    SqlAlchemyDurableTargetLockRepository(clock=clock).acquire(
        operation_type="vm_start",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="vm_start_dispatch",
    )
    recovery, lease = expired_restart_lease(
        clock,
        operation_id=operation_id,
        details={"node_id": "node-a", "vmid": 306, "cluster_id": "gjallar-mvp"},
    )
    handler = VmStartRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: ObservationClient(),
        target_lock_reader=get_target_operation_lock,
    )

    result = handler.handle(lease)

    operation = SqlAlchemyOperationStore(clock=clock).get(operation_id)
    item = recovery.get(operation_id)
    assert result.outcome == "paused_missing_task_reference"
    assert operation is not None and operation.status == "needs_reconciliation"
    assert item is not None and item.status == "paused"
    assert item.last_error_code == "VM_START_RECOVERY_TASK_REFERENCE_MISSING"
    from app.operations.facade import get_operation

    detail = get_operation(operation_id)
    assert detail["recovery_available_actions"] == []
    assert detail["recovery"]["manual_action_required"] is True


def test_runner_turns_observation_failure_into_bounded_retry():
    clock = MutableClock()
    operation_id = "operation-restart-network-error"
    create_vm_start_operation(clock, operation_id=operation_id)
    SqlAlchemyDurableTargetLockRepository(clock=clock).acquire(
        operation_type="vm_start",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="vm_start_dispatch",
    )
    recovery, _ = expired_restart_lease(clock, operation_id=operation_id)
    handler = VmStartRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: ObservationClient(failure=RuntimeError("network unavailable")),
        target_lock_reader=get_target_operation_lock,
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


def test_operator_observe_claims_paused_item_and_records_actor_before_get_only_recovery():
    clock = MutableClock()
    operation_id = "operation-operator-observe-paused"
    create_vm_start_operation(clock, operation_id=operation_id)
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    exact_lock = locks.acquire(
        operation_type="vm_start",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="vm_start_dispatch",
    )
    recovery = SqlAlchemyRecoveryStore(clock=clock)
    lease = recovery.prepare_and_claim(
        RecoverySpec(
            operation_id=operation_id,
            recovery_kind="vm_start_observation",
            details={
                "node_id": "node-a",
                "vmid": 306,
                "upid": "UPID:node-a:1:start",
                "target_type": "proxmox_vm",
                "target_id": "vmid:306",
                "cluster_id": "gjallar-mvp",
                "target_lock_id": exact_lock.lock_id,
            },
        ),
        lease_owner="foreground",
        lease_seconds=60,
    )
    operation, _ = recovery.commit_observation(
        lease,
        next_status="needs_reconciliation",
        event_type="recovery_state_mismatch",
        stage="reconciliation",
        expected_statuses=["dispatching"],
        recovery_status="paused",
    )
    client = ObservationClient()
    handler = VmStartRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: client,

        target_lock_reader=get_target_operation_lock,
    )
    runner = OperationRecoveryRunner(
        recovery=recovery,
        handlers={"vm_start_observation": handler},
        worker_id="automatic-runner",
    )
    coordinator = OperationRecoveryCoordinator(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        runner=runner,
        lock_reader=get_target_operation_lock,
        worker_id="operator-request",
    )

    observe_key = "observe-token-secret-password-v2"
    result = coordinator.observe(
        operation_id,
        actor=OperationActor(user_id="user-1", username="operator", role="operator"),
        expected_version=operation.version,
        expected_checksum=operation.last_event_checksum,
        idempotency_key=observe_key,
    )

    assert result["outcome"] == "succeeded"
    event_count = len(SqlAlchemyOperationStore(clock=clock).list_events(operation_id))
    replay = coordinator.observe(
        operation_id,
        actor=OperationActor(user_id="user-1", username="operator", role="operator"),
        expected_version=operation.version,
        expected_checksum=operation.last_event_checksum,
        idempotency_key=observe_key,
    )

    assert replay["outcome"] == "succeeded"
    assert replay["idempotent_replay"] is True
    assert recovery.get(operation_id).status == "completed"
    assert locks.current(cluster_id="gjallar-mvp", vmid=306) is None
    assert client.calls == [
        ("get_task_status", "node-a", "UPID:node-a:1:start"),
        ("get_vm_status", "node-a", 306),
    ]
    events = SqlAlchemyOperationStore(clock=clock).list_events(operation_id)
    requested = next(event for event in events if event.event_type == "operator_recovery_observation_requested")
    assert requested.actor.username == "operator"
    assert requested.payload["observation_only"] is True
    assert requested.payload["idempotency_key_digest"] == _observe_digest(observe_key)
    assert "idempotency_key" not in requested.payload
    recovery_details = recovery.get(operation_id).details
    assert recovery_details["last_operator_observe_key_digest"] == _observe_digest(observe_key)
    assert recovery_details["operator_observe_requests"] == [
        {
            "idempotency_key_digest": _observe_digest(observe_key),
            "expected_version": operation.version,
            "expected_checksum": operation.last_event_checksum,
        }
    ]
    assert "last_operator_observe_key" not in recovery_details
    assert observe_key not in str(requested.payload)
    assert observe_key not in str(recovery_details)
    assert len(events) == event_count


def test_same_operator_observe_request_with_live_lease_returns_stable_in_progress_conflict():
    clock = MutableClock()
    operation_id = "operation-operator-observe-live-replay"
    create_vm_start_operation(clock, operation_id=operation_id)
    recovery = SqlAlchemyRecoveryStore(clock=clock)
    operation = SqlAlchemyOperationStore(clock=clock).get(operation_id)
    lease = recovery.prepare_and_claim(
        RecoverySpec(
            operation_id=operation_id,
            recovery_kind="vm_start_observation",
            details={"node_id": "node-a", "vmid": 306, "upid": "UPID:node-a:1:start"},
        ),
        lease_owner="operator-request",
        lease_seconds=60,
        expected_operation_version=operation.version,
        expected_operation_checksum=operation.last_event_checksum,
    )
    recovery.commit_observation(
        lease,
        event_type="operator_recovery_observation_requested",
        stage="reconciliation",
        payload={
            "idempotency_key_digest": _observe_digest("observe-live-v1"),
            "observation_only": True,
        },
        expected_statuses=[operation.status],
        recovery_status="leased",
        recovery_details_patch={
            "last_operator_observe_key_digest": _observe_digest("observe-live-v1"),
            "last_operator_observe_expected_version": operation.version,
            "last_operator_observe_expected_checksum": operation.last_event_checksum,
        },
        expected_operation_version=operation.version,
        expected_operation_checksum=operation.last_event_checksum,
    )
    runner = OperationRecoveryRunner(
        recovery=recovery,
        handlers={},
        worker_id="automatic-runner",
    )
    coordinator = OperationRecoveryCoordinator(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        runner=runner,
        lock_reader=get_target_operation_lock,
        worker_id="operator-request-2",
        clock=clock,
    )

    with pytest.raises(OperationRecoveryObserveError) as raised:
        coordinator.observe(
            operation_id,
            actor=OperationActor(user_id="user-1", username="operator", role="operator"),
            expected_version=operation.version,
            expected_checksum=operation.last_event_checksum,
            idempotency_key="observe-live-v1",
        )

    assert raised.value.code == "OPERATION_RECOVERY_OBSERVATION_IN_PROGRESS"
    assert raised.value.status_code == 409
    assert raised.value.details["idempotent_replay"] is True
    assert recovery.get(operation_id).status == "leased"


def test_same_operator_observe_request_with_corrupt_version_fence_is_stable_conflict():
    item = SimpleNamespace(
        operation_id="operation-corrupt-observe-fence",
        details={
            "last_operator_observe_key_digest": _observe_digest("observe-v1"),
            "last_operator_observe_expected_version": "not-an-integer",
            "last_operator_observe_expected_checksum": "sha256:expected",
        },
    )

    with pytest.raises(OperationRecoveryObserveError) as raised:
        OperationRecoveryCoordinator._same_observe_request(
            item,
            idempotency_key_digest=_observe_digest("observe-v1"),
            expected_version=4,
            expected_checksum="sha256:expected",
        )

    assert raised.value.code == "OPERATION_RECOVERY_IDEMPOTENCY_CONFLICT"
    assert raised.value.status_code == 409


def test_operator_observe_key_reuse_after_another_key_keeps_first_fence_conflict():
    clock = MutableClock()
    operation_id = "operation-observe-ledger-k1-k2-k1"
    create_vm_start_operation(clock, operation_id=operation_id)
    operations = SqlAlchemyOperationStore(clock=clock)
    recovery = SqlAlchemyRecoveryStore(clock=clock)
    operation = operations.get(operation_id)
    lease = recovery.prepare_and_claim(
        RecoverySpec(
            operation_id=operation_id,
            recovery_kind="vm_start_observation",
            details={"node_id": "node-a", "vmid": 306, "upid": "UPID:node-a:1:start"},
        ),
        lease_owner="seed",
        lease_seconds=60,
        expected_operation_version=operation.version,
        expected_operation_checksum=operation.last_event_checksum,
    )
    recovery.commit_observation(
        lease,
        event_type="recovery_seeded",
        stage="reconciliation",
        expected_statuses=[operation.status],
        recovery_status="retry_wait",
    )

    class RetryingRunner:
        def __init__(self):
            self.calls = []

        def supports(self, recovery_kind):
            return recovery_kind == "vm_start_observation"

        def run_claimed(self, claimed):
            self.calls.append(claimed.operation_id)
            current = operations.get(claimed.operation_id)
            recovery.commit_observation(
                claimed,
                event_type="test_operator_observation_completed",
                stage="reconciliation",
                expected_statuses=[current.status],
                recovery_status="retry_wait",
                expected_operation_version=current.version,
                expected_operation_checksum=current.last_event_checksum,
            )
            return RecoveryRunResult(claimed.operation_id, "retry_task_running")

    runner = RetryingRunner()
    coordinator = OperationRecoveryCoordinator(
        recovery=recovery,
        operations=operations,
        runner=runner,
        lock_reader=lambda *_args: None,
        worker_id="operator-observe-ledger",
        clock=clock,
    )
    actor = OperationActor(user_id="user-1", username="operator", role="operator")

    first_fence = operations.get(operation_id)
    coordinator.observe(
        operation_id,
        actor=actor,
        expected_version=first_fence.version,
        expected_checksum=first_fence.last_event_checksum,
        idempotency_key="observe-k1",
    )
    second_fence = operations.get(operation_id)
    coordinator.observe(
        operation_id,
        actor=actor,
        expected_version=second_fence.version,
        expected_checksum=second_fence.last_event_checksum,
        idempotency_key="observe-k2",
    )
    current_fence = operations.get(operation_id)

    with pytest.raises(OperationRecoveryObserveError) as raised:
        coordinator.observe(
            operation_id,
            actor=actor,
            expected_version=current_fence.version,
            expected_checksum=current_fence.last_event_checksum,
            idempotency_key="observe-k1",
        )

    assert raised.value.code == "OPERATION_RECOVERY_IDEMPOTENCY_CONFLICT"
    assert raised.value.status_code == 409
    assert runner.calls == [operation_id, operation_id]
    ledger = recovery.get(operation_id).details["operator_observe_requests"]
    assert [record["idempotency_key_digest"] for record in ledger] == [
        _observe_digest("observe-k1"),
        _observe_digest("observe-k2"),
    ]


def test_operator_observe_ledger_full_rejects_before_claiming_or_counting_attempt():
    clock = MutableClock()
    operation_id = "operation-observe-ledger-full"
    create_vm_start_operation(clock, operation_id=operation_id)
    operations = SqlAlchemyOperationStore(clock=clock)
    recovery = SqlAlchemyRecoveryStore(clock=clock)
    operation = operations.get(operation_id)
    ledger = [
        {
            "idempotency_key_digest": _observe_digest(f"used-key-{index}"),
            "expected_version": operation.version,
            "expected_checksum": operation.last_event_checksum,
        }
        for index in range(64)
    ]
    lease = recovery.prepare_and_claim(
        RecoverySpec(
            operation_id=operation_id,
            recovery_kind="vm_start_observation",
            details={
                "node_id": "node-a",
                "vmid": 306,
                "upid": "UPID:node-a:1:start",
                "operator_observe_requests": ledger,
            },
        ),
        lease_owner="seed",
        lease_seconds=60,
        expected_operation_version=operation.version,
        expected_operation_checksum=operation.last_event_checksum,
    )
    recovery.commit_observation(
        lease,
        event_type="recovery_seeded",
        stage="reconciliation",
        expected_statuses=[operation.status],
        recovery_status="retry_wait",
    )
    before = recovery.get(operation_id)
    current = operations.get(operation_id)
    coordinator = OperationRecoveryCoordinator(
        recovery=recovery,
        operations=operations,
        runner=OperationRecoveryRunner(recovery=recovery, handlers={}, worker_id="unused"),
        lock_reader=lambda *_args: None,
        worker_id="operator-observe-ledger-full",
        clock=clock,
    )

    with pytest.raises(OperationRecoveryObserveError) as raised:
        coordinator.observe(
            operation_id,
            actor=OperationActor(user_id="user-1", username="operator", role="operator"),
            expected_version=current.version,
            expected_checksum=current.last_event_checksum,
            idempotency_key="new-key-after-ledger-full",
        )

    after = recovery.get(operation_id)
    assert raised.value.code == "OPERATION_RECOVERY_IDEMPOTENCY_LEDGER_FULL"
    assert raised.value.status_code == 409
    assert after.status == before.status == "retry_wait"
    assert after.lease_generation == before.lease_generation
    assert after.attempt_count == before.attempt_count
    assert after.lease_owner == before.lease_owner is None
    assert after.lease_expires_at == before.lease_expires_at is None


@pytest.mark.parametrize(
    ("error_code", "outcome", "expected_status", "expected_public_code"),
    [
        (
            "PROXMOX_CREATE_RECOVERY_PROJECTION_FAILED",
            "retry_projection",
            503,
            "OPERATION_RECOVERY_OBSERVATION_UNAVAILABLE",
        ),
        (
            "GUIDED_QM_RECOVERY_BINDING_MISMATCH",
            "paused_binding_mismatch",
            409,
            "OPERATION_RECOVERY_INELIGIBLE",
        ),
    ],
)
def test_operator_observe_maps_action_specific_recovery_failures_to_stable_http_semantics(
    error_code,
    outcome,
    expected_status,
    expected_public_code,
):
    clock = MutableClock()
    operation_id = f"operation-observe-outcome-{expected_status}"
    create_vm_start_operation(clock, operation_id=operation_id)
    operations = SqlAlchemyOperationStore(clock=clock)
    recovery = SqlAlchemyRecoveryStore(clock=clock)
    operation = operations.get(operation_id)
    lease = recovery.prepare_and_claim(
        RecoverySpec(
            operation_id=operation_id,
            recovery_kind="vm_start_observation",
            details={"node_id": "node-a", "vmid": 306, "upid": "UPID:node-a:1:start"},
        ),
        lease_owner="foreground",
        lease_seconds=60,
        expected_operation_version=operation.version,
        expected_operation_checksum=operation.last_event_checksum,
    )
    operation, _ = recovery.commit_observation(
        lease,
        event_type="recovery_paused_for_operator",
        stage="reconciliation",
        recovery_status="paused",
        expected_statuses=[operation.status],
        expected_operation_version=operation.version,
        expected_operation_checksum=operation.last_event_checksum,
    )

    class ActionSpecificFailureHandler:
        def handle(self, claimed):
            recovery_status = "paused" if expected_status == 409 else "retry_wait"
            recovery.commit_observation(
                claimed,
                event_type="action_specific_recovery_failed",
                stage="reconciliation",
                recovery_status=recovery_status,
                error_code=error_code,
            )
            return RecoveryRunResult(operation_id=operation_id, outcome=outcome)

    runner = OperationRecoveryRunner(
        recovery=recovery,
        handlers={"vm_start_observation": ActionSpecificFailureHandler()},
        worker_id="automatic-runner",
    )
    coordinator = OperationRecoveryCoordinator(
        recovery=recovery,
        operations=operations,
        runner=runner,
        lock_reader=get_target_operation_lock,
        worker_id="operator-request",
        clock=clock,
    )

    with pytest.raises(OperationRecoveryObserveError) as raised:
        coordinator.observe(
            operation_id,
            actor=OperationActor(user_id="user-1", username="operator", role="operator"),
            expected_version=operation.version,
            expected_checksum=operation.last_event_checksum,
            idempotency_key=f"observe-{expected_status}",
        )

    assert raised.value.status_code == expected_status
    assert raised.value.code == expected_public_code
    assert raised.value.details["recovery_error_code"] == error_code

    with pytest.raises(OperationRecoveryObserveError) as replayed:
        coordinator.observe(
            operation_id,
            actor=OperationActor(user_id="user-1", username="operator", role="operator"),
            expected_version=operation.version,
            expected_checksum=operation.last_event_checksum,
            idempotency_key=f"observe-{expected_status}",
        )

    assert replayed.value.status_code == expected_status
    assert replayed.value.code == expected_public_code
    assert replayed.value.details["idempotent_replay"] is True


def test_operator_observe_closes_exact_no_item_pre_dispatch_without_proxmox_read():
    clock = MutableClock()
    operation_id = "operation-operator-observe-pre-dispatch"
    create_vm_start_operation(clock, operation_id=operation_id, include_upid=False)
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    locks.acquire(
        operation_type="vm_start",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="vm_start_dispatch",
    )
    recovery = SqlAlchemyRecoveryStore(clock=clock)
    client = ObservationClient(failure=AssertionError("pre-dispatch recovery must not observe Proxmox"))
    handler = VmStartRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: client,

        target_lock_reader=get_target_operation_lock,
    )
    runner = OperationRecoveryRunner(
        recovery=recovery,
        handlers={"vm_start_observation": handler},
        worker_id="automatic-runner",
    )
    coordinator = OperationRecoveryCoordinator(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        runner=runner,
        lock_reader=get_target_operation_lock,
        worker_id="operator-request",
    )
    operation = SqlAlchemyOperationStore(clock=clock).get(operation_id)

    result = coordinator.observe(
        operation_id,
        actor=OperationActor(user_id="user-1", username="operator", role="operator"),
        expected_version=operation.version,
        expected_checksum=operation.last_event_checksum,
        idempotency_key="observe-pre-dispatch-v1",
    )

    assert result["outcome"] == "failed_pre_dispatch"
    assert SqlAlchemyOperationStore(clock=clock).get(operation_id).status == "failed"
    assert recovery.get(operation_id).status == "completed"
    assert locks.current(cluster_id="gjallar-mvp", vmid=306) is None
    assert client.calls == []


def test_operator_observe_repairs_missing_start_job_before_exact_no_item_release():
    from app.jobs.runs import get_job_run

    clock = MutableClock()
    operation_id = "operation-operator-observe-missing-start-job"
    create_vm_start_operation(
        clock,
        operation_id=operation_id,
        include_upid=False,
        initial_status="planned",
    )
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    locks.acquire(
        operation_type="vm_start",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="vm_start_dispatch",
    )
    recovery = SqlAlchemyRecoveryStore(clock=clock)
    client = ObservationClient(failure=AssertionError("pre-dispatch recovery must not observe Proxmox"))
    operations = SqlAlchemyOperationStore(clock=clock)
    handler = VmStartRecoveryHandler(
        recovery=recovery,
        operations=operations,
        observation_factory=lambda: client,
        compatibility_projection=SqlAlchemyVmStartRecoveryJobProjection(),

        target_lock_reader=get_target_operation_lock,
    )
    coordinator = OperationRecoveryCoordinator(
        recovery=recovery,
        operations=operations,
        runner=OperationRecoveryRunner(
            recovery=recovery,
            handlers={"vm_start_observation": handler},
            worker_id="automatic-runner",
        ),
        lock_reader=get_target_operation_lock,
        worker_id="operator-request",
        clock=clock,
    )
    operation = operations.get(operation_id)

    result = coordinator.observe(
        operation_id,
        actor=OperationActor(user_id="user-1", username="operator", role="operator"),
        expected_version=operation.version,
        expected_checksum=operation.last_event_checksum,
        idempotency_key="observe-missing-start-job-v1",
    )

    job = get_job_run(operation_id)
    assert result["outcome"] == "failed_pre_dispatch"
    assert job["status"] == "failed"
    assert job["details"]["vm_start_result"]["proxmox_mutation_enabled"] is False
    assert job["details"]["vm_start_result"]["side_effects"] == []
    assert locks.current(cluster_id="gjallar-mvp", vmid=306) is None
    assert client.calls == []


@pytest.mark.parametrize(
    ("operation_type", "terminal_status", "terminal_reason", "handler_type"),
    [
        ("vm_start", "failed", "mutation_client_unavailable", VmStartRecoveryHandler),
        ("vm_shutdown", "blocked", "precheck_blocked", VmShutdownRecoveryHandler),
    ],
)
def test_operator_observe_closes_exact_marked_terminal_no_item_without_proxmox_read(
    operation_type,
    terminal_status,
    terminal_reason,
    handler_type,
):
    clock = MutableClock()
    operation_id = f"operation-terminal-no-item-{operation_type}"
    create_vm_start_operation(
        clock,
        operation_id=operation_id,
        include_upid=False,
        operation_type=operation_type,
        initial_status="planned",
    )
    operations = SqlAlchemyOperationStore(clock=clock)
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    durable_lock = locks.acquire(
        operation_type=operation_type,
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason=f"{operation_type}_dispatch",
    )
    operation = operations.transition(
        operation_id,
        next_status=terminal_status,
        event_type=terminal_reason,
        stage="precheck" if terminal_status == "blocked" else "reconciliation",
        payload={
            "pre_dispatch_terminal_no_effect": True,
            "mutation_dispatched": False,
            "pre_dispatch_terminal_reason": terminal_reason,
            "target_lock_id": durable_lock.lock_id,
            "cluster_id": durable_lock.cluster_id,
        },
        details_patch={
            "pre_dispatch_terminal_no_effect": True,
            "mutation_dispatched": False,
            "pre_dispatch_terminal_reason": terminal_reason,
            "target_lock_id": durable_lock.lock_id,
            "cluster_id": durable_lock.cluster_id,
        },
        expected_statuses=["planned"],
    )
    recovery = SqlAlchemyRecoveryStore(clock=clock)
    client = ObservationClient(failure=AssertionError("terminal no-effect recovery must not observe Proxmox"))
    projection = RecordingProjection()
    handler = handler_type(
        recovery=recovery,
        operations=operations,
        observation_factory=lambda: client,
        compatibility_projection=projection,

        target_lock_reader=get_target_operation_lock,
    )
    runner = OperationRecoveryRunner(
        recovery=recovery,
        handlers={f"{operation_type}_observation": handler},
        worker_id="automatic-runner",
    )
    coordinator = OperationRecoveryCoordinator(
        recovery=recovery,
        operations=operations,
        runner=runner,
        lock_reader=get_target_operation_lock,
        worker_id="operator-request",
        clock=clock,
    )

    from app.operations.facade import get_operation

    detail = get_operation(operation_id)
    assert [action["action"] for action in detail["recovery_available_actions"]] == ["observe"]
    assert detail["coordination_incomplete"] is True

    result = coordinator.observe(
        operation_id,
        actor=OperationActor(user_id="user-1", username="operator", role="operator"),
        expected_version=operation.version,
        expected_checksum=operation.last_event_checksum,
        idempotency_key=f"observe-terminal-no-item-{operation_type}",
    )

    assert result["outcome"] == terminal_status
    assert operations.get(operation_id).status == terminal_status
    assert recovery.get(operation_id).status == "completed"
    assert locks.current(cluster_id="gjallar-mvp", vmid=306) is None
    assert projection.calls == [
        {
            "operation_id": operation_id,
            "operation_status": terminal_status,
            "target": {"node_id": "node-a", "vmid": 306},
            "task": {},
            "observed_after": {},
            "mutation_dispatched": False,
        }
    ]
    assert client.calls == []


@pytest.mark.parametrize(
    ("marker_patch", "expected_code"),
    [
        ({"pre_dispatch_terminal_reason": "arbitrary_reason"}, "OPERATION_RECOVERY_NOT_PREPARED"),
        ({"proxmox_upid": "UPID:node-a:stale"}, "OPERATION_RECOVERY_NOT_PREPARED"),
        ({"target_lock_id": "operation-lock-mismatch"}, "OPERATION_RECOVERY_TARGET_LOCK_MISMATCH"),
    ],
)
def test_operator_observe_rejects_terminal_no_item_without_exact_allowlisted_proof(
    marker_patch,
    expected_code,
):
    clock = MutableClock()
    operation_id = f"operation-terminal-no-item-invalid-{expected_code}-{len(str(marker_patch))}"
    create_vm_start_operation(
        clock,
        operation_id=operation_id,
        include_upid=False,
        initial_status="planned",
    )
    operations = SqlAlchemyOperationStore(clock=clock)
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    durable_lock = locks.acquire(
        operation_type="vm_start",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="vm_start_dispatch",
    )
    details_patch = {
        "pre_dispatch_terminal_no_effect": True,
        "mutation_dispatched": False,
        "pre_dispatch_terminal_reason": "mutation_client_unavailable",
        "target_lock_id": durable_lock.lock_id,
        "cluster_id": durable_lock.cluster_id,
        **marker_patch,
    }
    operation = operations.transition(
        operation_id,
        next_status="failed",
        event_type=str(details_patch["pre_dispatch_terminal_reason"]),
        stage="reconciliation",
        payload=details_patch,
        details_patch=details_patch,
        expected_statuses=["planned"],
    )
    recovery = SqlAlchemyRecoveryStore(clock=clock)
    client = ObservationClient(failure=AssertionError("ineligible recovery must not observe Proxmox"))
    runner = OperationRecoveryRunner(
        recovery=recovery,
        handlers={
            "vm_start_observation": VmStartRecoveryHandler(
                recovery=recovery,
                operations=operations,
                observation_factory=lambda: client,

                target_lock_reader=get_target_operation_lock,
            )
        },
        worker_id="automatic-runner",
    )
    coordinator = OperationRecoveryCoordinator(
        recovery=recovery,
        operations=operations,
        runner=runner,
        lock_reader=get_target_operation_lock,
        worker_id="operator-request",
        clock=clock,
    )

    from app.operations.facade import get_operation

    assert get_operation(operation_id)["recovery_available_actions"] == []

    with pytest.raises(OperationRecoveryObserveError) as raised:
        coordinator.observe(
            operation_id,
            actor=OperationActor(user_id="user-1", username="operator", role="operator"),
            expected_version=operation.version,
            expected_checksum=operation.last_event_checksum,
            idempotency_key=f"observe-invalid-terminal-{len(str(marker_patch))}",
        )

    assert raised.value.code == expected_code
    assert recovery.get(operation_id) is None
    assert locks.current(cluster_id="gjallar-mvp", vmid=306) is not None
    assert client.calls == []


def test_operator_observe_does_not_close_historical_no_item_dispatching_operation():
    clock = MutableClock()
    operation_id = "operation-operator-observe-historical-no-item"
    create_vm_start_operation(
        clock,
        operation_id=operation_id,
        include_upid=False,
        include_recovery_contract=False,
    )
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    locks.acquire(
        operation_type="vm_start",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="historical_vm_start_dispatch",
    )
    recovery = SqlAlchemyRecoveryStore(clock=clock)
    client = ObservationClient(failure=AssertionError("historical ambiguity must not be observed or closed"))
    handler = VmStartRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: client,

        target_lock_reader=get_target_operation_lock,
    )
    runner = OperationRecoveryRunner(
        recovery=recovery,
        handlers={"vm_start_observation": handler},
        worker_id="automatic-runner",
    )
    coordinator = OperationRecoveryCoordinator(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        runner=runner,
        lock_reader=get_target_operation_lock,
        worker_id="operator-request",
    )
    operation = SqlAlchemyOperationStore(clock=clock).get(operation_id)

    with pytest.raises(OperationRecoveryObserveError) as raised:
        coordinator.observe(
            operation_id,
            actor=OperationActor(user_id="user-1", username="operator", role="operator"),
            expected_version=operation.version,
            expected_checksum=operation.last_event_checksum,
            idempotency_key="observe-historical-no-item-v1",
        )

    assert raised.value.code == "OPERATION_RECOVERY_NOT_PREPARED"
    assert recovery.get(operation_id) is None
    assert locks.current(cluster_id="gjallar-mvp", vmid=306) is not None
    assert client.calls == []


def test_operator_observe_closes_exact_create_no_item_pre_dispatch_without_proxmox_read():
    clock = MutableClock()
    operation_id = "operation-create-operator-observe-pre-dispatch"
    intent = {"operation": "vm_create", "target": {"node_id": "node-a", "vmid": 306}}
    operation = SqlAlchemyOperationStore(clock=clock).create(
        OperationSpec(
            operation_id=operation_id,
            operation_type="vm_create",
            execution_mode="managed_api",
            target_type="proxmox_vm",
            target_id="vmid:306",
            idempotency_key=operation_id,
            intent_digest=operation_digest(intent),
            plan_digest=operation_digest({"intent": intent, "version": 1}),
            actor=OperationActor(user_id="user-1", username="operator", role="operator"),
            initial_status="approved",
            initial_stage="approval",
            details={
                "target": {"node_id": "node-a", "vmid": 306, "name": "vm-306"},
                "recovery_contract": PRE_DISPATCH_RECOVERY_CONTRACT,
            },
        )
    ).operation
    locks = SqlAlchemyDurableTargetLockRepository(clock=clock)
    locks.acquire(
        operation_type="vm_create",
        cluster_id="gjallar-mvp",
        vmid=306,
        owner_id=operation_id,
        reason="vm_create_dispatch",
    )
    recovery = SqlAlchemyRecoveryStore(clock=clock)
    projection_calls: list[dict] = []

    class CreateProjection:
        def record_pre_dispatch_failed(self, **payload):
            projection_calls.append(payload)

        def record_pre_dispatch_failed_in_transaction(self, _transaction, **payload):
            self.record_pre_dispatch_failed(**payload)

        def record_verified_success(self, **_payload):
            raise AssertionError("pre-dispatch recovery cannot project success")

    client = ObservationClient(failure=AssertionError("pre-dispatch recovery must not observe Proxmox"))
    handler = VmCreateRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        observation_factory=lambda: client,
        compatibility_projection=CreateProjection(),

        target_lock_reader=get_target_operation_lock,
    )
    runner = OperationRecoveryRunner(
        recovery=recovery,
        handlers={"vm_create_observation": handler},
        worker_id="automatic-runner",
    )
    coordinator = OperationRecoveryCoordinator(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        runner=runner,
        lock_reader=get_target_operation_lock,
        worker_id="operator-request",
        clock=clock,
    )

    result = coordinator.observe(
        operation_id,
        actor=OperationActor(user_id="user-1", username="operator", role="operator"),
        expected_version=operation.version,
        expected_checksum=operation.last_event_checksum,
        idempotency_key="observe-create-pre-dispatch-v1",
    )

    assert result["outcome"] == "failed_pre_dispatch"
    assert SqlAlchemyOperationStore(clock=clock).get(operation_id).status == "blocked"
    assert recovery.get(operation_id).status == "completed"
    assert locks.current(cluster_id="gjallar-mvp", vmid=306) is None
    assert len(projection_calls) == 1
    assert client.calls == []


def test_operator_observe_rejects_stale_version_without_claiming_paused_item():
    clock = MutableClock()
    operation_id = "operation-operator-observe-stale"
    create_vm_start_operation(clock, operation_id=operation_id)
    recovery = SqlAlchemyRecoveryStore(clock=clock)
    lease = recovery.prepare_and_claim(
        RecoverySpec(
            operation_id=operation_id,
            recovery_kind="vm_start_observation",
            details={"node_id": "node-a", "vmid": 306, "upid": "UPID:node-a:1:start"},
        ),
        lease_owner="foreground",
        lease_seconds=60,
    )
    operation, _ = recovery.commit_observation(
        lease,
        event_type="paused_for_operator",
        stage="reconciliation",
        recovery_status="paused",
    )
    runner = OperationRecoveryRunner(
        recovery=recovery,
        handlers={},
        worker_id="automatic-runner",
    )
    coordinator = OperationRecoveryCoordinator(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(clock=clock),
        runner=runner,
        lock_reader=get_target_operation_lock,
        worker_id="operator-request",
    )

    with pytest.raises(OperationRecoveryObserveError) as raised:
        coordinator.observe(
            operation_id,
            actor=OperationActor(user_id="user-1", username="operator", role="operator"),
            expected_version=operation.version - 1,
            expected_checksum=operation.last_event_checksum,
            idempotency_key="observe-stale",
        )

    assert raised.value.code == "OPERATION_RECOVERY_STATE_CONFLICT"
    assert recovery.get(operation_id).status == "paused"


def test_recovery_runtime_is_disabled_by_default_and_bounds_timing(monkeypatch):
    monkeypatch.delenv("GJALLAR_OPERATION_RECOVERY_ENABLED", raising=False)
    monkeypatch.setenv("GJALLAR_OPERATION_RECOVERY_POLL_SECONDS", "0")
    monkeypatch.setenv("GJALLAR_OPERATION_RECOVERY_LEASE_SECONDS", "9999")

    config = RecoveryRuntimeConfig.from_env()

    assert config.enabled is False
    assert config.poll_seconds == 1
    assert config.lease_seconds == 900


def test_recovery_runtime_allowlists_all_supported_action_specific_handlers():
    runner = recovery_runtime.build_recovery_runner(
        config=RecoveryRuntimeConfig(
            enabled=False,
            poll_seconds=5,
            lease_seconds=60,
            max_attempts=5,
        )
    )

    assert runner.supports("vm_start_observation") is True
    assert runner.supports("vm_shutdown_observation") is True
    assert runner.supports("vm_create_observation") is True
    assert runner.supports("guided_qm_unlock_observation") is True


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


def test_vm_start_pre_dispatch_projection_can_create_missing_no_effect_job():
    from app.jobs.runs import get_job_run

    operation_id = "vm-start-missing-pre-dispatch-projection"

    SqlAlchemyVmStartRecoveryJobProjection().record_terminal(
        operation_id=operation_id,
        operation_status="failed",
        target={"node_id": "node-a", "vmid": 306},
        task={},
        observed_after={},
        mutation_dispatched=False,
    )

    job = get_job_run(operation_id)
    result = job["details"]["vm_start_result"]
    assert job["status"] == "failed"
    assert result["recovered_pre_dispatch"] is True
    assert result["proxmox_start_ran"] is False
    assert result["proxmox_mutation_enabled"] is False
    assert result["side_effects"] == []


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
