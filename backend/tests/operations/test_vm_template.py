import json
from datetime import datetime, timedelta, timezone

import pytest

from app.db.session import session_scope
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.recovery.infrastructure.models import OperationRecoveryItemRecord
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.vm_admission import VmMutationAdmission
from app.operations.vm_template.application import TemplateService
from app.operations.vm_template.domain import TemplateError, TemplateRequest
from app.operations.vm_template.infrastructure import TemplateClient
from app.operations.vm_template.recovery import TemplateRecoveryHandler
from app.proxmox.client import ProxmoxMutationError

DISK = 'store1:40000/vm-40000-disk-0.qcow2'
BASE = 'store1:40000/base-40000-disk-0.qcow2'
CI = 'store1:40000/vm-40000-cloudinit.qcow2'


class FakePve:
    def __init__(self):
        self.config = {'name': 'template-test', 'digest': 'a' * 40, 'scsi0': DISK + ',size=20G', 'ide2': CI + ',media=cdrom',
                       'agent': 'enabled=1', 'cipassword': 'synthetic-sensitive-value', 'sshkeys': 'synthetic-public-key'}
        self.volumes = {DISK: 20 * 1024 ** 3, CI: 4 * 1024 ** 2}
        self.snapshots, self.pending, self.power = [{'name': 'current'}], [], 'stopped'
        self.permissions = {'VM.Audit', 'VM.Allocate', 'VM.Config.Disk'}
        self.calls, self.lost_response, self.partial, self.drift = [], False, False, False
        self.reads = 0
        self.upid = 'UPID:node1:0001:0002:0003:qmtemplate:40000:test@pve!test:'
        self.task_result = {'status': 'stopped', 'exitstatus': 'OK'}
    def get_vm_permissions(self, **kwargs): return self.permissions
    def get_vm_current_config(self, **kwargs):
        self.reads += 1
        if self.drift and self.reads == 3: self.config['digest'] = 'b' * 40
        return dict(self.config)
    def get_vm_status(self, **kwargs): return {'status': self.power}
    def get_vm_pending(self, **kwargs): return self.pending
    def get_vm_snapshots(self, **kwargs): return self.snapshots
    def get_storage_permissions(self, **kwargs): return {'Datastore.Audit'}
    def get_node_storages(self, **kwargs): return [{'storage': 'store1', 'type': 'nfs', 'active': 1, 'enabled': 1, 'content': 'images'}]
    def get_volume_info(self, *, volume, **kwargs):
        if volume not in self.volumes: raise ProxmoxMutationError('missing')
        return {'size': self.volumes[volume], 'format': 'qcow2'}
    def convert_vm_to_template(self, **kwargs):
        self.calls.append(kwargs)
        self.config.update(template=1, digest='c' * 40)
        if not self.partial:
            self.config['scsi0'] = BASE + ',size=20G'
            self.volumes[BASE] = self.volumes.pop(DISK)
        if self.lost_response: raise ProxmoxMutationError('synthetic-sensitive-value')
        return self.upid
    def wait_for_task(self, *, heartbeat, **kwargs):
        heartbeat()
        return self.task_result
    def get_task_status(self, **kwargs): return self.task_result


@pytest.fixture
def flow():
    fake = FakePve()
    service = TemplateService(client=TemplateClient(fake), admission=VmMutationAdmission(recovery_kind='vm_template_observation'),
        operations=SqlAlchemyOperationStore(), recovery=SqlAlchemyRecoveryStore(), cluster_id='gjallar-mvp')
    before = service.review(node_id='node1', vmid=40000)['observed_before']
    request = TemplateRequest(idempotency_key='template-test', expected_name='template-test', expected_digest='a' * 40,
        expected_resources_digest=before['resources_digest'], confirmation='40000/template-test', guest_prepared=True, conversion_acknowledged=True)
    return service, fake, request


def execute(flow):
    service, _, request = flow
    return service.execute(node_id='node1', vmid=40000, request=request, actor={'role': 'operator', 'user_id': 'test'})


def recover(service, operation_id):
    with session_scope() as session:
        session.get(OperationRecoveryItemRecord, operation_id).lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    lease = service.recovery.claim_operation(operation_id, lease_owner='template-test', lease_seconds=60)
    return TemplateRecoveryHandler(operations=service.operations, recovery=service.recovery, service_factory=lambda: service).handle(lease)


def test_conversion_verifies_actual_volume_and_replays_without_dispatch(flow):
    service, fake, _ = flow
    result = execute(flow)
    assert result['status'] == 'succeeded'
    assert result['observed_after']['volumes'][0]['volume_id'] == BASE
    assert result['observed_after']['volumes'][1]['volume_id'] == CI
    assert execute(flow)['idempotent_replay'] is True
    assert len(fake.calls) == 1
    evidence = json.dumps(service.operations.get(result['operation_id']).details)
    assert 'synthetic-sensitive-value' not in evidence and 'synthetic-public-key' not in evidence
    assert result['observed_after']['guest_readiness'] == 'operator_attested_not_runtime_verified'


@pytest.mark.parametrize('field,value', [('guest_prepared', False), ('conversion_acknowledged', False),
    ('confirmation', '40001/template-test'), ('expected_digest', 'b' * 40), ('expected_resources_digest', 'sha256:' + 'b' * 64)])
def test_review_drift_or_missing_attestation_blocks(flow, field, value):
    service, fake, request = flow
    with pytest.raises(TemplateError): execute((service, fake, request.model_copy(update={field: value})))
    assert not fake.calls


@pytest.mark.parametrize('patch', [{'template': 1}, {'lock': 'backup'}, {'unused0': DISK}, {'scsi1': DISK},
    {'agent': '0'}, {'hostpci0': '00:01.0'}, {'cicustom': 'user=custom'}, {'scsi0': 'other:40001/vm-40001-disk-0.qcow2'},
    {'ide2': 'none,media=cdrom'}, {'scsi0': DISK + ',shared=1'}])
def test_unsupported_source_is_blocked(flow, patch):
    service, fake, _ = flow
    fake.config.update(patch)
    with pytest.raises(TemplateError): execute(flow)
    assert not fake.calls


@pytest.mark.parametrize('field,value', [('power', 'running'), ('pending', [{'key': 'memory', 'pending': 2048}]),
    ('snapshots', [{'name': 'current'}, {'name': 'backup'}]), ('permissions', {'VM.Audit'})])
def test_state_and_permission_checks(flow, field, value):
    _, fake, _ = flow
    setattr(fake, field, value)
    with pytest.raises(TemplateError): execute(flow)
    assert not fake.calls


def test_pre_dispatch_drift_releases_without_mutation(flow):
    service, fake, _ = flow
    fake.drift = True
    with pytest.raises(TemplateError, match='변경'): execute(flow)
    assert not fake.calls


@pytest.mark.parametrize('mode', ['lost_response', 'partial', 'bad_upid', 'failed_task', 'changed_config', 'changed_size'])
def test_uncertain_or_partial_result_never_retries(flow, mode):
    service, fake, _ = flow
    if mode in {'lost_response', 'partial'}: setattr(fake, mode, True)
    if mode == 'bad_upid': fake.upid = fake.upid.replace('qmtemplate:40000', 'qmtemplate:40001')
    if mode == 'failed_task': fake.task_result['exitstatus'] = 'ERROR'
    original = fake.convert_vm_to_template
    def apply(**kwargs):
        result = original(**kwargs)
        if mode == 'changed_config': fake.config['memory'] = 8192
        if mode == 'changed_size': fake.volumes[BASE] += 1024
        return result
    fake.convert_vm_to_template = apply
    result = execute(flow)
    assert result['status'] == 'needs_reconciliation'
    recover(service, result['operation_id'])
    assert len(fake.calls) == 1
    assert service.operations.get(result['operation_id']).status == 'needs_reconciliation'


def test_running_task_is_later_observed_without_mutation(flow):
    service, fake, _ = flow
    fake.task_result = {'status': 'running'}
    result = execute(flow)
    assert result['status'] == 'running'
    with session_scope() as session:
        item = session.get(OperationRecoveryItemRecord, result['operation_id'])
        item.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    fake.task_result = {'status': 'stopped', 'exitstatus': 'OK'}
    recover(service, result['operation_id'])
    assert len(fake.calls) == 1
    assert service.operations.get(result['operation_id']).status == 'succeeded'


def test_template_volume_read_requires_config_disk_privilege(flow):
    _, fake, _ = flow
    fake.permissions.remove('VM.Config.Disk')
    with pytest.raises(TemplateError) as caught: execute(flow)
    assert caught.value.code == 'VM_TEMPLATE_PERMISSION_DENIED'
    assert not fake.calls
