from datetime import datetime, timedelta, timezone

import pytest

from app.db.session import session_scope
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.locks.infrastructure.repository import SqlAlchemyDurableTargetLockRepository
from app.operations.recovery.infrastructure.models import OperationRecoveryItemRecord
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.vm_admission import VmMutationAdmission
from app.operations.vm_delete.application import DeleteService
from app.operations.vm_delete.domain import DeleteError, DeleteRequest
from app.operations.vm_delete.infrastructure import DeleteClient
from app.operations.vm_delete.recovery import DeleteRecoveryHandler
from app.proxmox.client import ProxmoxMutationError

DISK = 'store1:40000/vm-40000-disk-0.qcow2'
CI = 'store1:40000/vm-40000-cloudinit.qcow2'
ORPHAN = 'store1:40000/vm-40000-disk-9.qcow2'


class FakePve:
    def __init__(self):
        self.config = {'name': 'delete-test', 'digest': 'a' * 40, 'scsi0': DISK + ',size=20G', 'ide2': CI + ',media=cdrom'}
        self.volumes = {DISK: 20 * 1024 ** 3, CI: 4 * 1024 ** 2, ORPHAN: 1024 ** 3}
        self.snapshots = [{'name': 'current'}]
        self.pending = []
        self.power = 'stopped'
        self.permissions = {'VM.Audit', 'VM.Allocate'}
        self.exists = True
        self.calls = []
        self.reads = 0
        self.current_reads_after_delete = 0
        self.lost_response = False
        self.after_write = None
        self.drift = False
        self.task_result = {'status': 'stopped', 'exitstatus': 'OK'}
        self.keep_disk = False
        self.remove_orphan = False
        self.absence_unavailable = False

    def get_vm_permissions(self, **kwargs):
        # PVE removes VM-specific ACLs after deletion.
        return self.permissions if self.exists else set()
    def get_vm_current_config(self, **kwargs):
        self.reads += 1
        if not self.exists:
            self.current_reads_after_delete += 1
            raise ProxmoxMutationError('VM ACL removed')
        if self.drift and self.reads == 3: self.config['digest'] = 'b' * 40
        return dict(self.config)
    def get_vm_status(self, **kwargs): return {'status': self.power}
    def get_vm_pending(self, **kwargs): return self.pending
    def get_vm_snapshots(self, **kwargs): return self.snapshots
    def get_storage_permissions(self, **kwargs): return {'Datastore.Audit', 'Datastore.Allocate'}
    def get_node_storages(self, **kwargs): return [{'storage': 'store1', 'type': 'nfs', 'active': 1, 'enabled': 1, 'content': 'images,backup'}]
    def get_volume_info(self, *, volume, **kwargs): return {'size': self.volumes[volume], 'format': 'qcow2'}
    def list_vm_storage_images(self, **kwargs):
        return [{'volid': volume, 'vmid': 40000, 'size': size, 'format': 'qcow2'} for volume, size in self.volumes.items()]
    def assert_vmid_unused(self, **kwargs):
        if self.exists or self.absence_unavailable: raise ProxmoxMutationError('absence unavailable')
        return True
    def delete_vm_reviewed(self, **kwargs):
        self.calls.append(kwargs)
        self.exists = False
        if not self.keep_disk: self.volumes.pop(DISK)
        self.volumes.pop(CI)
        if self.remove_orphan: self.volumes.pop(ORPHAN)
        if self.after_write: self.after_write()
        if self.lost_response: raise ProxmoxMutationError('synthetic secret must not leak')
        return 'UPID:node1:0001:0002:0003:qmdestroy:40000:test@pve!test:'
    def wait_for_task(self, *, heartbeat, **kwargs):
        heartbeat()
        return self.task_result
    def get_task_status(self, **kwargs): return self.task_result


@pytest.fixture
def flow():
    fake = FakePve()
    service = DeleteService(client=DeleteClient(fake), admission=VmMutationAdmission(recovery_kind='vm_delete_observation'),
        operations=SqlAlchemyOperationStore(), recovery=SqlAlchemyRecoveryStore(), cluster_id='gjallar-mvp')
    before = service.review(node_id='node1', vmid=40000)['observed_before']
    request = DeleteRequest(idempotency_key='delete-test', expected_name='delete-test', expected_digest='a' * 40,
        expected_resources_digest=before['resources_digest'], confirmation='40000/delete-test', delete_acknowledged=True)
    return service, fake, request


def execute(flow):
    service, _, request = flow
    return service.execute(node_id='node1', vmid=40000, request=request, actor={'role': 'operator', 'user_id': 'test'})


def recover(service, operation_id):
    with session_scope() as session:
        session.get(OperationRecoveryItemRecord, operation_id).lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    lease = service.recovery.claim_operation(operation_id, lease_owner='delete-test', lease_seconds=60)
    return DeleteRecoveryHandler(operations=service.operations, recovery=service.recovery, service_factory=lambda: service).handle(lease)


def test_delete_verified_after_acl_removal_preserves_orphan_and_never_redeletes(flow):
    service, fake, _ = flow
    result = execute(flow)
    assert result['status'] == 'succeeded'
    assert set(result['observed_after']['deleted_volumes']) == {DISK, CI}
    assert result['observed_after']['preserved_volumes'] == [ORPHAN]
    assert fake.current_reads_after_delete == 0 and not fake.get_vm_permissions()
    assert execute(flow)['idempotent_replay'] and len(fake.calls) == 1
    assert SqlAlchemyDurableTargetLockRepository().current(cluster_id='gjallar-mvp', vmid=40000) is None


@pytest.mark.parametrize('patch', [{'protection': 1}, {'template': 1}, {'lock': 'backup'}, {'unused0': ORPHAN},
    {'scsi1': ORPHAN}, {'hostpci0': '0000:00:01'}, {'ide2': 'store1:iso/external.iso,media=cdrom'},
    {'scsi0': 'store1:40001/vm-40001-disk-0.qcow2,size=20G'}, {'scsi0': DISK + ',shared=1'}, {'hookscript': 'store1:snippet/hook'}])
def test_delete_unsupported_or_protected_config_has_no_write(flow, patch):
    service, fake, _ = flow
    fake.config.update(patch)
    with pytest.raises(DeleteError): execute(flow)
    assert not fake.calls and not service.operations.list()


@pytest.mark.parametrize('reason', ['snapshot', 'unknown_snapshot', 'pending', 'running', 'permission', 'wrong_name', 'no_ack', 'volume_drift', 'config_drift'])
def test_delete_prechecks_and_review_fences(flow, reason):
    service, fake, request = flow
    if reason == 'snapshot': fake.snapshots.append({'name': 'checkpoint'})
    if reason == 'unknown_snapshot': fake.snapshots = []
    if reason == 'pending': fake.pending = [{'key': 'memory', 'pending': 4096}]
    if reason == 'running': fake.power = 'running'
    if reason == 'permission': fake.permissions.remove('VM.Allocate')
    if reason == 'wrong_name': request = request.model_copy(update={'confirmation': '40000/other'})
    if reason == 'no_ack': request = request.model_copy(update={'delete_acknowledged': False})
    if reason == 'volume_drift': fake.volumes[ORPHAN] = 2 * 1024 ** 3
    if reason == 'config_drift': fake.drift = True
    with pytest.raises(DeleteError): execute((service, fake, request))
    assert not fake.calls
    assert SqlAlchemyDurableTargetLockRepository().current(cluster_id='gjallar-mvp', vmid=40000) is None


@pytest.mark.parametrize('reason', ['remaining_disk', 'orphan_missing', 'absence_unavailable', 'id_reused', 'task_failed'])
def test_delete_partial_result_never_claims_success_or_unlocks(flow, reason):
    service, fake, _ = flow
    fake.keep_disk = reason == 'remaining_disk'
    fake.remove_orphan = reason == 'orphan_missing'
    fake.absence_unavailable = reason == 'absence_unavailable'
    if reason == 'id_reused': fake.after_write = lambda: setattr(fake, 'exists', True)
    if reason == 'task_failed': fake.task_result = {'status': 'stopped', 'exitstatus': 'ERROR'}
    result = execute(flow)
    assert result['status'] == 'needs_reconciliation'
    assert SqlAlchemyDurableTargetLockRepository().current(cluster_id='gjallar-mvp', vmid=40000) is not None
    assert service.recovery.get(result['operation_id']).status == 'paused'
    if reason == 'remaining_disk': assert result['observed_after']['remaining_volumes'] == [DISK]
    if reason == 'orphan_missing': assert result['observed_after']['preservation_unconfirmed'] == [ORPHAN]


def test_unknown_delete_response_never_succeeds_from_absence_alone(flow):
    service, fake, _ = flow
    fake.lost_response = True
    result = execute(flow)
    assert not fake.exists
    assert recover(service, result['operation_id']).outcome == 'paused'
    assert len(fake.calls) == 1 and execute(flow)['idempotent_replay']
    assert 'synthetic secret' not in str(service.operations.list_events(result['operation_id']))


def test_delete_task_can_finish_with_get_only_recovery(flow):
    service, fake, _ = flow
    fake.task_result = {'status': 'running'}
    result = execute(flow)
    fake.task_result = {'status': 'stopped', 'exitstatus': 'OK'}
    assert recover(service, result['operation_id']).outcome == 'succeeded'
    assert len(fake.calls) == 1


def test_storage_audit_alone_cannot_prove_absence_after_vm_acl_removal(flow):
    _, fake, _ = flow
    fake.get_storage_permissions = lambda **kwargs: {'Datastore.Audit'}
    with pytest.raises(DeleteError) as caught: execute(flow)
    assert caught.value.code == 'VM_DELETE_PERMISSION_DENIED'
    assert not fake.calls


def test_lost_storage_authority_after_delete_does_not_treat_filtered_empty_list_as_absence(flow):
    service, fake, _ = flow
    fake.after_write = lambda: setattr(fake, 'get_storage_permissions', lambda **kwargs: {'Datastore.Audit'})
    fake.list_vm_storage_images = lambda **kwargs: [] if not fake.exists else [
        {'volid': volume, 'vmid': 40000, 'size': size, 'format': 'qcow2'} for volume, size in fake.volumes.items()]
    result = execute(flow)
    assert result['status'] == 'needs_reconciliation'
    assert result['failure_code'] == 'VM_DELETE_PERMISSION_DENIED'
    recover(service, result['operation_id'])
    assert len(fake.calls) == 1
    assert service.operations.get(result['operation_id']).status == 'needs_reconciliation'
