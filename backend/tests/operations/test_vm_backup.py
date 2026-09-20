import copy
import json
from datetime import datetime, timedelta, timezone
import pytest
from app.backups.contracts import backup_body
from app.backups.domain import BackupError, archives
from app.db.session import session_scope
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.recovery.infrastructure.models import OperationRecoveryItemRecord
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.vm_admission import VmMutationAdmission
from app.operations.vm_backup.application import BackupService
from app.operations.vm_backup.domain import BackupRequest
from app.operations.vm_backup.infrastructure import BackupClient
from app.operations.vm_backup.recovery import BackupRecoveryHandler
from app.proxmox.client import ProxmoxMutationError

ARCHIVE = 'store1:backup/vzdump-qemu-40000-2026_09_19-05_30_00.vma.zst'
OLD = {'volid': ARCHIVE.replace('05_30_00','04_30_00'), 'vmid':40000, 'content':'backup', 'size':500, 'ctime':1000}


class Pve:
    def __init__(self):
        self.config = {'name':'backup-test', 'digest':'a'*40, 'scsi0':'store1:40000/vm-40000-disk-0.qcow2,size=10G',
            'ide2':'store1:40000/vm-40000-cloudinit.qcow2,media=cdrom', 'cipassword':'synthetic-secret'}
        self.vm_permissions = {'VM.Audit','VM.Backup'}
        self.storage_permissions = {'Datastore.Audit','Datastore.AllocateSpace'}
        self.defaults = {'mode':'snapshot', 'remove':1, 'notification-mode':'auto', 'mailto':'private@example.test'}
        self.stores = [{'storage':'store1','type':'nfs','active':1,'enabled':1,'content':'backup,images','avail':30*1024**3}]
        self.rows = [copy.deepcopy(OLD)]
        self.calls, self.power, self.pending, self.snapshots = [], 'stopped', [], [{'name':'current'}]
        self.mode, self.reads = None, 0
        self.upid = 'UPID:node1:0001:0002:0003:vzdump:40000:test@pve!test:'
        self.task_result = {'status':'stopped', 'exitstatus':'OK'}
    def get_vm_permissions(self, **_): return self.vm_permissions
    def get_storage_permissions(self, **_): return self.storage_permissions
    def has_node_task_audit(self, **_): return True
    def get_node_storages(self, **_): return self.stores
    def list_vm_backups(self, **_): return copy.deepcopy(self.rows)
    def get_vm_current_config(self, **_):
        self.reads += 1
        if self.mode == 'drift' and self.reads == 3: self.config['digest'] = 'b'*40
        return dict(self.config)
    def get_vm_status(self, **_): return {'status':self.power}
    def get_vm_pending(self, **_): return self.pending
    def get_vm_snapshots(self, **_): return self.snapshots
    def get_backup_defaults(self, **_): return dict(self.defaults)
    def create_vm_backup(self, *, operation_id, **kwargs):
        self.calls.append({'operation_id':operation_id, **kwargs})
        if self.mode == 'space': raise ProxmoxMutationError('private internal error')
        row = {'volid':ARCHIVE, 'vmid':40000, 'content':'backup', 'size':1000, 'ctime':2000, 'notes':operation_id}
        if self.mode == 'wrong_marker': row['notes'] = 'wrong'
        if self.mode == 'empty_file': row['size'] = 0
        if self.mode == 'old_missing': self.rows = []
        self.rows.append(row)
        if self.mode == 'changed_source': self.config['cores'] = 4
        if self.mode == 'lost': raise ProxmoxMutationError('private internal error')
        if self.mode == 'wrong_task': return self.upid.replace(':40000:', ':40001:')
        return self.upid
    def wait_for_task(self, *, heartbeat, **_):
        heartbeat()
        return self.task_result
    def get_task_status(self, **_): return self.task_result


@pytest.fixture
def flow():
    pve=Pve()
    service=BackupService(client=BackupClient(pve), admission=VmMutationAdmission(recovery_kind='vm_backup_observation'),
        operations=SqlAlchemyOperationStore(), recovery=SqlAlchemyRecoveryStore(), cluster_id='gjallar-mvp')
    before=service.review(node_id='node1',vmid=40000,storage='store1')['observed_before']
    request=BackupRequest(storage_id='store1',idempotency_key='backup-test',expected_name='backup-test',
        expected_review_digest=before['review_digest'],confirmation='40000/backup-test',backup_acknowledged=True)
    return service,pve,request


def execute(flow):
    service,_,request=flow
    return service.execute(node_id='node1',vmid=40000,request=request,actor={'role':'operator','user_id':'test'})


def recover(service, operation_id):
    with session_scope() as session:
        session.get(OperationRecoveryItemRecord,operation_id).lease_expires_at=datetime.now(timezone.utc)-timedelta(seconds=10)
    lease=service.recovery.claim_operation(operation_id,lease_owner='backup-test',lease_seconds=60)
    return BackupRecoveryHandler(operations=service.operations,recovery=service.recovery,service_factory=lambda:service).handle(lease)


def test_backup_confirms_new_archive_preservation_and_one_dispatch(flow):
    service,pve,_=flow
    result=execute(flow)
    assert result['status']=='succeeded'
    assert result['observed_after']['created_archive']['volume_id']==ARCHIVE
    assert result['observed_after']['previous_archives_preserved'] and not result['observed_after']['restore_verified']
    assert execute(flow)['idempotent_replay'] and len(pve.calls)==1
    stored=json.dumps(service.operations.get(result['operation_id']).details)
    assert 'synthetic-secret' not in stored and 'private@example.test' not in stored


@pytest.mark.parametrize('mode',['space','wrong_marker','empty_file','old_missing','changed_source','lost','wrong_task'])
def test_partial_unknown_failure_never_retries_or_cleans_up(flow,mode):
    service,pve,_=flow;pve.mode=mode
    result=execute(flow)
    assert result['status']=='needs_reconciliation' and len(pve.calls)==1
    assert recover(service,result['operation_id']).outcome=='paused'
    execute(flow)
    assert len(pve.calls)==1 and 'private internal error' not in repr(result)


def test_running_task_recovery_only_observes(flow):
    service,pve,_=flow;pve.task_result={'status':'running'}
    result=execute(flow)
    assert result['status']=='running'
    pve.task_result={'status':'stopped','exitstatus':'OK'}
    assert recover(service,result['operation_id']).outcome=='succeeded' and len(pve.calls)==1


@pytest.mark.parametrize('field,value',[('power','running'),('pending',[{'key':'cores','pending':4}]),
    ('snapshots',[{'name':'current'},{'name':'snap'}]),('vm_permissions',{'VM.Audit'}),('storage_permissions',{'Datastore.Audit'})])
def test_source_state_permission_is_required(flow,field,value):
    _,pve,_=flow;setattr(pve,field,value)
    with pytest.raises(BackupError):execute(flow)
    assert not pve.calls


@pytest.mark.parametrize('patch',[{'hookscript':'private-path'},{'scsi0':'store1:40000/vm-40000-disk-0.qcow2,size=10G,backup=0'},
    {'scsi1':'store1:40000/vm-40000-disk-1.qcow2'},{'template':1},{'lock':'backup'},{'hostpci0':'00:00.0'}])
def test_unsupported_config_never_dispatches(flow,patch):
    _,pve,_=flow;pve.config.update(patch)
    with pytest.raises(BackupError):execute(flow)
    assert not pve.calls


@pytest.mark.parametrize('mode',['hook','capacity','storage_type','drift','changed_defaults','confirmation'])
def test_review_precondition_and_second_observation(flow,mode):
    service,pve,request=flow
    if mode=='hook':pve.defaults['script']='private-hook-path'
    if mode=='capacity':pve.stores[0]['avail']=10
    if mode=='storage_type':pve.stores[0]['type']='dir'
    if mode=='drift':pve.mode='drift'
    if mode=='changed_defaults':pve.defaults['compress']='zstd'
    if mode=='confirmation':request=request.model_copy(update={'backup_acknowledged':False})
    with pytest.raises(BackupError):execute((service,pve,request))
    assert not pve.calls


def test_backup_request_has_no_prune_hook_or_notification():
    body=backup_body(40000,'store1','vm-backup-'+'a'*64)
    assert body['remove']==0 and body['all']==0 and body['stop']==0
    assert body['notification-mode']=='legacy-sendmail' and body['mailto']==''
    assert body['fleecing']=='enabled=0' and body['lockwait']==0
    assert not {'script','prune-backups','dumpdir','pool','bwlimit'} & set(body)


@pytest.mark.parametrize('patch',[{'vmid':40001},{'size':0},{'ctime':None},{'content':'images'},
    {'volid':ARCHIVE.replace('40000','40001')},{'volid':ARCHIVE.replace('09_19','19_39')}, {'volid':'../private-path'}])
def test_archive_owner_metadata_are_required(patch):
    with pytest.raises(BackupError):archives([{**OLD,**patch}],storage='store1',vmid=40000)


def test_failed_task_remains_unconfirmed_without_destructive_cleanup(flow):
    service,pve,_=flow
    pve.task_result={'status':'stopped','exitstatus':'ERROR: storage full'}
    result=execute(flow)
    assert result['status']=='needs_reconciliation' and result['failure_code']=='VM_BACKUP_TASK_UNCONFIRMED'
    assert recover(service,result['operation_id']).outcome=='paused'
    assert len(pve.calls)==1 and len(pve.rows)==2


def test_changed_intent_cannot_reuse_a_successful_request_id(flow):
    service,pve,request=flow
    execute(flow)
    with pytest.raises(BackupError) as failure:
        execute((service,pve,request.model_copy(update={'storage_id':'other'})))
    assert failure.value.code=='VM_BACKUP_IDEMPOTENCY_CONFLICT' and len(pve.calls)==1
