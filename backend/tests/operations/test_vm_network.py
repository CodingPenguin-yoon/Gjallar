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
from app.operations.vm_network.application import NetworkService
from app.operations.vm_network.domain import NetworkError, NetworkRequest
from app.operations.vm_network.infrastructure import NetworkAdmission, NetworkClient
from app.operations.vm_network.recovery import NetworkRecoveryHandler
from app.proxmox.client import ProxmoxMutationError


class FakeClient:
    def __init__(self):
        self.config = {"name": "test-vm", "net0": "virtio=02:00:00:00:00:01,bridge=vmbr0,firewall=1", "digest": "a" * 40}
        self.status = "stopped"
        self.pending = []
        self.permissions = {"VM.Audit", "VM.Config.Network"}
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

    def get_node_network_snapshot(self, **kwargs):
        return {"pending_changes": False, "interfaces": [
            {"iface": "vmbr0", "type": "bridge", "active": 1, "exists": 1},
            {"iface": "vmbr1", "type": "bridge", "active": 1, "exists": 1, "bridge_vlan_aware": 1},
        ]}

    def get_bridge_permissions(self, **kwargs):
        return {"SDN.Audit", "SDN.Use"}

    def set_vm_config(self, *, node, vmid, config):
        self.calls.append((node, vmid, config))
        assert config["digest"] == self.config["digest"]
        self.config.update(net0=config["net0"], digest="b" * 40)
        if self.partial:
            self.config["net0"] = self.config["net0"].replace("tag=100", "tag=200")
        if self.after_write:
            self.after_write()
        if self.lost_response:
            raise ProxmoxMutationError("synthetic secret must not leak")


@pytest.fixture
def flow():
    fake = FakeClient()
    service = NetworkService(client=NetworkClient(fake), admission=NetworkAdmission(),
        operations=SqlAlchemyOperationStore(), recovery=SqlAlchemyRecoveryStore(), cluster_id="gjallar-mvp")
    request = NetworkRequest(idempotency_key="network-test", expected_digest="a" * 40,
        expected_name="test-vm", expected_net0=fake.config["net0"], bridge_id="vmbr1", vlan_tag=100)
    return service, fake, request


def execute(flow):
    service, _, request = flow
    return service.execute(node_id="node1", vmid=40000, request=request, actor={"user_id": "operator", "role": "operator"})


def recover(service, operation_id):
    with session_scope() as session:
        row = session.get(OperationRecoveryItemRecord, operation_id)
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    lease = service.recovery.claim_operation(operation_id, lease_owner="test-recovery", lease_seconds=60)
    return NetworkRecoveryHandler(operations=service.operations, recovery=service.recovery,
                                  service_factory=lambda: service).handle(lease)


def test_verified_result_replay_and_event_chain(flow):
    service, fake, request = flow
    result = execute(flow)
    assert result["status"] == "succeeded"
    assert result["observed_before"]["bridge_id"] == "vmbr0"
    assert result["observed_after"]["bridge_id"] == "vmbr1"
    assert result["observed_after"]["vlan_tag"] == 100
    assert service.recovery.get(result["operation_id"]).status == "completed"
    assert SqlAlchemyDurableTargetLockRepository().current(cluster_id="gjallar-mvp", vmid=40000) is None
    # A later external state change cannot replace the historical verified result.
    fake.config["net0"] = fake.config["net0"].replace("tag=100", "tag=200")
    replay = execute(flow)
    assert replay["idempotent_replay"] and replay["observed_after"]["bridge_id"] == "vmbr1"
    assert len(fake.calls) == 1
    assert verify_event_chain(service.operations.list_events(result["operation_id"]))
    with pytest.raises(NetworkError, match="같은 요청"):
        execute((service, fake, request.model_copy(update={"vlan_tag": 200})))


def test_permission_pending_and_power_drift(flow):
    service, fake, _ = flow
    fake.permissions.remove("VM.Config.Network")
    with pytest.raises(NetworkError) as failure:
        execute(flow)
    assert failure.value.status_code == 403 and not fake.calls
    fake.permissions.add("VM.Config.Network")
    fake.pending = [{"key": "memory", "pending": 1024}]
    with pytest.raises(NetworkError, match="대기 중"):
        execute(flow)
    fake.pending = []
    fake.reads = 0
    fake.drift = True
    with pytest.raises(NetworkError, match="정지된"):
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
    assert result["observed_after"]["bridge_id"] == "vmbr1" and result["observed_after"]["vlan_tag"] == 200
    with pytest.raises(DurableTargetLockBusy):
        SqlAlchemyDurableTargetLockRepository().acquire(operation_type="vm_start", cluster_id="gjallar-mvp",
            vmid=40000, owner_id="other", reason="test")
    fake.config["net0"] = fake.config["net0"].replace("tag=200", "tag=100")
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


def test_foreign_action_target_lock_prevents_network_admission(flow):
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


def test_host_network_changes_after_review_block_dispatch(flow):
    service, fake, _ = flow
    original = fake.get_node_network_snapshot
    def snapshot(**kwargs):
        value = original(**kwargs)
        value['pending_changes'] = fake.reads >= 2
        return value
    fake.get_node_network_snapshot = snapshot
    with pytest.raises(NetworkError) as failure:
        execute(flow)
    assert failure.value.code == 'VM_NETWORK_HOST_PENDING'
    assert not fake.calls
    assert service.operations.list()[0].status == 'blocked'
    assert SqlAlchemyDurableTargetLockRepository().current(cluster_id='gjallar-mvp', vmid=40000) is None


def test_unrelated_mac_change_cannot_be_verified_as_requested_result(flow):
    service, fake, _ = flow
    def change_mac():
        fake.config['net0'] = fake.config['net0'].replace('02:00:00:00:00:01', '02:00:00:00:00:02')
    fake.after_write = change_mac
    result = execute(flow)
    assert result['status'] == 'needs_reconciliation'
    assert result['observed_after']['vlan_tag'] == 100
    assert result['observed_after']['mac'] == '02:00:00:00:00:02'
    assert service.recovery.get(result['operation_id']).status == 'paused'
    assert len(fake.calls) == 1


def test_bridge_visibility_alone_does_not_grant_use(flow):
    service, fake, _ = flow
    fake.get_bridge_permissions = lambda **kwargs: {'SDN.Audit'}
    with pytest.raises(NetworkError) as failure:
        execute(flow)
    assert failure.value.code == 'VM_NETWORK_BRIDGE_UNAVAILABLE'
    assert not service.operations.list() and not fake.calls
