from datetime import datetime, timedelta, timezone

import pytest

from app.operations.core.domain import verify_event_chain
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.locks.infrastructure.repository import SqlAlchemyDurableTargetLockRepository
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.recovery.infrastructure.models import OperationRecoveryItemRecord
from app.operations.recovery.domain import RecoveryLeaseLost
from app.db.session import session_scope
from app.operations.vm_admission import VmMutationAdmission
from app.operations.vm_disk.application import DiskService
from app.operations.vm_disk.domain import GIB, DiskError, DiskRequest
from app.operations.vm_disk.infrastructure import DiskClient
from app.operations.vm_disk.recovery import DiskRecoveryHandler
from app.proxmox.client import ProxmoxMutationError


class Pve:
    def __init__(self):
        self.size = 20
        self.disk_size = 20
        self.name = "test-vm"
        self.digest = "a" * 40
        self.power = "stopped"
        self.pending = []
        self.calls = []
        self.task_status = "stopped"
        self.exitstatus = "OK"
        self.lost_response = self.wait_unavailable = self.partial = self.bad_upid = False
        self.permissions = {"VM.Audit", "VM.Config.Disk"}
        self.after_write = None

    def get_vm_current_config(self, **kwargs):
        return {"name": self.name, "digest": self.digest,
                "scsi0": f"store1:40000/vm-40000-disk-0.qcow2,size={self.size}G"}

    def get_vm_status(self, **kwargs):
        return {"status": self.power}

    def get_vm_pending(self, **kwargs):
        return self.pending

    def get_node_storages(self, **kwargs):
        return [{"storage": "store1", "type": "nfs", "active": 1, "enabled": 1}]

    def get_volume_info(self, **kwargs):
        return {"size": self.disk_size * GIB, "format": "qcow2"}

    def get_vm_permissions(self, **kwargs):
        return self.permissions

    def get_storage_permissions(self, **kwargs):
        return {"Datastore.Audit", "Datastore.AllocateSpace"}

    def resize_vm_disk_reviewed(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["digest"] == self.digest
        self.size = kwargs["size_gib"]
        if not self.partial:
            self.disk_size = self.size
        self.digest = "b" * 40
        if self.after_write:
            self.after_write()
        if self.lost_response:
            raise ProxmoxMutationError("synthetic secret")
        return "not-a-task" if self.bad_upid else "UPID:node1:00000001:00000002:00000003:resize:40000:test@pve!gjallar:"

    def get_task_status(self, **kwargs):
        return {"status": self.task_status, "exitstatus": self.exitstatus}

    def wait_for_task(self, *, heartbeat, **kwargs):
        heartbeat()
        if self.wait_unavailable:
            raise ProxmoxMutationError("synthetic secret")
        return self.get_task_status(**kwargs)


@pytest.fixture
def flow():
    pve = Pve()
    service = DiskService(client=DiskClient(pve), admission=VmMutationAdmission(recovery_kind="vm_disk_observation"),
        operations=SqlAlchemyOperationStore(), recovery=SqlAlchemyRecoveryStore(), cluster_id="gjallar-mvp")
    request = DiskRequest(idempotency_key="disk-test", expected_digest="a" * 40, expected_name="test-vm",
        expected_volume="store1:40000/vm-40000-disk-0.qcow2", expected_size_bytes=20 * GIB, size_gib=24)
    return service, pve, request


def execute(flow):
    service, _, request = flow
    return service.execute(node_id="node1", vmid=40000, request=request, actor={"user_id": "operator", "role": "operator"})


def recover(service, operation_id):
    lease = service.recovery.claim_operation(operation_id, lease_owner="disk-recovery", lease_seconds=60)
    return DiskRecoveryHandler(operations=service.operations, recovery=service.recovery, service_factory=lambda: service).handle(lease)


def test_resize_verified_with_task_and_volume_then_replay(flow):
    service, pve, request = flow
    result = execute(flow)
    assert result["status"] == "succeeded" and result["observed_after"]["size_bytes"] == 24 * GIB
    assert result["task"]["status"] == "stopped" and result["task"]["exitstatus"] == "OK"
    assert service.recovery.get(result["operation_id"]).status == "completed"
    assert SqlAlchemyDurableTargetLockRepository().current(cluster_id="gjallar-mvp", vmid=40000) is None
    assert verify_event_chain(service.operations.list_events(result["operation_id"]))
    pve.disk_size = 30
    assert execute(flow)["idempotent_replay"] is True
    assert len(pve.calls) == 1
    with pytest.raises(DiskError, match="같은 요청"):
        execute((service, pve, request.model_copy(update={"size_gib": 30})))


@pytest.mark.parametrize("flag", ["lost_response", "bad_upid"])
def test_missing_bound_task_never_completes_or_redispatches(flow, flag):
    service, pve, _ = flow
    setattr(pve, flag, True)
    result = execute(flow)
    assert result["status"] == "needs_reconciliation"
    assert recover(service, result["operation_id"]).outcome == "paused"
    assert len(pve.calls) == 1
    assert SqlAlchemyDurableTargetLockRepository().current(cluster_id="gjallar-mvp", vmid=40000) is not None
    assert "synthetic secret" not in str(service.operations.get(result["operation_id"]).details)


def test_restart_observes_bound_task_without_writes(flow):
    service, pve, _ = flow
    pve.wait_unavailable = True
    result = execute(flow)
    assert result["status"] == "needs_reconciliation"
    pve.wait_unavailable = False
    assert recover(service, result["operation_id"]).outcome == "succeeded"
    assert len(pve.calls) == 1


def test_task_ok_with_wrong_actual_bytes_stays_unconfirmed(flow):
    service, pve, _ = flow
    pve.partial = True
    result = execute(flow)
    assert result["status"] == "needs_reconciliation"
    assert result["failure_code"] == "VM_DISK_SIZE_UNCONFIRMED"
    pve.disk_size = 24
    assert recover(service, result["operation_id"]).outcome == "succeeded"
    assert len(pve.calls) == 1


def test_task_error_never_proves_success_even_with_matching_size(flow):
    service, pve, _ = flow
    pve.exitstatus = "raw sensitive failure"
    result = execute(flow)
    assert result["status"] == "needs_reconciliation"
    assert result["task"]["exitstatus"] == "ERROR"
    assert recover(service, result["operation_id"]).outcome == "paused"


def test_permissions_and_drift_block_before_dispatch(flow, monkeypatch):
    service, pve, _ = flow
    pve.permissions = {"VM.Audit"}
    with pytest.raises(DiskError) as denied:
        execute(flow)
    assert denied.value.status_code == 403
    pve.permissions.add("VM.Config.Disk")
    original = service.admission.prepare

    def prepare(*args, **kwargs):
        result = original(*args, **kwargs)
        pve.power = "running"
        return result

    monkeypatch.setattr(service.admission, "prepare", prepare)
    with pytest.raises(DiskError, match="정지"):
        execute(flow)
    assert not pve.calls
    assert service.operations.list()[0].status == "blocked"
    assert SqlAlchemyDurableTargetLockRepository().current(cluster_id="gjallar-mvp", vmid=40000) is None


def expire_lease(service):
    operation = service.operations.list()[0]
    with session_scope() as session:
        session.get(OperationRecoveryItemRecord, operation.operation_id).lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    return operation


def test_expired_foreground_cannot_commit_ack_or_release_lock(flow):
    service, pve, _ = flow
    pve.after_write = lambda: expire_lease(service)
    with pytest.raises(RecoveryLeaseLost):
        execute(flow)
    operation = service.operations.list()[0]
    assert operation.status == "dispatching" and not operation.details.get("proxmox_upid")
    assert recover(service, operation.operation_id).outcome == "paused"
    assert len(pve.calls) == 1
    assert SqlAlchemyDurableTargetLockRepository().current(cluster_id="gjallar-mvp", vmid=40000) is not None


def test_atomic_admission_crash_before_dispatch_is_recoverable(flow, monkeypatch):
    service, pve, _ = flow
    prepare = service.admission.prepare

    def interrupted(*args, **kwargs):
        prepare(*args, **kwargs)
        raise RuntimeError("injected process interruption")

    monkeypatch.setattr(service.admission, "prepare", interrupted)
    with pytest.raises(RuntimeError, match="interruption"):
        execute(flow)
    operation = expire_lease(service)
    assert operation.status == "planned" and not pve.calls
    assert recover(service, operation.operation_id).outcome == "blocked"
    assert SqlAlchemyDurableTargetLockRepository().current(cluster_id="gjallar-mvp", vmid=40000) is None
