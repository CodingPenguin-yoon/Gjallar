from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models import OperationLockRecord
from app.db.session import session_scope
from app.operations.core.domain import verify_event_chain
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.locks.domain import DurableTargetLockBusy
from app.operations.locks.infrastructure.repository import SqlAlchemyDurableTargetLockRepository
from app.operations.recovery.infrastructure.models import OperationRecoveryItemRecord
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.vm_compute.application import ComputeService
from app.operations.vm_compute.domain import ComputeError, ComputeRequest
from app.operations.vm_compute.infrastructure import ComputeAdmission, ComputeClient
from app.operations.vm_compute.recovery import ComputeRecoveryHandler
from app.proxmox.client import ProxmoxMutationError


class FakeClient:
    def __init__(self):
        self.config = {"name": "test-vm", "cores": 2, "memory": 2048, "sockets": 1, "digest": "a" * 40}
        self.status = "stopped"
        self.pending = []
        self.permissions = {"VM.Audit", "VM.Config.CPU", "VM.Config.Memory"}
        self.calls = []
        self.reads = 0
        self.drift = False
        self.lost_response = False
        self.partial = False
        self.post_fail = False
        self.after_write = None

    def get_vm_current_config(self, **kwargs):
        self.reads += 1
        if self.drift and self.reads == 2:
            self.status = "running"
        if self.post_fail and self.calls:
            raise ProxmoxMutationError("synthetic secret must not leak")
        return dict(self.config)

    def get_vm_status(self, **kwargs):
        return {"status": self.status}

    def get_vm_pending(self, **kwargs):
        return self.pending

    def get_vm_permissions(self, **kwargs):
        return self.permissions

    def set_vm_config(self, *, node, vmid, config):
        self.calls.append((node, vmid, config))
        assert config["digest"] == self.config["digest"]
        self.config.update(cores=config["cores"], digest="b" * 40)
        if not self.partial:
            self.config["memory"] = config["memory"]
        if self.after_write:
            self.after_write()
        if self.lost_response:
            raise ProxmoxMutationError("synthetic secret must not leak")


@pytest.fixture
def flow():
    fake = FakeClient()
    service = ComputeService(client=ComputeClient(fake), admission=ComputeAdmission(),
        operations=SqlAlchemyOperationStore(), recovery=SqlAlchemyRecoveryStore(), cluster_id="gjallar-mvp")
    request = ComputeRequest(idempotency_key="compute-test", expected_digest="a" * 40,
        expected_name="test-vm", cores=4, memory_mib=4096)
    return service, fake, request


def execute(flow):
    service, _, request = flow
    return service.execute(node_id="node1", vmid=40000, request=request, actor={"user_id": "operator", "role": "operator"})


def recover(service, operation_id):
    with session_scope() as session:
        row = session.get(OperationRecoveryItemRecord, operation_id)
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    lease = service.recovery.claim_operation(operation_id, lease_owner="test-recovery", lease_seconds=60)
    return ComputeRecoveryHandler(operations=service.operations, recovery=service.recovery,
                                  service_factory=lambda: service).handle(lease)


def test_verified_result_replay_and_event_chain(flow):
    service, fake, request = flow
    result = execute(flow)
    assert result["status"] == "succeeded"
    assert result["observed_before"]["cores"] == 2
    assert result["observed_after"]["cores"] == 4
    assert result["observed_after"]["memory_mib"] == 4096
    assert service.recovery.get(result["operation_id"]).status == "completed"
    assert SqlAlchemyDurableTargetLockRepository().current(cluster_id="gjallar-mvp", vmid=40000) is None
    # A later external state change cannot replace the historical verified result.
    fake.config["cores"] = 8
    replay = execute(flow)
    assert replay["idempotent_replay"] and replay["observed_after"]["cores"] == 4
    assert len(fake.calls) == 1
    assert verify_event_chain(service.operations.list_events(result["operation_id"]))
    with pytest.raises(ComputeError, match="같은 요청"):
        execute((service, fake, request.model_copy(update={"cores": 8})))


@pytest.mark.parametrize("patch,code", [
    ({"sockets": 2}, "VM_COMPUTE_TOPOLOGY_UNSUPPORTED"),
    ({"vcpus": 1}, "VM_COMPUTE_TOPOLOGY_UNSUPPORTED"),
    ({"template": 1}, "VM_COMPUTE_LOCKED_OR_TEMPLATE"),
    ({"lock": "backup"}, "VM_COMPUTE_LOCKED_OR_TEMPLATE"),
    ({"digest": "c" * 40}, "VM_COMPUTE_STATE_CHANGED"),
    ({"balloon": 8192}, "VM_COMPUTE_BALLOON_LIMIT"),
])
def test_precheck_denies_without_write(flow, patch, code):
    service, fake, _ = flow
    fake.config.update(patch)
    with pytest.raises(ComputeError) as failure:
        execute(flow)
    assert failure.value.code == code
    assert not fake.calls and not service.operations.list()


def test_permission_pending_and_power_drift(flow):
    service, fake, _ = flow
    fake.permissions.remove("VM.Config.CPU")
    with pytest.raises(ComputeError) as failure:
        execute(flow)
    assert failure.value.status_code == 403 and not fake.calls
    fake.permissions.add("VM.Config.CPU")
    fake.pending = [{"key": "memory", "pending": 1024}]
    with pytest.raises(ComputeError, match="대기 중"):
        execute(flow)
    fake.pending = []
    fake.reads = 0
    fake.drift = True
    with pytest.raises(ComputeError, match="정지된"):
        execute(flow)
    assert not fake.calls
    operation = service.operations.list()[0]
    assert operation.status == "blocked" and service.recovery.get(operation.operation_id).status == "completed"
    assert SqlAlchemyDurableTargetLockRepository().current(cluster_id="gjallar-mvp", vmid=40000) is None


def test_partial_result_retains_lock_until_verified_get_only_recovery(flow):
    service, fake, _ = flow
    fake.partial = True
    result = execute(flow)
    assert result["status"] == "needs_reconciliation"
    assert result["observed_after"]["cores"] == 4 and result["observed_after"]["memory_mib"] == 2048
    with pytest.raises(DurableTargetLockBusy):
        SqlAlchemyDurableTargetLockRepository().acquire(operation_type="vm_start", cluster_id="gjallar-mvp",
            vmid=40000, owner_id="other", reason="test")
    fake.config["memory"] = 4096
    assert recover(service, result["operation_id"]).outcome == "succeeded"
    assert len(fake.calls) == 1


def test_unknown_dispatch_never_retries_or_claims_success_from_matching_values(flow):
    service, fake, _ = flow
    fake.lost_response = True
    result = execute(flow)
    assert result["status"] == "needs_reconciliation"
    assert execute(flow)["idempotent_replay"]
    assert recover(service, result["operation_id"]).outcome == "paused"
    assert len(fake.calls) == 1
    assert service.recovery.get(result["operation_id"]).status == "paused"
    assert "synthetic secret" not in str(service.operations.list_events(result["operation_id"]))


def test_observation_failure_can_recover_without_write(flow):
    service, fake, _ = flow
    fake.post_fail = True
    result = execute(flow)
    assert result["status"] == "needs_reconciliation"
    fake.post_fail = False
    assert recover(service, result["operation_id"]).outcome == "succeeded"
    assert len(fake.calls) == 1


def test_admission_failure_rolls_back_operation_lock_and_recovery(flow, monkeypatch):
    service, fake, _ = flow
    original = SqlAlchemyRecoveryStore.prepare_and_claim

    def fail_after_insert(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic admission failure")

    monkeypatch.setattr(SqlAlchemyRecoveryStore, "prepare_and_claim", fail_after_insert)
    with pytest.raises(RuntimeError):
        execute(flow)
    assert not fake.calls and not service.operations.list()
    with session_scope() as session:
        assert session.scalar(select(OperationLockRecord)) is None
        assert session.scalar(select(OperationRecoveryItemRecord)) is None


def test_crash_after_dispatch_is_get_only_and_retains_uncertainty(flow):
    service, fake, _ = flow
    fake.after_write = lambda: (_ for _ in ()).throw(RuntimeError("process interrupted"))
    with pytest.raises(RuntimeError):
        execute(flow)
    operation = service.operations.list()[0]
    assert operation.status == "dispatching"
    assert recover(service, operation.operation_id).outcome == "paused"
    assert len(fake.calls) == 1


def test_foreign_action_target_lock_prevents_compute_admission(flow):
    service, fake, _ = flow
    SqlAlchemyDurableTargetLockRepository().acquire(operation_type="vm_start", cluster_id="gjallar-mvp",
        vmid=40000, owner_id="other-operation", reason="test")
    with pytest.raises(DurableTargetLockBusy):
        execute(flow)
    assert not fake.calls and not service.operations.list()


def test_lease_loss_after_write_cannot_commit_success(flow):
    from app.operations.recovery.domain import RecoveryLeaseLost
    service, fake, _ = flow

    def steal():
        with session_scope() as session:
            row = session.scalar(select(OperationRecoveryItemRecord))
            row.lease_token = "new-owner"

    fake.after_write = steal
    with pytest.raises(RecoveryLeaseLost):
        execute(flow)
    assert service.operations.list()[0].status == "dispatching"
    assert SqlAlchemyDurableTargetLockRepository().current(cluster_id="gjallar-mvp", vmid=40000) is not None
    assert len(fake.calls) == 1
