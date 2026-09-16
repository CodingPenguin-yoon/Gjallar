"""GET-only durable recovery contracts for Create VM."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.operations.core.domain import OperationActor, OperationSpec
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.recovery.domain import (
    PRE_DISPATCH_RECOVERY_CONTRACT,
    RecoveryLeaseLost,
    RecoverySpec,
)
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.target_lock import acquire_target_operation_lock, get_target_operation_lock
from app.operations.vm_create.recovery import (
    VM_CREATE_RECOVERY_KIND,
    VmCreateRecoveryHandler,
    VmCreateRecoverySession,
)
from app.operations.vm_create.recovery_adapters import (
    ProxmoxVmCreateRecoveryObservationAdapter,
    SqlAlchemyVmCreateRecoveryProjection,
)
from app.proxmox.client import ProxmoxMutationError
from app.vm_create.proxmox_runner import vm_config_fingerprint


def _prepared(*, operation_id: str, phase: str, status: str = "dispatching", details=None):
    operations = SqlAlchemyOperationStore()
    recovery = SqlAlchemyRecoveryStore()
    operation = operations.create(
        OperationSpec(
            operation_id=operation_id,
            operation_type="vm_create",
            execution_mode="managed_api",
            target_type="proxmox_vm",
            target_id="vmid:102",
            idempotency_key=operation_id,
            intent_digest="sha256:intent",
            plan_digest="sha256:plan",
            actor=OperationActor(username="operator", role="operator"),
            initial_status=status,
            initial_stage="create",
            details={"target": {"node_id": "node-a", "vmid": 102}},
        ),
        event_payload={"test": True},
    ).operation
    handle = acquire_target_operation_lock(
        target_type="proxmox_vm",
        target_id="vmid:102",
        owner_id=operation_id,
        operation_type="vm_create",
    )
    lock = handle.to_dict()
    durable = dict(lock["durable"])
    lease = recovery.prepare_and_claim(
        RecoverySpec(
            operation_id=operation_id,
            recovery_kind=VM_CREATE_RECOVERY_KIND,
            details={
                "operation_type": "vm_create",
                "execution_mode": "managed_api",
                "target_type": "proxmox_vm",
                "target_id": "vmid:102",
                "node_id": "node-a",
                "vmid": 102,
                "vm_name": "vm-102",
                "plan_digest": "sha256:plan",
                "target_lock_id": durable["operation_lock_id"],
                "cluster_id": durable["cluster_id"],
                "phase": phase,
                "mutation_replay_allowed": False,
                "recovery_contract": PRE_DISPATCH_RECOVERY_CONTRACT,
                **dict(details or {}),
            },
        ),
        lease_owner=f"test:{operation_id}",
        lease_seconds=60,
        expected_operation_version=operation.version,
        expected_operation_checksum=operation.last_event_checksum,
    )
    return operations, recovery, lease


class Projection:
    def __init__(self):
        self.calls = []

    def record_pre_dispatch_failed(self, **kwargs):
        self.calls.append(("pre_dispatch", kwargs))

    def record_pre_dispatch_failed_in_transaction(self, _transaction, **kwargs):
        return self.record_pre_dispatch_failed(**kwargs)

    def record_clear_rejection(self, **kwargs):
        self.calls.append(("clear_rejection", kwargs))

    def record_clear_rejection_in_transaction(self, _transaction, **kwargs):
        return self.record_clear_rejection(**kwargs)

    def record_verified_success(self, **kwargs):
        self.calls.append(("success", kwargs))
        return (
            {"request_id": kwargs["operation_id"], "status": "completed"},
            {"vm_instance_id": "node-a:102", "status": "stopped"},
            dict(kwargs["observed_after_artifact"])
            or {
                "artifact_id": "artifact-observed-after-recovered",
                "checksum": "sha256:recovered-observed-after",
            },
        )

    def record_verified_success_in_transaction(self, _transaction, **kwargs):
        return self.record_verified_success(**kwargs)

    def record_verified_absent_failure(self, **kwargs):
        self.calls.append(("absent_failure", kwargs))

    def record_verified_absent_failure_in_transaction(self, _transaction, **kwargs):
        return self.record_verified_absent_failure(**kwargs)


class GetOnlyObserver:
    def __init__(self, *, task=None, status=None, config=None):
        self.task = dict(task or {})
        self.status = dict(status or {"status": "stopped", "name": "vm-102"})
        self.config = dict(config or {"smbios1": "uuid=vm-102"})
        self.calls = []

    def get_task_status(self, *, node, upid):
        self.calls.append(("GET task", node, upid))
        return self.task

    def get_vm_status(self, *, node, vmid):
        self.calls.append(("GET status", node, vmid))
        return self.status

    def get_vm_config(self, *, node, vmid):
        self.calls.append(("GET config", node, vmid))
        return self.config


def _handler(operations, recovery, observer, projection=None, *, max_attempts=5):
    return VmCreateRecoveryHandler(
        recovery=recovery,
        operations=operations,
        observation_factory=lambda: observer,
        compatibility_projection=projection,

        target_lock_reader=get_target_operation_lock,
        max_attempts=max_attempts,
    )


def _record_production_create_inputs(operation_id: str, *, job_type: str = "vm_create") -> None:
    from app.db.models import VmCreateRequestRecord
    from app.db.session import session_scope
    from app.jobs.runs import record_job_run

    now = "2026-08-26T00:00:00+00:00"
    with session_scope() as session:
        session.add(
            VmCreateRequestRecord(
                request_id=operation_id,
                draft_id=f"draft-{operation_id}",
                manifest_id=f"manifest-{operation_id}",
                operator_id="operator",
                status="running",
                target_node_id="node-a",
                vmid=102,
                vm_name="vm-102",
                profile_id="dev-small",
                template_id="template-9000",
                storage_id="local-lvm",
                request_payload={
                    "hardware": {"cpu": 2, "memory_mb": 2048, "disk_gb": 32},
                    "network": {"bridge_id": "vmbr0"},
                    "access": {"ssh_public_key": "[REDACTED]"},
                    "risk_summary": {"level": "green"},
                },
                approval={"can_execute": True},
                result={"side_effects": ["proxmox_clone_invoked"]},
                created_at=now,
                updated_at=now,
            )
        )
    record_job_run(
        job_id=operation_id,
        job_type=job_type,
        status="running",
        target_id="node-a:vm-102",
        risk_level="green",
        stage="create" if job_type == "vm_create" else "start",
        step_status="running",
        message="running",
    )


def test_pre_dispatch_recovery_closes_projection_and_exact_lock_without_observation():
    operations, recovery, lease = _prepared(
        operation_id="vm-create-recovery-pre-dispatch",
        phase="dispatch_prepared",
    )
    projection = Projection()
    observer = GetOnlyObserver()

    result = _handler(operations, recovery, observer, projection).handle(lease)

    assert result.outcome == "failed_pre_dispatch"
    assert operations.get(lease.operation_id).status == "failed"
    assert recovery.get(lease.operation_id).status == "completed"
    assert get_target_operation_lock("proxmox_vm", "vmid:102") is None
    assert [call[0] for call in projection.calls] == ["pre_dispatch"]
    assert observer.calls == []


def test_foreground_success_projector_is_not_called_after_lease_takeover():
    from app.db.session import session_scope
    from app.operations.recovery.infrastructure.models import OperationRecoveryItemRecord

    operations, recovery, stale_lease = _prepared(
        operation_id="vm-create-foreground-stale-projection",
        phase="task_and_state_observed",
        status="verifying",
    )
    operation = operations.get(stale_lease.operation_id)
    foreground = VmCreateRecoverySession(
        recovery=recovery,
        operations=operations,
        lease=stale_lease,
        operation=operation,
        actor=OperationActor(username="operator", role="operator"),
        lease_seconds=60,
        phase="task_and_state_observed",
    )
    with session_scope() as transaction:
        row = transaction.get(OperationRecoveryItemRecord, stale_lease.operation_id)
        row.lease_expires_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
    replacement = recovery.claim_due(
        lease_owner="replacement-worker",
        lease_seconds=60,
    )
    assert len(replacement) == 1
    calls = []

    with pytest.raises(RecoveryLeaseLost):
        foreground.complete_success(
            result={
                "success": True,
                "status": "completed",
                "observed_after": {"status": "stopped"},
            },
            project_compatibility=lambda _transaction: calls.append("projected")
            or (
                {"request_id": stale_lease.operation_id},
                {"vm_instance_id": "node-a:102"},
                {"artifact_id": "artifact-observed", "checksum": "sha256:observed"},
            ),

        )

    assert calls == []
    assert operations.get(stale_lease.operation_id).status == "verifying"
    assert recovery.get(stale_lease.operation_id).lease_generation == replacement[0].generation
    assert get_target_operation_lock("proxmox_vm", "vmid:102")["owner_id"] == stale_lease.operation_id


def test_pre_dispatch_projection_failure_remains_retryable_and_retains_exact_lock():
    operations, recovery, lease = _prepared(
        operation_id="vm-create-recovery-pre-dispatch-projection-failure",
        phase="pre_dispatch_projection_pending",
    )

    class FailingProjection(Projection):
        def record_pre_dispatch_failed(self, **kwargs):
            raise RuntimeError("request projection unavailable")

    result = _handler(
        operations,
        recovery,
        GetOnlyObserver(),
        FailingProjection(),
    ).handle(lease)

    assert result.outcome == "retry_projection"
    assert operations.get(lease.operation_id).status == "dispatching"
    assert recovery.get(lease.operation_id).status == "retry_wait"
    assert get_target_operation_lock("proxmox_vm", "vmid:102")["owner_id"] == lease.operation_id


def test_recovery_rejects_any_item_that_allows_mutation_replay():
    operations, recovery, lease = _prepared(
        operation_id="vm-create-recovery-mutation-replay-contract-mismatch",
        phase="dispatch_prepared",
        details={"mutation_replay_allowed": True},
    )
    projection = Projection()
    observer = GetOnlyObserver()

    result = _handler(operations, recovery, observer, projection).handle(lease)

    assert result.outcome == "paused_manual_reconciliation"
    assert recovery.get(lease.operation_id).status == "paused"
    assert projection.calls == []
    assert observer.calls == []
    assert get_target_operation_lock("proxmox_vm", "vmid:102")["owner_id"] == lease.operation_id


def test_binding_failure_without_exact_lock_is_durably_paused_without_observation():
    from app.operations.locks.infrastructure.repository import SqlAlchemyDurableTargetLockRepository

    operations, recovery, lease = _prepared(
        operation_id="vm-create-recovery-missing-exact-lock",
        phase="config_pending",
    )
    locks = SqlAlchemyDurableTargetLockRepository()
    durable = locks.current(cluster_id="gjallar-mvp", vmid=102)
    assert durable is not None
    locks.release(durable, reason="test_missing_binding")
    observer = GetOnlyObserver()
    projection = Projection()

    result = _handler(operations, recovery, observer, projection).handle(lease)

    assert result.outcome == "paused_manual_reconciliation"
    assert operations.get(lease.operation_id).status == "needs_reconciliation"
    assert recovery.get(lease.operation_id).status == "paused"
    assert recovery.get(lease.operation_id).last_error_code == "PROXMOX_CREATE_RECOVERY_BINDING_MISMATCH"
    assert observer.calls == []
    assert projection.calls == []


def test_terminal_pre_dispatch_recovery_still_closes_partial_compatibility_projection():
    operations, recovery, lease = _prepared(
        operation_id="vm-create-recovery-terminal-pre-dispatch-projection",
        phase="pre_dispatch_projection_pending",
    )
    operations.transition(
        lease.operation_id,
        next_status="failed",
        event_type="operator_terminalized_pre_dispatch",
        stage="reconciliation",
        expected_statuses=["dispatching"],
    )
    projection = Projection()

    result = _handler(
        operations,
        recovery,
        GetOnlyObserver(),
        projection,
    ).handle(lease)

    assert result.outcome == "failed_pre_dispatch"
    assert operations.get(lease.operation_id).status == "failed"
    assert recovery.get(lease.operation_id).status == "completed"
    assert [call[0] for call in projection.calls] == ["pre_dispatch"]
    assert get_target_operation_lock("proxmox_vm", "vmid:102") is None


def test_pending_mutation_is_observed_then_paused_without_any_mutation_replay():
    operations, recovery, lease = _prepared(
        operation_id="vm-create-recovery-config-pending",
        phase="config_pending",
    )
    observer = GetOnlyObserver()

    result = _handler(operations, recovery, observer, Projection()).handle(lease)

    assert result.outcome == "paused_manual_reconciliation"
    assert operations.get(lease.operation_id).status == "needs_reconciliation"
    assert recovery.get(lease.operation_id).status == "paused"
    assert [call[0] for call in observer.calls] == ["GET status", "GET config"]
    assert get_target_operation_lock("proxmox_vm", "vmid:102")["owner_id"] == lease.operation_id


def test_clear_clone_rejection_replays_only_local_projection_and_releases_exact_lock():
    operations, recovery, lease = _prepared(
        operation_id="vm-create-recovery-clear-rejection",
        phase="clone_rejected",
        details={
            "status": "failed",
            "error_type": "ProxmoxMutationError",
            "details": {"status_code": 409},
        },
    )
    projection = Projection()
    observer = GetOnlyObserver()

    result = _handler(operations, recovery, observer, projection).handle(lease)

    assert result.outcome == "failed"
    assert operations.get(lease.operation_id).status == "failed"
    assert recovery.get(lease.operation_id).status == "completed"
    assert [call[0] for call in projection.calls] == ["clear_rejection"]
    assert observer.calls == []
    assert get_target_operation_lock("proxmox_vm", "vmid:102") is None


def test_running_clone_task_is_only_polled_and_scheduled_for_another_observation():
    operations, recovery, lease = _prepared(
        operation_id="vm-create-recovery-clone-running",
        phase="clone_dispatched",
        details={"clone_upid": "UPID:node-a:clone"},
    )
    observer = GetOnlyObserver(task={"status": "running"})

    result = _handler(operations, recovery, observer, Projection()).handle(lease)

    assert result.outcome == "retry_task_running"
    assert operations.get(lease.operation_id).status == "dispatching"
    assert recovery.get(lease.operation_id).status == "retry_wait"
    assert [call[0] for call in observer.calls] == ["GET task", "GET status", "GET config"]


def test_invalid_stored_create_upid_is_scrubbed_before_any_proxmox_get():
    opaque_locator = "opaque-secret?token=do-not-store"
    operations, recovery, lease = _prepared(
        operation_id="vm-create-recovery-invalid-upid",
        phase="clone_dispatched",
        details={"clone_upid": opaque_locator},
    )
    observer = GetOnlyObserver()

    result = _handler(operations, recovery, observer, Projection()).handle(lease)

    item = recovery.get(lease.operation_id)
    assert result.outcome == "paused_manual_reconciliation"
    assert observer.calls == []
    assert item.details["clone_upid"] == ""
    assert item.details["start_upid"] == ""
    assert item.details["last_observation"] == {
        "reason": "recovery_clone_task_reference_invalid"
    }
    assert opaque_locator not in json.dumps(item.details, sort_keys=True)


def test_cross_node_clone_recovery_uses_task_node_only_for_upid_and_target_node_for_vm():
    operations, recovery, lease = _prepared(
        operation_id="vm-create-recovery-cross-node-clone",
        phase="clone_dispatched",
        details={
            "template_node": "node-template",
            "clone_task_node_id": "node-template",
            "clone_upid": "UPID:node-template:clone",
        },
    )
    observer = GetOnlyObserver(task={"status": "running"})

    result = _handler(operations, recovery, observer, Projection()).handle(lease)

    assert result.outcome == "retry_task_running"
    assert observer.calls == [
        ("GET task", "node-template", "UPID:node-template:clone"),
        ("GET status", "node-a", 102),
        ("GET config", "node-a", 102),
    ]


def test_corrupted_create_recovery_node_binding_pauses_without_any_observation():
    operations, recovery, lease = _prepared(
        operation_id="vm-create-recovery-corrupt-node",
        phase="clone_dispatched",
        details={
            "node_id": "node-b",
            "template_node": "node-template",
            "clone_task_node_id": "node-template",
            "clone_upid": "UPID:node-template:clone",
        },
    )
    observer = GetOnlyObserver(task={"status": "running"})

    result = _handler(operations, recovery, observer, Projection()).handle(lease)

    assert result.outcome == "paused_manual_reconciliation"
    item = recovery.get(lease.operation_id)
    assert item.status == "paused"
    assert item.last_error_code == "PROXMOX_CREATE_RECOVERY_BINDING_MISMATCH"
    assert item.details["last_observation"]["reason"] == "recovery_node_mismatch"
    assert observer.calls == []


def test_create_recovery_bounds_unknown_external_task_and_vm_state_values():
    operations, recovery, lease = _prepared(
        operation_id="vm-create-recovery-bounded-external-values",
        phase="clone_dispatched",
        details={"clone_upid": "UPID:node-a:clone"},
    )
    task_marker = "opaque-create-task-exitstatus"
    status_marker = "opaque-create-vm-status"
    name_marker = "opaque-create-vm-name"
    observer = GetOnlyObserver(
        task={"status": "stopped", "exitstatus": task_marker},
        status={"status": status_marker, "name": name_marker},
    )

    result = _handler(operations, recovery, observer, Projection()).handle(lease)

    assert result.outcome == "paused_manual_reconciliation"
    item = recovery.get(lease.operation_id)
    observation = item.details["last_observation"]
    assert observation["task"]["exitstatus"] == "NON_OK"
    assert observation["observed"]["status"] == "unknown"
    assert observation["observed"]["name"] == "vm-102"
    serialized = repr(
        {
            "operation": operations.get(lease.operation_id),
            "events": operations.list_events(lease.operation_id),
            "recovery": item,
        }
    )
    assert task_marker not in serialized
    assert status_marker not in serialized
    assert name_marker not in serialized


def test_terminal_non_ok_task_and_authoritative_vm_absence_close_failed_without_replay():
    operations, recovery, lease = _prepared(
        operation_id="vm-create-recovery-terminal-failed-absent",
        phase="clone_dispatched",
        details={"clone_upid": "UPID:node-a:clone"},
    )
    projection = Projection()
    observer = GetOnlyObserver(
        task={"status": "stopped", "exitstatus": "ERROR"},
        status={"exists": False},
    )

    result = _handler(operations, recovery, observer, projection).handle(lease)

    assert result.outcome == "failed_target_absent"
    assert operations.get(lease.operation_id).status == "failed"
    assert recovery.get(lease.operation_id).status == "completed"
    assert [call[0] for call in projection.calls] == ["absent_failure"]
    assert projection.calls[0][1]["evidence"] == {
        "phase": "clone_dispatched",
        "task": {
            "kind": "clone",
            "upid": "UPID:node-a:clone",
            "status": "stopped",
            "exitstatus": "NON_OK",
        },
        "observed": {"exists": False},
        "mutation_replayed": False,
    }
    assert [call[0] for call in observer.calls] == ["GET task", "GET status"]
    assert get_target_operation_lock("proxmox_vm", "vmid:102") is None


@pytest.mark.parametrize(
    ("details", "task", "status", "expected_outcome", "expected_recovery_status"),
    [
        ({}, {}, {"exists": False}, "paused_manual_reconciliation", "paused"),
        (
            {"clone_upid": "UPID:node-a:clone"},
            {"status": "running"},
            {"exists": False},
            "retry_task_running",
            "retry_wait",
        ),
        (
            {"clone_upid": "UPID:node-a:clone"},
            {"status": "stopped", "exitstatus": "OK"},
            {"exists": False},
            "paused_manual_reconciliation",
            "paused",
        ),
        (
            {"start_upid": "UPID:node-a:start"},
            {"status": "stopped", "exitstatus": "ERROR"},
            {"status": "stopped", "name": "vm-102"},
            "paused_manual_reconciliation",
            "paused",
        ),
    ],
)
def test_absence_failure_requires_stored_terminal_non_ok_upid_and_absent_exact_target(
    details,
    task,
    status,
    expected_outcome,
    expected_recovery_status,
):
    operation_id = f"vm-create-recovery-negative-{expected_outcome}-{len(details)}-{task.get('status', 'none')}"
    operations, recovery, lease = _prepared(
        operation_id=operation_id,
        phase="clone_pending",
        details=details,
    )
    projection = Projection()
    observer = GetOnlyObserver(task=task, status=status)

    result = _handler(operations, recovery, observer, projection).handle(lease)

    assert result.outcome == expected_outcome
    assert recovery.get(lease.operation_id).status == expected_recovery_status
    assert [call[0] for call in projection.calls] == []
    assert get_target_operation_lock("proxmox_vm", "vmid:102")["owner_id"] == lease.operation_id


def test_terminal_absent_failure_projection_failure_is_retryable_and_retains_lock():
    operations, recovery, lease = _prepared(
        operation_id="vm-create-recovery-terminal-absent-projection-failure",
        phase="start_dispatched",
        details={"start_upid": "UPID:node-a:start"},
    )

    class FailingProjection(Projection):
        def record_verified_absent_failure(self, **kwargs):
            raise RuntimeError("compatibility persistence unavailable")

    result = _handler(
        operations,
        recovery,
        GetOnlyObserver(
            task={"status": "stopped", "exitstatus": "ERROR"},
            status={"exists": False},
        ),
        FailingProjection(),
    ).handle(lease)

    assert result.outcome == "retry_projection"
    assert operations.get(lease.operation_id).status == "dispatching"
    assert recovery.get(lease.operation_id).status == "retry_wait"
    assert get_target_operation_lock("proxmox_vm", "vmid:102")["owner_id"] == lease.operation_id





def test_unknown_vm_observation_retries_without_persisting_raw_error():
    operations, recovery, lease = _prepared(
        operation_id="vm-create-recovery-observation-unknown",
        phase="clone_dispatched",
        details={"clone_upid": "UPID:node-a:clone"},
    )

    class UnknownObserver(GetOnlyObserver):
        def get_vm_status(self, *, node, vmid):
            self.calls.append(("GET status", node, vmid))
            raise TimeoutError("token-secret-must-not-be-stored")

    result = _handler(
        operations,
        recovery,
        UnknownObserver(task={"status": "stopped", "exitstatus": "ERROR"}),
        Projection(),
    ).handle(lease)

    assert result.outcome == "retry_observation"
    item = recovery.get(lease.operation_id)
    assert item.status == "retry_wait"
    assert "token-secret-must-not-be-stored" not in json.dumps(item.details)
    assert get_target_operation_lock("proxmox_vm", "vmid:102")["owner_id"] == lease.operation_id


def test_create_observation_adapter_normalizes_only_exact_status_404_to_bounded_absence():
    class Client:
        def get_vm_status(self, **kwargs):
            raise ProxmoxMutationError(
                "raw response contains token-secret",
                details={
                    "status_code": 404,
                    "response_text": "token-secret",
                    "path": "/nodes/node-a/qemu/102/status/current",
                },
            )

    observed = ProxmoxVmCreateRecoveryObservationAdapter(Client()).get_vm_status(
        node="node-a",
        vmid=102,
    )

    assert observed == {"exists": False}
    assert "secret" not in json.dumps(observed)


@pytest.mark.parametrize("status_code", [None, 401, 500, "404"])
def test_create_observation_adapter_does_not_normalize_non_exact_404(status_code):
    class Client:
        def get_vm_status(self, **kwargs):
            raise ProxmoxMutationError(
                "observation unavailable",
                details={"status_code": status_code},
            )

    with pytest.raises(ProxmoxMutationError):
        ProxmoxVmCreateRecoveryObservationAdapter(Client()).get_vm_status(
            node="node-a",
            vmid=102,
        )


def test_artifact_checkpoint_can_complete_only_after_exact_get_verification_and_projection():
    config = {"smbios1": "uuid=vm-102", "net0": "virtio=AA:BB:CC:DD:EE:FF"}
    fingerprint = vm_config_fingerprint(config)
    artifact = {"artifact_id": "artifact-observed-after", "checksum": "sha256:artifact"}
    observed_after = {"status": "stopped", "fingerprint": fingerprint}
    operations, recovery, lease = _prepared(
        operation_id="vm-create-recovery-success",
        phase="observed_after_artifact_recorded",
        details={
            "result_success": True,
            "required_status": "stopped",
            "observed_after": observed_after,
            "observed_after_artifact": artifact,
        },
    )
    projection = Projection()
    observer = GetOnlyObserver(config=config)

    result = _handler(operations, recovery, observer, projection).handle(lease)

    assert result.outcome == "succeeded"
    assert operations.get(lease.operation_id).status == "succeeded"
    assert recovery.get(lease.operation_id).status == "completed"
    assert [call[0] for call in observer.calls] == ["GET status", "GET config"]
    assert [call[0] for call in projection.calls] == ["success"]
    assert get_target_operation_lock("proxmox_vm", "vmid:102") is None


def test_recorded_artifact_checkpoint_without_checksum_pauses_before_observation_or_projection():
    from app.operations.facade import get_operation
    from app.operations.recovery.application import (
        OperationRecoveryCoordinator,
        OperationRecoveryObserveError,
        OperationRecoveryRunner,
    )

    config = {"smbios1": "uuid=vm-102"}
    operations, recovery, lease = _prepared(
        operation_id="vm-create-recovery-artifact-checksum-missing",
        phase="observed_after_artifact_recorded",
        details={
            "result_success": True,
            "required_status": "stopped",
            "observed_after": {
                "status": "stopped",
                "fingerprint": vm_config_fingerprint(config),
            },
            "observed_after_artifact": {"artifact_id": "artifact-observed-after"},
        },
    )
    projection = Projection()
    observer = GetOnlyObserver(config=config)

    handler = _handler(operations, recovery, observer, projection)
    result = handler.handle(lease)

    assert result.outcome == "paused_manual_reconciliation"
    assert recovery.get(lease.operation_id).last_error_code == (
        "PROXMOX_CREATE_RECOVERY_ARTIFACT_BINDING_INVALID"
    )
    assert observer.calls == []
    assert projection.calls == []
    assert get_target_operation_lock("proxmox_vm", "vmid:102")["owner_id"] == lease.operation_id
    operation = operations.get(lease.operation_id)
    assert get_operation(lease.operation_id)["recovery_available_actions"] == []
    coordinator = OperationRecoveryCoordinator(
        recovery=recovery,
        operations=operations,
        runner=OperationRecoveryRunner(
            recovery=recovery,
            handlers={VM_CREATE_RECOVERY_KIND: handler},
            worker_id="automatic-runner",
        ),
        lock_reader=get_target_operation_lock,
        worker_id="operator-observer",
    )
    with pytest.raises(OperationRecoveryObserveError) as raised:
        coordinator.observe(
            lease.operation_id,
            actor=OperationActor(username="operator", role="operator"),
            expected_version=operation.version,
            expected_checksum=operation.last_event_checksum,
            idempotency_key="observe-invalid-create-artifact-binding",
        )
    assert raised.value.status_code == 409
    assert raised.value.code == "OPERATION_RECOVERY_INELIGIBLE"
    assert observer.calls == []


@pytest.mark.parametrize(
    "error_code",
    [
        "PROXMOX_CREATE_RECOVERY_ARTIFACT_BINDING_INVALID",
        "PROXMOX_CREATE_RECOVERY_MANUAL_DECISION_REQUIRED",
    ],
)
def test_create_manual_pause_codes_are_ineligible(error_code):
    from app.operations.recovery.application import recovery_error_semantics

    assert recovery_error_semantics(error_code) == "ineligible"


def test_readiness_checkpoint_rebuilds_artifact_projection_without_replaying_mutation():
    config = {"smbios1": "uuid=vm-102", "net0": "virtio=AA:BB:CC:DD:EE:FF"}
    observed_after = {"status": "stopped", "fingerprint": vm_config_fingerprint(config)}
    operations, recovery, lease = _prepared(
        operation_id="vm-create-recovery-readiness-artifact",
        phase="readiness_observed",
        details={
            "result_success": True,
            "required_status": "stopped",
            "observed_after": observed_after,
        },
    )
    projection = Projection()
    observer = GetOnlyObserver(config=config)

    result = _handler(operations, recovery, observer, projection).handle(lease)

    assert result.outcome == "succeeded"
    assert operations.get(lease.operation_id).status == "succeeded"
    assert recovery.get(lease.operation_id).status == "completed"
    assert [call[0] for call in observer.calls] == ["GET status", "GET config"]
    assert projection.calls[0][1]["observed_after_artifact"] == {}
    assert get_target_operation_lock("proxmox_vm", "vmid:102") is None


def test_post_result_projection_crash_rolls_forward_from_full_durable_observation():
    config = {"smbios1": "uuid=vm-102", "net0": "virtio=AA:BB:CC:DD:EE:FF"}
    observed_after = {"status": "stopped", "fingerprint": vm_config_fingerprint(config)}
    artifact = {"artifact_id": "artifact-observed-after", "checksum": "sha256:artifact"}
    operations, recovery, lease = _prepared(
        operation_id="vm-create-recovery-post-result-projection",
        phase="task_and_state_observed",
        status="verifying",
        details={
            "result_success": True,
            "required_status": "stopped",
            "observed_after": observed_after,
            "observed_after_artifact": artifact,
        },
    )
    projection = Projection()
    observer = GetOnlyObserver(config=config)

    result = _handler(operations, recovery, observer, projection).handle(lease)

    assert result.outcome == "succeeded"
    assert operations.get(lease.operation_id).status == "succeeded"
    assert recovery.get(lease.operation_id).status == "completed"
    assert [call[0] for call in projection.calls] == ["success"]
    assert [call[0] for call in observer.calls] == ["GET status", "GET config"]
    assert get_target_operation_lock("proxmox_vm", "vmid:102") is None


def test_production_projection_idempotently_rebuilds_artifact_request_workload_and_job():
    from app.db.models import VmCreateRequestRecord
    from app.db.session import session_scope
    from app.jobs.runs import get_job_run_strict, record_job_run

    operation_id = "vm-create-recovery-production-projection"
    now = "2026-08-26T00:00:00+00:00"
    with session_scope() as session:
        session.add(
            VmCreateRequestRecord(
                request_id=operation_id,
                draft_id="draft-recovery",
                manifest_id="manifest-recovery",
                operator_id="operator",
                status="running",
                target_node_id="node-a",
                vmid=102,
                vm_name="vm-102",
                profile_id="dev-small",
                template_id="template-9000",
                storage_id="local-lvm",
                request_payload={
                    "hardware": {"cpu": 2, "memory_mb": 2048, "disk_gb": 32},
                    "network": {"bridge_id": "vmbr0"},
                    "access": {"ssh_public_key": "[REDACTED]"},
                    "risk_summary": {"level": "green"},
                },
                approval={"can_execute": True},
                result={"side_effects": ["proxmox_clone_invoked"]},
                created_at=now,
                updated_at=now,
            )
        )
    record_job_run(
        job_id=operation_id,
        job_type="vm_create",
        status="running",
        target_id="node-a:vm-102",
        risk_level="green",
        stage="create",
        step_status="running",
        message="running",
    )
    projection = SqlAlchemyVmCreateRecoveryProjection()
    observed = {
        "status": "stopped",
        "fingerprint": vm_config_fingerprint({"smbios1": "uuid=vm-102"}),
    }

    first = projection.record_verified_success(
        operation_id=operation_id,
        target={"node_id": "node-a", "vmid": 102},
        observed_after=observed,
        observed_after_artifact={},
    )
    second = projection.record_verified_success(
        operation_id=operation_id,
        target={"node_id": "node-a", "vmid": 102},
        observed_after=observed,
        observed_after_artifact=first[2],
    )

    assert first[0]["status"] == second[0]["status"] == "completed"
    assert first[1]["vm_instance_id"] == second[1]["vm_instance_id"] == "node-a:102"
    assert first[2]["artifact_id"] == second[2]["artifact_id"]
    assert get_job_run_strict(operation_id)["status"] == "completed"


def test_production_success_projection_does_not_reassign_foreign_owned_workload():
    from app.db.models import VmCreateRequestRecord, VmInstanceRecord
    from app.db.session import session_scope
    from app.jobs.artifacts import list_artifact_records
    from app.jobs.runs import get_job_run_strict

    operation_id = "vm-create-recovery-foreign-workload-owner"
    _record_production_create_inputs(operation_id)
    now = "2026-08-26T00:00:00+00:00"
    with session_scope() as session:
        session.add(
            VmInstanceRecord(
                vm_instance_id="node-a:102",
                node_id="node-a",
                vmid=102,
                name="foreign-owner-vm",
                status="running",
                profile_id="foreign-profile",
                template_id="foreign-template",
                storage_id="foreign-storage",
                cpu=8,
                memory_mb=8192,
                disk_gb=128,
                network={"bridge_id": "foreign"},
                access={},
                observed_after={"status": "running"},
                create_job_id="different-create-operation",
                created_at=now,
                updated_at=now,
            )
        )

    SqlAlchemyVmCreateRecoveryProjection().record_verified_success(
        operation_id=operation_id, target={"node_id": "node-a", "vmid": 102},
        observed_after={"status": "stopped"}, observed_after_artifact={},
    )
    with session_scope() as session:
        request = session.get(VmCreateRequestRecord, operation_id)
        workload = session.get(VmInstanceRecord, "node-a:102")
        assert request.status == "completed"
        assert workload.name == "foreign-owner-vm"
        assert workload.status == "running"
        assert workload.create_job_id == "different-create-operation"
    assert get_job_run_strict(operation_id)["status"] == "completed"


def test_recorded_artifact_mismatch_does_not_change_any_projection():
    from app.db.models import VmCreateRequestRecord, VmInstanceRecord
    from app.db.session import session_scope
    from app.jobs.artifacts import get_artifact_record, read_artifact_text, write_json_artifact
    from app.jobs.runs import get_job_run_strict

    operation_id = "vm-create-recovery-recorded-artifact-mismatch"
    _record_production_create_inputs(operation_id)
    observed = {"status": "stopped", "fingerprint": {"hash": "sha256:" + "a" * 64}}
    existing = write_json_artifact(
        run_dir="unused",
        job_id=operation_id,
        artifact_type="observed_after",
        filename="observed_after.json",
        payload=observed,
    )
    original_text = read_artifact_text(existing)

    with pytest.raises(ValueError, match="artifact binding does not match"):
        SqlAlchemyVmCreateRecoveryProjection().record_verified_success(
            operation_id=operation_id,
            target={"node_id": "node-a", "vmid": 102},
            observed_after=observed,
            observed_after_artifact={
                "artifact_id": existing.artifact_id,
                "checksum": "sha256:" + "0" * 64,
            },
        )

    retained = get_artifact_record(existing.artifact_id)
    assert retained is not None and retained.checksum == existing.checksum
    assert read_artifact_text(retained) == original_text
    with session_scope() as session:
        assert session.get(VmCreateRequestRecord, operation_id).status == "running"
        assert session.get(VmInstanceRecord, "node-a:102") is None
    assert get_job_run_strict(operation_id)["status"] == "running"


def test_recorded_artifact_content_hash_mismatch_does_not_change_any_projection():
    from app.db.models import JobArtifactRecord, VmCreateRequestRecord, VmInstanceRecord
    from app.db.session import session_scope
    from app.jobs.artifacts import write_json_artifact
    from app.jobs.runs import get_job_run_strict

    operation_id = "vm-create-recovery-artifact-content-hash-mismatch"
    _record_production_create_inputs(operation_id)
    observed = {"status": "stopped", "fingerprint": {"hash": "sha256:" + "b" * 64}}
    existing = write_json_artifact(
        run_dir="unused",
        job_id=operation_id,
        artifact_type="observed_after",
        filename="observed_after.json",
        payload=observed,
    )
    with session_scope() as session:
        row = session.get(JobArtifactRecord, existing.artifact_id)
        row.content_text = json.dumps({**observed, "status": "running"}, sort_keys=True) + "\n"

    with pytest.raises(ValueError, match="content checksum"):
        SqlAlchemyVmCreateRecoveryProjection().record_verified_success(
            operation_id=operation_id,
            target={"node_id": "node-a", "vmid": 102},
            observed_after=observed,
            observed_after_artifact=existing.to_dict(),
        )

    with session_scope() as session:
        assert session.get(VmCreateRequestRecord, operation_id).status == "running"
        assert session.get(VmInstanceRecord, "node-a:102") is None
    assert get_job_run_strict(operation_id)["status"] == "running"


def test_recorded_artifact_superset_content_does_not_change_any_projection():
    from app.db.models import VmCreateRequestRecord, VmInstanceRecord
    from app.db.session import session_scope
    from app.jobs.artifacts import write_json_artifact
    from app.jobs.runs import get_job_run_strict

    operation_id = "vm-create-recovery-artifact-superset-mismatch"
    _record_production_create_inputs(operation_id)
    observed = {"status": "stopped", "fingerprint": {"hash": "sha256:" + "c" * 64}}
    existing = write_json_artifact(
        run_dir="unused",
        job_id=operation_id,
        artifact_type="observed_after",
        filename="observed_after.json",
        payload={**observed, "unexpected": "different-evidence"},
    )

    with pytest.raises(ValueError, match="artifact content does not match"):
        SqlAlchemyVmCreateRecoveryProjection().record_verified_success(
            operation_id=operation_id,
            target={"node_id": "node-a", "vmid": 102},
            observed_after=observed,
            observed_after_artifact=existing.to_dict(),
        )

    with session_scope() as session:
        assert session.get(VmCreateRequestRecord, operation_id).status == "running"
        assert session.get(VmInstanceRecord, "node-a:102") is None
    assert get_job_run_strict(operation_id)["status"] == "running"


def test_success_projection_does_not_reassign_a_different_job_type():
    from app.db.models import VmCreateRequestRecord, VmInstanceRecord
    from app.db.session import session_scope
    from app.jobs.artifacts import list_artifact_records
    from app.jobs.runs import get_job_run_strict

    operation_id = "vm-create-recovery-foreign-job-type"
    _record_production_create_inputs(operation_id, job_type="vm_start")

    with pytest.raises(ValueError, match="job type does not match"):
        SqlAlchemyVmCreateRecoveryProjection().record_verified_success(
            operation_id=operation_id,
            target={"node_id": "node-a", "vmid": 102},
            observed_after={"status": "stopped"},
            observed_after_artifact={},
        )

    with session_scope() as session:
        assert session.get(VmCreateRequestRecord, operation_id).status == "running"
        assert session.get(VmInstanceRecord, "node-a:102") is None
    assert get_job_run_strict(operation_id)["job_type"] == "vm_start"
    assert not any(
        item["type"] == "observed_after"
        for item in list_artifact_records(operation_id)
    )


def test_production_pre_dispatch_projection_is_idempotent_and_does_not_invent_orphan_job():
    from app.db.models import VmCreateRequestRecord
    from app.db.session import session_scope
    from app.db.vm_runtime import get_vm_create_request_record
    from app.jobs.runs import get_job_run_strict, record_job_run

    operation_id = "vm-create-recovery-production-pre-dispatch"
    now = "2026-08-26T00:00:00+00:00"
    with session_scope() as session:
        session.add(
            VmCreateRequestRecord(
                request_id=operation_id,
                draft_id="draft-recovery-pre-dispatch",
                manifest_id="manifest-recovery-pre-dispatch",
                operator_id="operator",
                status="running",
                target_node_id="node-a",
                vmid=102,
                vm_name="vm-102",
                profile_id="dev-small",
                template_id="template-9000",
                storage_id="local-lvm",
                request_payload={},
                approval={"can_execute": True},
                result={"external_effect": False},
                created_at=now,
                updated_at=now,
            )
        )
    record_job_run(
        job_id=operation_id,
        job_type="vm_create",
        status="running",
        target_id="node-a:vm-102",
        risk_level="green",
        stage="create",
        step_status="running",
        message="running",
    )
    projection = SqlAlchemyVmCreateRecoveryProjection()

    for _ in range(2):
        projection.record_pre_dispatch_failed(
            operation_id=operation_id,
            target={"node_id": "node-a", "vmid": 102},
            code="PROXMOX_CREATE_RECOVERED_PRE_DISPATCH",
        )

    assert get_vm_create_request_record(operation_id)["status"] == "failed"
    assert get_job_run_strict(operation_id)["status"] == "failed"

    orphan_operation_id = "vm-create-recovery-production-orphan-pre-dispatch"
    projection.record_pre_dispatch_failed(
        operation_id=orphan_operation_id,
        target={"node_id": "node-a", "vmid": 103},
        code="PROXMOX_CREATE_RECOVERED_PRE_DISPATCH",
    )

    assert get_vm_create_request_record(orphan_operation_id) is None
    assert get_job_run_strict(orphan_operation_id) is None


def test_production_absent_failure_projection_is_idempotent_and_redacts_evidence():
    from app.db.models import VmCreateRequestRecord
    from app.db.session import session_scope
    from app.db.vm_runtime import get_vm_create_request_record
    from app.jobs.runs import get_job_run_strict, record_job_run

    operation_id = "vm-create-recovery-production-absent-failure"
    now = "2026-08-26T00:00:00+00:00"
    with session_scope() as session:
        session.add(
            VmCreateRequestRecord(
                request_id=operation_id,
                draft_id="draft-recovery-absent",
                manifest_id="manifest-recovery-absent",
                operator_id="operator",
                status="running",
                target_node_id="node-a",
                vmid=102,
                vm_name="vm-102",
                profile_id="dev-small",
                template_id="template-9000",
                storage_id="local-lvm",
                request_payload={},
                approval={"can_execute": True},
                result={"side_effects": ["proxmox_clone_invoked"]},
                created_at=now,
                updated_at=now,
            )
        )
    record_job_run(
        job_id=operation_id,
        job_type="vm_create",
        status="running",
        target_id="node-a:vm-102",
        risk_level="green",
        stage="create",
        step_status="running",
        message="running",
    )
    projection = SqlAlchemyVmCreateRecoveryProjection()
    evidence = {
        "phase": "clone_dispatched",
        "task": {
            "kind": "clone",
            "upid": "UPID:node-a:clone",
            "status": "stopped",
            "exitstatus": "NON_OK",
        },
        "observed": {"exists": False},
        "mutation_replayed": False,
        "token_secret": "must-not-be-stored",
    }

    for _ in range(2):
        projection.record_verified_absent_failure(
            operation_id=operation_id,
            target={"node_id": "node-a", "vmid": 102},
            evidence=evidence,
        )

    request = get_vm_create_request_record(operation_id)
    job = get_job_run_strict(operation_id)
    assert request["status"] == "failed"
    assert request["result"]["target_absence_verified"] is True
    assert request["result"]["mutation_replayed"] is False
    assert request["result"]["side_effects"] == ["proxmox_clone_invoked"]
    assert job["status"] == "failed"
    assert "must-not-be-stored" not in json.dumps({"request": request, "job": job})
