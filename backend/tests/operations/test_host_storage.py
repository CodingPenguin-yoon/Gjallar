from datetime import datetime, timedelta, timezone
import pytest
from pydantic import ValidationError
from app.db.session import session_scope
from app.operations.core.domain import verify_event_chain
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.host_config.admission import HostConfigurationAdmission
from app.operations.host_config.infrastructure import ConfigurationLockRepository
from app.operations.host_config.recovery import HostConfigurationRecoveryHandler
from app.operations.host_storage.application import StorageService
from app.operations.host_storage.domain import StorageChange, StorageRequest, StorageError, mutation_body
from app.operations.host_storage.infrastructure import StorageClient
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.recovery.infrastructure.models import OperationRecoveryItemRecord
from app.proxmox.client import ProxmoxMutationError


class FakeClient:
    def __init__(self):
        self.config = {'storage':'test-dir','type':'dir','path':'/mnt/old','content':'iso','digest':'a'*40,
                       'preallocation':'metadata','is_mountpoint':'/mnt'}
        self.calls = []
        self.active = 1
        self.lost = False
        self.drift = False
        self.reads = 0
        self.corrupt_after = False

    def list_nodes(self): return [{'node':'node1','status':'online'}]
    def get_storage_configuration_permissions(self): return {'Datastore.Allocate'}
    def get_storage_permissions(self, **kwargs): return {'Datastore.Allocate','Datastore.Audit'}
    def list_storage_configurations(self): return [self.config] if self.config else []
    def get_storage_configuration(self, **kwargs):
        self.reads += 1
        if self.drift and self.reads == 3: self.config['digest'] = 'c'*40
        return dict(self.config)
    def get_node_storages(self, **kwargs):
        return [{'storage':'test-dir','type':'dir','active':self.active,'enabled':1}]
    def configure_directory_storage(self, *, node, storage, change, before):
        body = mutation_body(change,node_id=node,storage_id=storage,before=before)
        self.calls.append(body)
        if change.mode == 'update': assert body['digest'] == self.config['digest']
        self.config = {**(self.config or {}), **body, 'storage':storage, 'digest':'b'*40}
        if self.corrupt_after: self.config['preallocation'] = 'off'
        if self.lost: raise ProxmoxMutationError('synthetic-private-value')
        return {'storage':storage,'type':'dir'}


@pytest.fixture
def flow():
    fake = FakeClient()
    service = StorageService(client=StorageClient(fake),admission=HostConfigurationAdmission(),
        operations=SqlAlchemyOperationStore(),recovery=SqlAlchemyRecoveryStore(),cluster_id='gjallar-mvp')
    return service,fake


def request(service, **patch):
    change = StorageChange(mode='update',content=['iso','images'],**patch)
    plan = service.review(node_id='node1',storage_id='test-dir',change=change)
    return StorageRequest(**change.model_dump(),idempotency_key='test-storage',expected_review_digest=plan['review_digest'],
        confirmation=plan['confirmation'],acknowledge_cluster_impact=True)


def execute(service, value):
    return service.execute(node_id='node1',storage_id='test-dir',request=value,actor={'user_id':'admin','role':'admin'})


def recover(service, operation_id):
    with session_scope() as session:
        row = session.get(OperationRecoveryItemRecord,operation_id)
        row.lease_expires_at = datetime.now(timezone.utc)-timedelta(seconds=10)
    lease = service.recovery.claim_operation(operation_id,lease_owner='test-recovery',lease_seconds=60)
    return HostConfigurationRecoveryHandler(operation_type='host_storage',operations=service.operations,recovery=service.recovery,
        service_factory=lambda:service,error_type=StorageError).handle(lease)


def test_update_preserves_original_config_and_verifies_activation(flow):
    service,fake = flow
    value = request(service)
    result = execute(service,value)
    assert result['status'] == 'succeeded'
    assert result['review']['desired']['all_nodes'] is True
    assert result['observed_after']['active'] is True and result['observed_after']['content_directories_verified'] is False
    assert fake.config['path'] == '/mnt/old' and fake.config['preallocation'] == 'metadata'
    assert fake.calls == [{'content':'images,iso','disable':0,'create-base-path':0,'create-subdirs':0,'digest':'a'*40}]
    assert ConfigurationLockRepository().current(cluster_id='gjallar-mvp') is None
    assert verify_event_chain(service.operations.list_events(result['operation_id']))
    assert execute(service,value)['idempotent_replay'] is True and len(fake.calls) == 1
    with pytest.raises(StorageError): execute(service,value.model_copy(update={'enabled':False}))


def test_create_uses_exact_new_id_existing_path_and_no_directory_creation(flow):
    service,fake = flow
    fake.config = None
    change = StorageChange(mode='create',path='/mnt/existing',content=['images'])
    plan = service.review(node_id='node1',storage_id='test-dir',change=change)
    value = StorageRequest(**change.model_dump(),idempotency_key='create',expected_review_digest=plan['review_digest'],
        confirmation=plan['confirmation'],acknowledge_cluster_impact=True)
    result = execute(service,value)
    assert result['status'] == 'succeeded'
    assert fake.calls == [{'storage':'test-dir','type':'dir','path':'/mnt/existing','content':'images','nodes':'node1',
                          'shared':0,'disable':0,'create-base-path':0,'create-subdirs':0}]


def test_disabled_configuration_does_not_claim_unmount_or_activation(flow):
    service,fake = flow
    result = execute(service,request(service,enabled=False))
    assert result['status'] == 'succeeded'
    assert result['observed_after']['active'] is None and result['observed_after']['activation_checked'] is False
    assert fake.calls[0]['disable'] == 1


@pytest.mark.parametrize('condition',['lost','offline','preserved_drift'])
def test_uncertain_result_keeps_lock_and_get_only_recovery_never_rewrites(flow,condition):
    service,fake = flow
    value = request(service)
    if condition == 'lost': fake.lost = True
    if condition == 'offline': fake.active = 0
    if condition == 'preserved_drift': fake.corrupt_after = True
    result = execute(service,value)
    assert result['status'] == 'needs_reconciliation' and 'synthetic-private-value' not in str(result)
    assert ConfigurationLockRepository().current(cluster_id='gjallar-mvp') is not None
    assert recover(service,result['operation_id']).outcome == 'paused'
    assert len(fake.calls) == 1
    if condition == 'offline':
        fake.active = 1
        assert recover(service,result['operation_id']).outcome == 'succeeded'
        assert len(fake.calls) == 1


def test_change_after_admission_blocks_without_write(flow):
    service,fake = flow
    value = request(service)
    fake.drift = True
    with pytest.raises(StorageError) as failure: execute(service,value)
    assert failure.value.code == 'HOST_STORAGE_STATE_CHANGED'
    assert fake.calls == [] and service.operations.list()[0].status == 'blocked'
    assert ConfigurationLockRepository().current(cluster_id='gjallar-mvp') is None


def test_interruption_before_dispatch_can_only_release_without_mutation(flow,monkeypatch):
    service,fake=flow
    value=request(service)
    original=service.admission.prepare
    def interrupted(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('synthetic process interruption')
    monkeypatch.setattr(service.admission,'prepare',interrupted)
    with pytest.raises(RuntimeError): execute(service,value)
    operation=service.operations.list()[0]
    assert recover(service,operation.operation_id).outcome=='blocked'
    assert fake.calls==[] and ConfigurationLockRepository().current(cluster_id='gjallar-mvp') is None


def test_recovery_rejects_changed_target_before_any_proxmox_read(flow):
    service,fake=flow
    fake.active=0
    result=execute(service,request(service))
    with session_scope() as session:
        row=session.get(OperationRecoveryItemRecord,result['operation_id'])
        row.details={**row.details,'target':{'node_id':'other','storage_id':'test-dir'}}
    count=fake.reads
    assert recover(service,result['operation_id']).outcome=='paused'
    assert fake.reads==count and len(fake.calls)==1
    assert ConfigurationLockRepository().current(cluster_id='gjallar-mvp') is not None


@pytest.mark.parametrize('patch', [{'type':'nfs'},{'nodes':'other'},{'digest':'invalid'},{'path':'/mnt/../other'},
    {'shared':'unknown'},{'content':'invalid'}])
def test_unsupported_observation_is_not_a_change_plan(flow,patch):
    service,fake = flow
    fake.config.update(patch)
    with pytest.raises(StorageError): request(service)
    assert not fake.calls and not service.operations.list()


@pytest.mark.parametrize('patch',[{'path':'/new'},{'content':['command']},{'enabled':'yes'},{'delete':'path'}])
def test_update_input_cannot_change_paths_or_send_raw_options(patch):
    with pytest.raises(ValidationError): StorageChange.model_validate({'mode':'update','content':['images'],**patch})


@pytest.mark.parametrize('path',['/','relative','/mnt//new','/mnt/../new','/mnt/./new','/mnt/new/','/mnt/new;id'])
def test_new_directory_path_requires_exact_absolute_identity(path):
    with pytest.raises(ValidationError): StorageChange(mode='create',path=path,content=['images'])
