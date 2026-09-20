from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.db.session import session_scope
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.locks.infrastructure.repository import SqlAlchemyDurableTargetLockRepository
from app.operations.recovery.infrastructure.models import OperationRecoveryItemRecord
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.vm_admission import VmMutationAdmission
from app.operations.vm_clone.application import CloneService
from app.operations.vm_clone.domain import CloneError, CloneRequest, verified_task_reference
from app.operations.vm_clone.infrastructure import CloneClient
from app.operations.vm_clone.recovery import CloneRecoveryHandler
from app.proxmox.client import ProxmoxMutationError

MAC = '02:00:00:00:00:01'
UUID = '00000000-0000-0000-0000-000000000001'


class FakePve:
    def __init__(self):
        self.configs = {40000: {'name': 'original', 'digest': 'a' * 40, 'cores': 2, 'memory': 2048, 'onboot': 0,
            'scsi0': 'source:40000/vm-40000-disk-0.qcow2,size=20G',
            'ide2': 'source:40000/vm-40000-cloudinit.qcow2,media=cdrom',
            'net0': f'virtio={MAC},bridge=vmbr0,firewall=1', 'smbios1': f'uuid={UUID}'}}
        self.calls = []
        self.task_reads = []
        self.lost_response = False
        self.after_write = None
        self.task_result = {'status': 'stopped', 'exitstatus': 'OK'}
        self.power = 'stopped'
        self.permission = True
        self.source_reads = 0
        self.precheck_drift = False

    def get_vm_current_config(self, *, node, vmid):
        if vmid == 40000:
            self.source_reads += 1
            if self.precheck_drift and self.source_reads == 2:
                self.configs[vmid]['digest'] = 'c' * 40
        return dict(self.configs[vmid])

    def get_vm_status(self, **kwargs): return {'status': self.power}
    def get_vm_pending(self, **kwargs): return []
    def get_vm_permissions(self, *, vmid): return {'VM.Audit', 'VM.Clone', 'VM.Allocate', 'VM.Config.Disk'} if self.permission else {'VM.Audit'}
    def get_storage_permissions(self, **kwargs): return {'Datastore.Audit', 'Datastore.AllocateSpace'}
    def get_bridge_permissions(self, **kwargs): return {'SDN.Use'}
    def get_node_storages(self, **kwargs):
        return [{'storage': name, 'type': 'nfs', 'active': 1, 'enabled': 1, 'content': 'images,backup'} for name in ('source', 'dest')]
    def get_volume_info(self, **kwargs): return {'size': 20 * 1024 ** 3, 'format': 'qcow2'}
    def list_vm_resources(self): return [{'vmid': vmid, 'node': 'node1', 'type': 'qemu'} for vmid in self.configs]

    def clone_vm_reviewed(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs['vmid'] == 40000 and kwargs['new_vmid'] == 40001
        assert kwargs['disk_format'] == 'qcow2' and kwargs['storage'] == 'dest'
        target = deepcopy(self.configs[40000])
        target.update(name=kwargs['name'], digest='b' * 40, description=kwargs['description'],
            scsi0='dest:40001/vm-40001-disk-0.qcow2,size=20G', ide2='dest:40001/vm-40001-cloudinit.qcow2,media=cdrom',
            net0=f'virtio=02:00:00:00:00:02,bridge=vmbr0,firewall=1', smbios1='uuid=00000000-0000-0000-0000-000000000002')
        self.configs[40001] = target
        if self.after_write:
            self.after_write()
        if self.lost_response:
            raise ProxmoxMutationError('synthetic secret must not leak')
        return 'UPID:node1:0001:0002:0003:qmclone:40000:test@pve!test:'

    def wait_for_task(self, *, heartbeat, **kwargs):
        heartbeat()
        return self.get_task_status(**kwargs)
    def get_task_status(self, **kwargs):
        self.task_reads.append(kwargs)
        return self.task_result


@pytest.fixture
def flow():
    fake = FakePve()
    service = CloneService(client=CloneClient(fake), admission=VmMutationAdmission(recovery_kind='vm_clone_observation'),
        operations=SqlAlchemyOperationStore(), recovery=SqlAlchemyRecoveryStore(), cluster_id='gjallar-mvp')
    request = CloneRequest(idempotency_key='clone-test', expected_digest='a' * 40, expected_name='original',
        expected_volume='source:40000/vm-40000-disk-0.qcow2', expected_size_bytes=20 * 1024 ** 3,
        new_vmid=40001, name='copy-test', storage_id='dest', guest_identity_acknowledged=True)
    return service, fake, request


def execute(flow):
    service, _, request = flow
    return service.execute(node_id='node1', vmid=40000, request=request, actor={'role': 'operator', 'user_id': 'test'})


def recover(service, operation_id):
    with session_scope() as session:
        row = session.get(OperationRecoveryItemRecord, operation_id)
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    lease = service.recovery.claim_operation(operation_id, lease_owner='clone-test', lease_seconds=60)
    return CloneRecoveryHandler(operations=service.operations, recovery=service.recovery, service_factory=lambda: service).handle(lease)


def test_full_clone_preserves_source_and_verifies_new_identity_and_both_locks(flow):
    service, fake, request = flow
    original = deepcopy(fake.configs[40000])
    result = execute(flow)
    assert result['status'] == 'succeeded' and result['target']['vmid'] == 40001
    assert fake.configs[40000] == original
    assert result['observed_after']['destination']['mac'] != MAC
    assert result['observed_after']['destination']['smbios_uuid'] != UUID
    assert result['observed_after']['destination']['status'] == 'stopped'
    assert result['observed_after']['destination']['operation_marker'] == result['operation_id']
    repository = SqlAlchemyDurableTargetLockRepository()
    assert all(repository.current(cluster_id='gjallar-mvp', vmid=vmid) is None for vmid in (40000, 40001))
    assert execute(flow)['idempotent_replay'] and len(fake.calls) == 1
    with pytest.raises(CloneError, match='같은 요청'):
        execute((service, fake, request.model_copy(update={'name': 'another'})))


@pytest.mark.parametrize('patch', [{'onboot': 1}, {'template': 1}, {'lock': 'backup'}, {'hostpci0': '0000:00:01'},
    {'net1': f'virtio={MAC},bridge=vmbr0'}, {'scsi1': 'source:40000/vm-40000-disk-1.qcow2,size=1G'},
    {'efidisk0': 'source:40000/vm-40000-disk-2.raw'}, {'ide2': 'source:iso/boot.iso,media=cdrom'},
    {'scsi0': 'source:40099/vm-40099-disk-0.qcow2,size=20G'}, {'args': '-custom'}])
def test_unsupported_source_never_dispatches_or_records_operation(flow, patch):
    service, fake, _ = flow
    fake.configs[40000].update(patch)
    with pytest.raises(CloneError): execute(flow)
    assert not fake.calls and not service.operations.list()


@pytest.mark.parametrize('reason', ['occupied', 'permission', 'running', 'ack', 'drift'])
def test_clone_prechecks_and_review_drift(flow, reason):
    service, fake, request = flow
    if reason == 'occupied': fake.configs[40001] = {'name': 'preexisting'}
    if reason == 'permission': fake.permission = False
    if reason == 'running': fake.power = 'running'
    if reason == 'ack': request = request.model_copy(update={'guest_identity_acknowledged': False})
    if reason == 'drift': fake.precheck_drift = True
    with pytest.raises(CloneError): execute((service, fake, request))
    assert not fake.calls
    repository = SqlAlchemyDurableTargetLockRepository()
    assert all(repository.current(cluster_id='gjallar-mvp', vmid=vmid) is None for vmid in (40000, 40001))


def test_clone_response_loss_preserves_both_locks_even_when_copy_exists(flow):
    service, fake, _ = flow
    fake.lost_response = True
    result = execute(flow)
    assert result['status'] == 'needs_reconciliation'
    assert recover(service, result['operation_id']).outcome == 'paused'
    assert len(fake.calls) == 1 and not fake.task_reads
    repository = SqlAlchemyDurableTargetLockRepository()
    assert all(repository.current(cluster_id='gjallar-mvp', vmid=vmid) is not None for vmid in (40000, 40001))
    assert 'synthetic secret' not in str(service.operations.list_events(result['operation_id']))


@pytest.mark.parametrize('damage', ['source_changed', 'same_mac', 'same_uuid', 'wrong_marker', 'wrong_disk', 'task_failed'])
def test_clone_partial_or_unconfirmed_result_never_releases_locks(flow, damage):
    service, fake, _ = flow
    def alter():
        if damage == 'source_changed': fake.configs[40000]['digest'] = 'c' * 40
        if damage == 'same_mac': fake.configs[40001]['net0'] = fake.configs[40000]['net0']
        if damage == 'same_uuid': fake.configs[40001]['smbios1'] = f'uuid={UUID}'
        if damage == 'wrong_marker': fake.configs[40001]['description'] = 'other operation'
        if damage == 'wrong_disk': fake.configs[40001]['scsi0'] = fake.configs[40000]['scsi0']
        if damage == 'task_failed': fake.task_result = {'status': 'stopped', 'exitstatus': 'ERROR'}
    fake.after_write = alter
    result = execute(flow)
    assert result['status'] == 'needs_reconciliation'
    assert service.recovery.get(result['operation_id']).status == 'paused'
    assert len(fake.calls) == 1


def test_clone_task_pending_can_finish_via_get_only_recovery(flow):
    service, fake, _ = flow
    fake.task_result = {'status': 'running'}
    result = execute(flow)
    assert service.recovery.get(result['operation_id']).status == 'retry_wait'
    fake.task_result = {'status': 'stopped', 'exitstatus': 'OK'}
    assert recover(service, result['operation_id']).outcome == 'succeeded'
    assert len(fake.calls) == 1


def test_clone_upid_is_bound_to_source_not_destination():
    with pytest.raises(CloneError):
        verified_task_reference('UPID:node1:0001:0002:0003:qmclone:40001:test@pve!test:', node_id='node1', vmid=40000)
