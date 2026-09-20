import copy
import json
from datetime import datetime, timedelta, timezone

import pytest
from app.backups.archive import parse_archive_config
from app.backups.domain import BackupError
from app.db.session import session_scope
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.locks.infrastructure.repository import SqlAlchemyDurableTargetLockRepository
from app.operations.recovery.infrastructure.models import OperationRecoveryItemRecord
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.vm_admission import VmMutationAdmission
from app.operations.vm_restore.application import RestoreService
from app.operations.vm_restore.domain import RestoreRequest
from app.operations.vm_restore.infrastructure import RestoreClient
from app.operations.vm_restore.recovery import RestoreRecoveryHandler
from app.proxmox.client import ProxmoxMutationError

ARCHIVE = 'nfs:backup/vzdump-qemu-40000-2026_09_19-05_00_00.vma.zst'
RAW = '''name: source-vm
cores: 2
memory: 2048
scsi0: nfs:40000/vm-40000-disk-0.qcow2,size=10G
ide2: nfs:40000/vm-40000-cloudinit.qcow2,media=cdrom
net0: virtio=02:00:00:00:00:01,bridge=vmbr1,firewall=1
onboot: 1
agent: 1
cipassword: synthetic-password
sshkeys: synthetic-key
smbios1: uuid=11111111-1111-1111-1111-111111111111
vmgenid: 22222222-2222-2222-2222-222222222222
#qmdump#map:scsi0:drive-scsi0:nfs:qcow2:
'''


class Pve:
    def __init__(self):
        config, _ = parse_archive_config(RAW, source_vmid=40000)
        self.configs = {40000: {**config, 'digest':'a'*40}}
        self.archive_config = RAW
        self.stores = [{'storage':key,'type':'nfs','active':1,'enabled':1,'content':'images,backup','avail':30*1024**3} for key in ('nfs','target')]
        self.rows = [{'volid':ARCHIVE,'vmid':40000,'size':1000,'ctime':1000,'content':'backup'}]
        self.network = {'pending_changes':False,'interfaces':[{'iface':'vmbr1','type':'bridge','active':1}]}
        self.vm_permissions = {'VM.Audit','VM.Backup','VM.Allocate','VM.Config.Disk','VM.PowerMgmt','VM.GuestAgent.Audit'}
        self.storage_permissions = {'Datastore.Audit','Datastore.AllocateSpace'}
        self.bridge_permissions = {'SDN.Use'}
        self.calls, self.reads, self.mode = [], 0, None
        self.task_result = {'status':'stopped','exitstatus':'OK'}
        self.upid = 'UPID:node1:0001:0002:0003:qmrestore:40001:test@pve!test:'
    def get_vm_permissions(self, **_): return self.vm_permissions
    def get_storage_permissions(self, **_): return self.storage_permissions
    def get_bridge_permissions(self, **_): return self.bridge_permissions
    def has_node_task_audit(self, **_): return True
    def get_node_storages(self, **_): return self.stores
    def get_node_network_snapshot(self, **_): return self.network
    def list_vm_backups(self, **_): return copy.deepcopy(self.rows)
    def get_backup_config(self, **_): return self.archive_config
    def assert_vmid_unused(self, *, vmid):
        if vmid in self.configs: raise ProxmoxMutationError('private existence detail')
        return True
    def get_vm_current_config(self, *, vmid, **_):
        self.reads += 1
        if self.mode == 'drift' and self.reads == 3: self.configs[40000]['digest'] = 'b'*40
        if vmid not in self.configs: raise ProxmoxMutationError('private missing detail')
        return dict(self.configs[vmid])
    def get_vm_status(self, *, vmid, **_):
        return {'status':'running' if self.mode == 'running' and vmid == 40001 else 'stopped'}
    def get_vm_pending(self, **_): return []
    def get_vm_snapshots(self, **_): return [{'name':'current'}]
    def get_volume_info(self, *, volume, **_):
        return {'size': (1 if self.mode == 'short_disk' else 10*1024**3) if '-disk-' in volume else 4*1024**2,'format':'qcow2'}
    def restore_vm_backup(self, **kwargs):
        self.calls.append(kwargs)
        target = {**self.configs[40000], 'name':kwargs['name'], 'description':kwargs['operation_id'], 'digest':'c'*40,
            'onboot':0, 'scsi0':'target:40001/vm-40001-disk-1.qcow2,size=10G',
            'ide2':'target:40001/vm-40001-cloudinit.qcow2,media=cdrom',
            'net0':f"virtio={kwargs['mac']},bridge={kwargs['bridge']},link_down=1,firewall={kwargs['firewall']}",
            'smbios1':'uuid=33333333-3333-3333-3333-333333333333', 'vmgenid':'44444444-4444-4444-4444-444444444444'}
        if self.mode == 'link_up': target['net0'] = target['net0'].replace('link_down=1','link_down=0')
        if self.mode == 'autostart': target['onboot'] = 1
        if self.mode == 'wrong_marker': target['description'] = 'different-operation'
        if self.mode == 'wrong_disk': target['scsi0'] = target['scsi0'].replace('40001','40002')
        if self.mode == 'wrong_storage': target['scsi0'] = target['scsi0'].replace('target:','nfs:')
        if self.mode == 'wrong_hardware': target['cores'] = 8
        if self.mode == 'same_uuid': target['smbios1'] = self.configs[40000]['smbios1']
        if self.mode == 'same_generation': target['vmgenid'] = self.configs[40000]['vmgenid']
        self.configs[40001] = target
        if self.mode == 'source_changed': self.configs[40000]['cores'] = 8
        if self.mode == 'archive_changed': self.rows[0]['size'] = 2000
        if self.mode == 'archive_config_changed': self.archive_config = RAW.replace('memory: 2048','memory: 4096')
        if self.mode == 'archive_missing': self.rows = []
        if self.mode == 'lost': raise ProxmoxMutationError('private dispatch detail')
        return self.upid.replace(':40001:', ':40000:') if self.mode == 'wrong_task' else self.upid
    def wait_for_task(self, *, heartbeat, **_):
        heartbeat()
        return self.task_result
    def get_task_status(self, **_): return self.task_result


@pytest.fixture
def flow():
    pve = Pve()
    service = RestoreService(client=RestoreClient(pve), admission=VmMutationAdmission(recovery_kind='vm_restore_observation'),
        operations=SqlAlchemyOperationStore(), recovery=SqlAlchemyRecoveryStore(), cluster_id='gjallar-mvp')
    before = service.review(node_id='node1',vmid=40000,archive=ARCHIVE,new_vmid=40001,storage_id='target',bridge_id='vmbr1')['observed_before']
    request = RestoreRequest(archive=ARCHIVE,new_vmid=40001,name='restored',storage_id='target',bridge_id='vmbr1',
        idempotency_key='restore-test',expected_name='source-vm',expected_review_digest=before['review_digest'],
        confirmation='40000/40001/restored',isolation_acknowledged=True)
    return service,pve,request


def execute(flow):
    service, _, request = flow
    return service.execute(node_id='node1',vmid=40000,request=request,actor={'role':'operator','user_id':'test'})


def recover(service, operation_id):
    with session_scope() as session:
        session.get(OperationRecoveryItemRecord, operation_id).lease_expires_at = datetime.now(timezone.utc)-timedelta(seconds=10)
    lease = service.recovery.claim_operation(operation_id,lease_owner='restore-test',lease_seconds=60)
    return RestoreRecoveryHandler(operations=service.operations,recovery=service.recovery,service_factory=lambda:service).handle(lease)


def test_restore_preserves_original_and_archive_and_releases_both_locks(flow):
    service,pve,_=flow
    result=execute(flow)
    assert result['status']=='succeeded'
    after=result['observed_after']
    assert after['destination']['onboot_disabled'] and after['destination']['nic']['link_down']=='1'
    assert not after['boot_verified'] and not after['guest_access_verified']
    assert result['target']['vmid']==40001 and after['source']['vmid']==40000
    assert execute(flow)['idempotent_replay'] and len(pve.calls)==1
    stored=json.dumps(service.operations.get(result['operation_id']).details)
    assert 'synthetic-' not in stored
    locks=SqlAlchemyDurableTargetLockRepository()
    assert all(locks.current(cluster_id='gjallar-mvp',vmid=vmid) is None for vmid in (40000,40001))


@pytest.mark.parametrize('mode',['link_up','autostart','wrong_marker','wrong_disk','wrong_storage','wrong_hardware',
    'same_uuid','same_generation','source_changed','archive_changed','archive_config_changed','archive_missing',
    'lost','wrong_task','short_disk','running'])
def test_partial_or_uncertain_result_preserves_locks_and_never_reposts_or_deletes(flow,mode):
    service,pve,_=flow;pve.mode=mode
    result=execute(flow)
    assert result['status']=='needs_reconciliation'
    assert recover(service,result['operation_id']).outcome=='paused'
    assert execute(flow)['idempotent_replay'] and len(pve.calls)==1
    assert 'private' not in repr(result)
    locks=SqlAlchemyDurableTargetLockRepository()
    assert all(locks.current(cluster_id='gjallar-mvp',vmid=vmid).status=='reconciliation_required' for vmid in (40000,40001))


def test_running_task_completes_through_read_only_recovery(flow):
    service,pve,_=flow;pve.task_result={'status':'running'}
    result=execute(flow)
    assert result['status']=='running'
    pve.task_result={'status':'stopped','exitstatus':'OK'}
    assert recover(service,result['operation_id']).outcome=='succeeded' and len(pve.calls)==1


@pytest.mark.parametrize('failure',['exists','drift','permission','storage_permission','bridge_permission','pending_network',
    'bridge_inactive','space','archive_missing','archive_unsafe','different_source','confirmation'])
def test_review_and_second_precheck_block_without_dispatch(flow,failure):
    service,pve,request=flow
    if failure=='exists':pve.configs[40001]={'name':'preserve-existing'}
    if failure=='drift':pve.mode='drift'
    if failure=='permission':pve.vm_permissions.remove('VM.Config.Disk')
    if failure=='storage_permission':pve.storage_permissions.remove('Datastore.AllocateSpace')
    if failure=='bridge_permission':pve.bridge_permissions.clear()
    if failure=='pending_network':pve.network['pending_changes']=True
    if failure=='bridge_inactive':pve.network['interfaces'][0]['active']=0
    if failure=='space':pve.stores[1]['avail']=1
    if failure=='archive_missing':pve.rows=[]
    if failure=='archive_unsafe':pve.archive_config+='hookscript: private-path\n'
    if failure=='different_source':request=request.model_copy(update={'archive':ARCHIVE.replace('40000','40002')})
    if failure=='confirmation':request=request.model_copy(update={'isolation_acknowledged':False})
    with pytest.raises(BackupError):execute((service,pve,request))
    assert not pve.calls


def test_failed_task_never_claims_restore_success(flow):
    service,pve,_=flow;pve.task_result={'status':'stopped','exitstatus':'ERROR: interrupted'}
    result=execute(flow)
    assert result['status']=='needs_reconciliation' and result['failure_code']=='VM_RESTORE_TASK_UNCONFIRMED'
    assert recover(service,result['operation_id']).outcome=='paused' and len(pve.calls)==1


def test_same_request_key_with_different_restore_target_is_conflict(flow):
    service,pve,request=flow
    execute(flow)
    with pytest.raises(BackupError) as error:
        execute((service,pve,request.model_copy(update={'new_vmid':40002})))
    assert error.value.code=='VM_RESTORE_IDEMPOTENCY_CONFLICT' and len(pve.calls)==1


@pytest.mark.parametrize('running,agent_response,agent_status', [(False,None,'not_run'),(True,{'result':[]},'passed'),(True,None,'unavailable')])
def test_report_separates_power_agent_and_access(flow,running,agent_response,agent_status):
    from app.operations.vm_restore.report import restore_report
    service,pve,_=flow
    result=execute(flow)
    operation=service.operations.get(result['operation_id'])
    payload={'operation':{'operation_id':operation.operation_id,'operation_type':operation.operation_type,
        'execution_mode':'managed_api','target_type':'proxmox_vm','target_id':operation.target_id,
        'status':operation.status,'details':operation.details}}
    calls=[]
    def agent(**kwargs):calls.append(kwargs);return agent_response
    pve.get_guest_network_interfaces=agent
    if running:pve.mode='running'
    report=restore_report(payload,service.client)
    checks={row['name']:row['status'] for row in report['checks']}
    assert checks['restore_task']=='passed' and checks['restored_configuration']=='passed'
    assert checks['power']==('running' if running else 'stopped') and checks['guest_agent']==agent_status
    assert len(calls)==int(running) and len(pve.calls)==1
    assert report['external_access_verified'] is False and report['automatic_boot'] is False
    assert 'synthetic' not in json.dumps(report)
    payload['coordination_incomplete']=True
    with pytest.raises(BackupError):restore_report(payload,service.client)


def test_report_does_not_query_agent_on_replaced_or_connected_target(flow):
    from app.operations.vm_restore.report import restore_report
    service,pve,_=flow
    result=execute(flow);operation=service.operations.get(result['operation_id'])
    payload={'operation':{'operation_id':operation.operation_id,'operation_type':'vm_restore','execution_mode':'managed_api',
        'target_type':'proxmox_vm','target_id':operation.target_id,'status':'succeeded','details':operation.details}}
    pve.mode='running'
    pve.configs[40001]['net0']=pve.configs[40001]['net0'].replace('link_down=1','link_down=0')
    def agent(**_):raise AssertionError('Agent of changed guest must not be queried')
    pve.get_guest_network_interfaces=agent
    pve.rows=[]
    report=restore_report(payload,service.client)
    checks={row['name']:row['status'] for row in report['checks']}
    assert checks['archive_preserved']=='unavailable' and checks['source_preserved']=='passed'
    assert checks['network_isolation']=='not_verified' and checks['restored_configuration']=='not_verified'
    assert checks['guest_agent']=='not_run'
