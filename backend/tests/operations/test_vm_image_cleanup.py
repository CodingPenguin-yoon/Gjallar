from types import SimpleNamespace

import pytest
from app.cloud_images.catalog import ALMA_9, ImageError
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.vm_admission import VmMutationAdmission
from app.operations.vm_image_cleanup.application import ImageCleanupService
from app.operations.vm_image_cleanup.domain import CleanupRequest

PARENT = 'vm-image-build-' + 'a' * 64


class Store:
    def __init__(self, parent, real): self.parent, self.real = parent, real
    def get(self, identity): return self.parent if identity == PARENT else self.real.get(identity)
    def __getattr__(self, name): return getattr(self.real, name)


class Client:
    def __init__(self): self.calls, self.removed, self.lost, self.partial = [], False, False, False
    def read(self, *, parent, resource, **kwargs):
        return {'storage_id': 'target' if resource == 'template' else 'stage',
                'deleted_volumes': [{'volume_id': 'owned-volume'}], 'preserved_volumes': []}
    def apply(self, *, before, **kwargs):
        self.calls.append(before['resource'])
        self.removed = not self.partial
        if self.lost: raise ImageError('IMAGE_CLEANUP_DISPATCH_UNKNOWN', 'lost response')
        return 'UPID:node1:1:2:3:' + ('qmdestroy:40000' if before['resource'] == 'template' else 'imgdel:stage') + ':test@pve!test:'
    def task(self, *, heartbeat=None, **kwargs):
        if heartbeat: heartbeat()
        return {'status': 'stopped', 'exitstatus': 'OK'}
    def observe_deletion(self, **kwargs):
        return {'removed': self.removed, 'vmid_unused': self.removed,
                'remaining_volumes': [] if self.removed else ['owned-volume'], 'preservation_unconfirmed': []}


@pytest.fixture
def flow():
    parent = SimpleNamespace(operation_id=PARENT, operation_type='vm_image_build', execution_mode='managed_api', status='succeeded',
        details={'cluster_id': 'gjallar-mvp', 'target': {'node_id': 'node1', 'vmid': 40000, 'name': 'alma-test'},
        'requested': {'image_id': ALMA_9.image_id, 'name': 'alma-test', 'storage_id': 'target', 'staging_storage_id': 'stage',
            'bridge_id': 'vmbr1', 'idempotency_key': 'build', 'expected_review_digest': 'sha256:'+'b'*64,
            'confirmation': '40000/alma-test', 'image_build_acknowledged': True},
        'source_integrity': {'image_id': ALMA_9.image_id, 'sha256': ALMA_9.sha256, 'download_bytes': ALMA_9.download_bytes,
            'virtual_size_bytes': ALMA_9.virtual_size_bytes}, 'observed_after': {'template': True}})
    fake = Client()
    service = ImageCleanupService(client=fake, admission=VmMutationAdmission(recovery_kind='vm_image_cleanup_observation'),
        operations=Store(parent, SqlAlchemyOperationStore()), recovery=Store(SimpleNamespace(status='completed'), SqlAlchemyRecoveryStore()),
        cluster_id='gjallar-mvp')
    return service, fake, parent


def request(service, resource):
    before = service.review(node_id='node1', vmid=40000, parent_operation_id=PARENT, resource=resource)['observed_before']
    return CleanupRequest(parent_operation_id=PARENT, resource=resource, expected_name='alma-test',
        expected_review_digest=before['review_digest'], idempotency_key='cleanup-'+resource,
        confirmation='40000/alma-test/'+resource, cleanup_acknowledged=True)


def run(service, value): return service.execute(node_id='node1', vmid=40000, request=value, actor={'role': 'operator'})


@pytest.mark.parametrize('resource', ['template', 'source'])
def test_owned_cleanup_is_one_task_and_same_key_replay(flow, resource):
    service, fake, _ = flow
    value = request(service, resource)
    assert run(service, value)['status'] == 'succeeded'
    assert run(service, value)['idempotent_replay'] is True
    assert fake.calls == [resource]


@pytest.mark.parametrize('mode', ['lost', 'partial'])
def test_uncertain_cleanup_keeps_lock_and_never_reissues(flow, mode):
    service, fake, _ = flow
    setattr(fake, mode, True)
    value = request(service, 'source')
    assert run(service, value)['status'] == 'needs_reconciliation'
    assert run(service, value)['idempotent_replay'] is True
    assert fake.calls == ['source']


@pytest.mark.parametrize('mode', ['unfinished', 'wrong_cluster', 'different_image'])
def test_parent_build_must_prove_completed_ownership(flow, mode):
    service, fake, parent = flow
    if mode == 'unfinished': parent.status = 'needs_reconciliation'
    if mode == 'wrong_cluster': parent.details['cluster_id'] = 'other'
    if mode == 'different_image': parent.details['source_integrity']['sha256'] = 'f'*64
    with pytest.raises(ImageError): request(service, 'template')
    assert not fake.calls


def test_cleanup_requires_resource_specific_confirmation(flow):
    service, fake, _ = flow
    value = request(service, 'source').model_copy(update={'confirmation': '40000/alma-test/template'})
    with pytest.raises(ImageError): run(service, value)
    assert not fake.calls


@pytest.mark.parametrize('resource', ['source', 'template'])
def test_cleanup_recovery_observes_completion_without_delete_again(flow, resource):
    from datetime import datetime, timedelta, timezone
    from app.db.session import session_scope
    from app.operations.recovery.infrastructure.models import OperationRecoveryItemRecord
    from app.operations.vm_image_cleanup.recovery import ImageCleanupRecoveryHandler
    service, fake, _ = flow
    original_task = fake.task
    fake.task = lambda **kwargs: {'status': 'running', 'exitstatus': ''}
    result = run(service, request(service, resource))
    assert result['status'] == 'running'
    with session_scope() as session:
        row = session.get(OperationRecoveryItemRecord, result['operation_id'])
        row.lease_expires_at = row.available_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    fake.task = original_task
    lease = service.recovery.claim_operation(result['operation_id'], lease_owner='cleanup-test', lease_seconds=60)
    handler = ImageCleanupRecoveryHandler(operations=service.operations, recovery=service.recovery, service_factory=lambda: service)
    assert handler.handle(lease).outcome == 'succeeded'
    assert fake.calls == [resource]


def test_cleanup_expired_lease_cannot_record_success_or_release(flow):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from app.db.session import session_scope
    from app.operations.recovery.domain import RecoveryLeaseLost
    from app.operations.recovery.infrastructure.models import OperationRecoveryItemRecord
    from app.operations.locks.infrastructure.repository import SqlAlchemyDurableTargetLockRepository
    service, fake, _ = flow
    original = fake.apply
    def apply(**kwargs):
        result = original(**kwargs)
        with session_scope() as session:
            row = session.scalar(select(OperationRecoveryItemRecord))
            row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        return result
    fake.apply = apply
    with pytest.raises(RecoveryLeaseLost): run(service, request(service, 'source'))
    assert fake.calls == ['source']
    assert SqlAlchemyDurableTargetLockRepository().current(cluster_id='gjallar-mvp', vmid=40000)


@pytest.mark.parametrize('reference', ['UPID:node1:1:2:3:imgdel:other:test@pve!test:',
                                      'UPID:node1:1:2:3:qmdestroy:40000:test@pve!test:',
                                      'UPID:node2:1:2:3:imgdel:stage:test@pve!test:'])
def test_cleanup_task_is_bound_to_resource_kind_and_exact_storage(reference):
    from app.operations.vm_image_cleanup.domain import task_reference
    with pytest.raises(ImageError): task_reference(reference, node_id='node1', vmid=40000, resource='source', storage='stage')
