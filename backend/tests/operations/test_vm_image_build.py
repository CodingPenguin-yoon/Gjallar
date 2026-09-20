from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest

from app.cloud_images.catalog import ALMA_9, ImageError
from app.cloud_images.contracts import BuildInput, BuildRequest
from app.db.session import session_scope
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.recovery.infrastructure.models import OperationRecoveryItemRecord
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.vm_admission import VmMutationAdmission
from app.operations.vm_image_build.application import ImageBuildService
from app.operations.vm_image_build.recovery import ImageBuildRecoveryHandler


class Client:
    def __init__(self):
        self.calls = []
        self.fail = None
        self.tasks = {}
        self.owner = None
        self.changed = False
        self.partial = False
        self.prechecks = 0
        self.stage_exists = False

    def preflight(self, *, request, **kwargs):
        self.prechecks += 1
        if self.fail == 'recheck' and self.prechecks == 3:
            raise ImageError('RECHECK_FAILED', 'synthetic drift')
        return {'image': ALMA_9.public(), 'name': request.name, 'connection_revision': 'test-revision',
                'storage_id': request.storage_id, 'staging_storage_id': request.staging_storage_id, 'bridge_id': request.bridge_id}

    def assert_upload_absent(self, **kwargs):
        if self.stage_exists: raise ImageError('STAGING_EXISTS', 'exists')

    def mutate(self, stage, vmid):
        self.calls.append(stage)
        if self.fail == stage: raise ImageError('DISPATCH_UNKNOWN', 'lost response')
        kind = {'upload': 'imgcopy', 'create': 'qmcreate', 'template': 'qmtemplate'}[stage]
        upid = f'UPID:node1:0001:0002:0003:{kind}:{vmid}:test@pve!test:'
        self.tasks[upid] = {'status': 'stopped', 'exitstatus': 'OK'}
        if self.fail == stage + '_running': self.tasks[upid] = {'status': 'running', 'exitstatus': ''}
        if self.fail == stage + '_task': self.tasks[upid] = {'status': 'stopped', 'exitstatus': 'ERROR'}
        return upid

    def upload(self, *, operation_id, file, heartbeat, **kwargs):
        self.owner = operation_id
        assert file.read() == b'verified-image-fixture'
        heartbeat()
        return self.mutate('upload', '')

    def observe_staging(self, **kwargs):
        return {'volume_id': 'stage:import/' + self.owner + '.qcow2', 'format': 'qcow2', 'virtual_size_bytes': 10 * 1024 ** 3}

    def create(self, **kwargs): return self.mutate('create', 40000)
    def convert(self, **kwargs): return self.mutate('template', 40000)

    def observe_vm(self, *, converted=False, **kwargs):
        if self.partial and converted: raise ImageError('PARTIAL_CONVERSION', 'not converted')
        return {'vmid': 40000, 'name': 'alma-test', 'template': converted, 'status': 'stopped', 'digest': 'a' * 40,
                'resources_digest': 'sha256:' + 'b' * 64, 'config_fingerprint': 'changed' if self.changed and converted else 'same',
                'volumes': [{'slot': 'scsi0', 'volume_id': f'target:40000/{"base" if converted else "vm"}-40000-disk-0.qcow2', 'size_bytes': 10 * 1024 ** 3}]}

    def task(self, *, upid, heartbeat=None, **kwargs):
        if heartbeat: heartbeat()
        return self.tasks[upid]


@contextmanager
def downloaded(image_id, *, heartbeat):
    assert image_id == ALMA_9.image_id
    heartbeat()
    with BytesIO(b'verified-image-fixture') as file:
        yield file, {'image_id': image_id, 'sha256': ALMA_9.sha256, 'download_bytes': ALMA_9.download_bytes,
                     'virtual_size_bytes': ALMA_9.virtual_size_bytes}


@pytest.fixture
def flow():
    fake = Client()
    service = ImageBuildService(client=fake, admission=VmMutationAdmission(recovery_kind='vm_image_build_observation'),
        operations=SqlAlchemyOperationStore(), recovery=SqlAlchemyRecoveryStore(), cluster_id='gjallar-mvp', downloader=downloaded)
    data = BuildInput(image_id=ALMA_9.image_id, name='alma-test', storage_id='target', staging_storage_id='stage', bridge_id='vmbr1')
    review = service.review(node_id='node1', vmid=40000, request=data)
    request = BuildRequest(**data.model_dump(), idempotency_key='build-test', expected_review_digest=review['review_digest'],
                           confirmation='40000/alma-test', image_build_acknowledged=True)
    return service, fake, request


def execute(flow):
    service, _, request = flow
    return service.execute(node_id='node1', vmid=40000, request=request, actor={'role': 'operator', 'user_id': 'test'})


def recover(service, operation_id):
    with session_scope() as session:
        item = session.get(OperationRecoveryItemRecord, operation_id)
        item.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        item.available_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    lease = service.recovery.claim_operation(operation_id, lease_owner='image-build-test', lease_seconds=60)
    return ImageBuildRecoveryHandler(operations=service.operations, recovery=service.recovery, service_factory=lambda: service).handle(lease)


def test_build_checkpoints_all_stages_and_replays_without_mutation(flow):
    service, fake, _ = flow
    result = execute(flow)
    assert result['status'] == 'succeeded'
    assert fake.calls == ['upload', 'create', 'template']
    assert set(result['stages']) == {'upload', 'create', 'template'}
    assert all(value['task']['exitstatus'] == 'OK' for value in result['stages'].values())
    assert result['source_integrity']['sha256'] == ALMA_9.sha256
    assert result['staging'] and result['observed_after']['template']
    assert execute(flow)['idempotent_replay'] is True
    assert len(fake.calls) == 3


@pytest.mark.parametrize('stage', ['upload', 'create', 'template'])
def test_lost_response_retains_stage_and_never_redispatches(flow, stage):
    service, fake, _ = flow
    fake.fail = stage
    result = execute(flow)
    calls = list(fake.calls)
    assert result['status'] == 'needs_reconciliation' and result['build_stage'] == stage
    assert result['stage_dispatch_state'] == 'dispatching'
    recover(service, result['operation_id'])
    assert fake.calls == calls
    assert service.operations.get(result['operation_id']).status == 'needs_reconciliation'


@pytest.mark.parametrize('stage', ['upload', 'create', 'template'])
def test_running_step_is_observed_but_does_not_start_next_mutation(flow, stage):
    service, fake, _ = flow
    fake.fail = stage + '_running'
    result = execute(flow)
    calls = list(fake.calls)
    assert result['status'] == 'needs_reconciliation'
    upid = result['stages'][stage]['upid']
    fake.tasks[upid] = {'status': 'stopped', 'exitstatus': 'OK'}
    recover(service, result['operation_id'])
    observed = service.operations.get(result['operation_id'])
    assert fake.calls == calls
    assert observed.status == ('succeeded' if stage == 'template' else 'needs_reconciliation')
    if stage != 'template': assert observed.details['failure_code'] == 'IMAGE_BUILD_NEXT_STAGE_NOT_DISPATCHED'


@pytest.mark.parametrize('stage', ['upload', 'create', 'template'])
def test_failed_task_never_advances_or_retries(flow, stage):
    service, fake, _ = flow
    fake.fail = stage + '_task'
    result = execute(flow)
    calls = list(fake.calls)
    recover(service, result['operation_id'])
    assert fake.calls == calls and service.operations.get(result['operation_id']).status == 'needs_reconciliation'


@pytest.mark.parametrize('mode', ['partial', 'changed'])
def test_template_flag_or_config_drift_does_not_pass(flow, mode):
    service, fake, _ = flow
    setattr(fake, mode, True)
    result = execute(flow)
    assert result['status'] == 'needs_reconciliation'
    recover(service, result['operation_id'])
    assert fake.calls == ['upload', 'create', 'template']
    assert service.operations.get(result['operation_id']).status == 'needs_reconciliation'


@pytest.mark.parametrize('patch', [{'image_build_acknowledged': False}, {'confirmation': '40001/alma-test'},
                                  {'expected_review_digest': 'sha256:' + 'f' * 64}])
def test_wrong_confirmation_and_changed_review_do_not_dispatch(flow, patch):
    service, fake, request = flow
    with pytest.raises(ImageError): execute((service, fake, request.model_copy(update=patch)))
    assert not fake.calls


def test_staging_collision_is_blocked_before_any_write(flow):
    _, fake, _ = flow
    fake.stage_exists = True
    with pytest.raises(ImageError) as caught: execute(flow)
    assert caught.value.code == 'STAGING_EXISTS' and caught.value.details['operation_id']
    assert not fake.calls


@pytest.mark.parametrize('field,value', [('build_stage', 'create'), ('stage_dispatch_state', 'dispatching'),
                                       ('stages_digest', 'sha256:' + '0' * 64)])
def test_recovery_rejects_mismatched_stage_evidence(flow, field, value):
    service, fake, _ = flow
    fake.fail = 'template_running'
    result = execute(flow)
    with session_scope() as session:
        row = session.get(OperationRecoveryItemRecord, result['operation_id'])
        row.details = {**row.details, field: value}
    calls = list(fake.calls)
    assert recover(service, result['operation_id']).outcome == 'paused_binding_mismatch'
    assert fake.calls == calls
    assert service.operations.get(result['operation_id']).status == 'needs_reconciliation'


def test_expired_lease_cannot_dispatch_next_stage_or_release_target(flow):
    from app.operations.recovery.domain import RecoveryLeaseLost
    from app.operations.locks.infrastructure.repository import SqlAlchemyDurableTargetLockRepository
    service, fake, _ = flow
    original = fake.upload
    def upload(**kwargs):
        upid = original(**kwargs)
        with session_scope() as session:
            row = session.get(OperationRecoveryItemRecord, kwargs['operation_id'])
            row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        return upid
    fake.upload = upload
    with pytest.raises(RecoveryLeaseLost): execute(flow)
    assert fake.calls == ['upload']
    assert SqlAlchemyDurableTargetLockRepository().current(cluster_id='gjallar-mvp', vmid=40000)
    recover(service, fake.owner)
    assert fake.calls == ['upload']
    assert service.operations.get(fake.owner).status == 'needs_reconciliation'


def test_process_interruption_before_first_mutation_is_blocked_by_recovery(flow):
    from app.operations.locks.infrastructure.repository import SqlAlchemyDurableTargetLockRepository
    service, fake, _ = flow
    @contextmanager
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt('synthetic process interruption')
        yield
    service.downloader = interrupted
    with pytest.raises(KeyboardInterrupt): execute(flow)
    operations = service.operations.list(limit=10)
    operation = operations[0]
    recover(service, operation.operation_id)
    assert service.operations.get(operation.operation_id).status == 'blocked'
    assert SqlAlchemyDurableTargetLockRepository().current(cluster_id='gjallar-mvp', vmid=40000) is None
    assert not fake.calls
