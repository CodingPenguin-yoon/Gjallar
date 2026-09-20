import copy
import json
from datetime import datetime, timedelta, timezone
import pytest
from app.db.session import session_scope
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.recovery.infrastructure.models import OperationRecoveryItemRecord
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.vm_admission import VmMutationAdmission
from app.operations.vm_migrate.application import MigrateService
from app.operations.vm_migrate.domain import MigrateError, MigrateRequest, request_allowed, request_body
from app.operations.vm_migrate.infrastructure import MigrateClient
from app.operations.vm_migrate.recovery import MigrateRecoveryHandler
from app.proxmox.client import ProxmoxMutationError


class Pve:
    def __init__(self):
        self.config={'name':'move-test','digest':'a'*40,'cores':2,'memory':2048,'onboot':0,
            'scsi0':'nfs:40000/vm-40000-disk-0.qcow2,size=10G','ide2':'nfs:40000/vm-40000-cloudinit.qcow2,media=cdrom',
            'net0':'virtio=02:00:00:00:00:01,bridge=vmbr1,firewall=1','cipassword':'synthetic-secret'}
        self.status={'status':'stopped','ha':{'managed':0}}
        self.pending=[];self.snapshots=[{'name':'current'}]
        self.vm_permissions={'VM.Audit','VM.Migrate','VM.Config.Disk'}
        self.storage_permissions={'Datastore.Audit'};self.bridge_permissions={'SDN.Use'}
        self.nodes=[{'node':key,'status':'online'} for key in ('node1','node2')]
        self.node_status={node['node']:{'pveversion':'pve-manager/9.0.11/build','cpuinfo':{'model':'same-cpu'}} for node in self.nodes}
        self.stores={node['node']:[{'storage':'nfs','type':'nfs','shared':1,'active':1,'enabled':1,'content':'images'}] for node in self.nodes}
        self.networks={node['node']:{'pending_changes':False,'interfaces':[{'iface':'vmbr1','type':'bridge','active':1}]} for node in self.nodes}
        self.precondition={'running':0,'allowed_nodes':['node2'],'not_allowed_nodes':{'node2':{}},'local_disks':[],
            'local_resources':[],'mapped-resources':[],'mapped-resource-info':{}}
        self.resources=[{'vmid':40000,'type':'qemu','node':'node1'}]
        self.calls=[];self.reads=0;self.mode=None
        self.upid='UPID:node1:0001:0002:0003:qmigrate:40000:test@pve!test:'
        self.task_result={'status':'stopped','exitstatus':'OK'}
    def get_vm_permissions(self,**_):return self.vm_permissions
    def get_storage_permissions(self,**_):return self.storage_permissions
    def get_bridge_permissions(self,**_):return self.bridge_permissions
    def has_node_task_audit(self,**_):return True
    def list_nodes(self):return self.nodes
    def get_node_status(self,*,node):return self.node_status[node]
    def get_node_storages(self,*,node):return self.stores[node]
    def get_node_network_snapshot(self,*,node):return self.networks[node]
    def list_vm_resources(self):return self.resources
    def get_vm_migration_preconditions(self,**_):return self.precondition
    def get_vm_current_config(self,**_):
        self.reads+=1
        if self.mode=='drift' and self.reads==3:self.config['digest']='b'*40
        return dict(self.config)
    def get_vm_status(self,**_):return self.status
    def get_vm_pending(self,**_):return self.pending
    def get_vm_snapshots(self,**_):return self.snapshots
    def get_volume_info(self,*,node,volume,**_):
        size=10*1024**3 if '-disk-' in volume else 4*1024**2
        if self.mode=='wrong_volume' and self.calls and node=='node2':size+=1
        return {'size':size,'format':'qcow2'}
    def migrate_vm_reviewed(self,**kwargs):
        self.calls.append(kwargs);self.resources[0]['node']='node2';self.config['digest']='c'*40
        if self.mode=='source_location':self.resources[0]['node']='node1'
        if self.mode=='third_location':self.resources[0]['node']='node3'
        if self.mode=='duplicate_location':self.resources.append({'vmid':40000,'type':'qemu','node':'node1'})
        if self.mode=='changed_config':self.config['cores']=4
        if self.mode=='running':self.status['status']='running'
        if self.mode=='changed_bridge':self.networks['node2']['interfaces'][0]['comments']='changed'
        if self.mode=='lost':raise ProxmoxMutationError('private transport detail')
        return self.upid.replace('node1','node2') if self.mode=='wrong_task' else self.upid
    def wait_for_task(self,*,heartbeat,**_):heartbeat();return self.task_result
    def get_task_status(self,**_):return self.task_result


@pytest.fixture
def flow():
    pve=Pve();service=MigrateService(client=MigrateClient(pve),admission=VmMutationAdmission(recovery_kind='vm_migrate_observation'),
        operations=SqlAlchemyOperationStore(),recovery=SqlAlchemyRecoveryStore(),cluster_id='gjallar-mvp')
    before=service.review(node_id='node1',vmid=40000,destination_node='node2')['observed_before']
    request=MigrateRequest(destination_node='node2',idempotency_key='migrate-test',expected_name='move-test',
        expected_review_digest=before['review_digest'],confirmation='40000/move-test/node1->node2',migration_acknowledged=True)
    return service,pve,request


def execute(flow):
    service,_,request=flow
    return service.execute(node_id='node1',vmid=40000,request=request,actor={'role':'operator','user_id':'test'})


def recover(service,operation_id):
    with session_scope() as session:
        session.get(OperationRecoveryItemRecord,operation_id).lease_expires_at=datetime.now(timezone.utc)-timedelta(seconds=10)
    lease=service.recovery.claim_operation(operation_id,lease_owner='migrate-test',lease_seconds=60)
    return MigrateRecoveryHandler(operations=service.operations,recovery=service.recovery,service_factory=lambda:service).handle(lease)


def test_migration_confirms_unique_destination_and_unchanged_vm_volume_without_boot(flow):
    service,pve,_=flow
    result=execute(flow)
    assert result['status']=='succeeded' and result['observed_after']['node_id']=='node2'
    assert result['target']['node_id']=='node1' and result['observed_after']['source_location_absent']
    assert result['observed_after']['boot_verified'] is False
    assert execute(flow)['idempotent_replay'] and len(pve.calls)==1
    assert 'synthetic-secret' not in json.dumps(service.operations.get(result['operation_id']).details)


@pytest.mark.parametrize('mode',['source_location','third_location','duplicate_location','changed_config','running','changed_bridge','lost','wrong_task','wrong_volume'])
def test_unknown_partial_or_mismatching_migration_never_retries_or_rolls_back(flow,mode):
    service,pve,_=flow;pve.mode=mode
    result=execute(flow)
    assert result['status']=='needs_reconciliation'
    assert recover(service,result['operation_id']).outcome=='paused'
    assert execute(flow)['idempotent_replay'] and len(pve.calls)==1
    assert 'private transport detail' not in repr(result)


def test_running_task_recovery_keeps_source_node_binding_after_location_changes(flow):
    service,pve,_=flow;pve.task_result={'status':'running'}
    result=execute(flow)
    assert result['status']=='running'
    pve.task_result={'status':'stopped','exitstatus':'OK'}
    assert recover(service,result['operation_id']).outcome=='succeeded' and len(pve.calls)==1


@pytest.mark.parametrize('failure',['drift','running','ha','ha_unknown','permission','storage_permission','bridge_permission','offline',
    'version','cpu','local_storage','inactive_storage','pending_network','missing_bridge','local_disk','local_resource','mapped',
    'ha_dependency','not_allowed','pending_vm','snapshot','autostart','host_device','extra_nic','vlan','confirmation'])
def test_preconditions_block_unsafe_scope_or_drift_without_mutation(flow,failure):
    service,pve,request=flow
    if failure=='drift':pve.mode='drift'
    if failure=='running':pve.status['status']='running'
    if failure=='ha':pve.status['ha']['managed']=1
    if failure=='ha_unknown':pve.status.pop('ha')
    if failure=='permission':pve.vm_permissions.remove('VM.Migrate')
    if failure=='storage_permission':pve.storage_permissions.clear()
    if failure=='bridge_permission':pve.bridge_permissions.clear()
    if failure=='offline':pve.nodes[1]['status']='offline'
    if failure=='version':pve.node_status['node2']['pveversion']='pve-manager/9.1/different'
    if failure=='cpu':pve.node_status['node2']['cpuinfo']['model']='other-cpu'
    if failure=='local_storage':pve.stores['node2'][0]['shared']=0
    if failure=='inactive_storage':pve.stores['node2'][0]['active']=0
    if failure=='pending_network':pve.networks['node2']['pending_changes']=True
    if failure=='missing_bridge':pve.networks['node2']['interfaces']=[]
    if failure=='local_disk':pve.precondition['local_disks']=[{'volid':'local:disk'}]
    if failure=='local_resource':pve.precondition['local_resources']=['hostpci0']
    if failure=='mapped':pve.precondition['mapped-resource-info']={'hostpci0':{}}
    if failure=='ha_dependency':pve.precondition['dependent-ha-resources']=['vm:40002']
    if failure=='not_allowed':pve.precondition['not_allowed_nodes']['node2']={'unavailable_storages':['nfs']}
    if failure=='pending_vm':pve.pending=[{'key':'cores','pending':4}]
    if failure=='snapshot':pve.snapshots.append({'name':'before'})
    if failure=='autostart':pve.config['onboot']=1
    if failure=='host_device':pve.config['hostpci0']='01:00.0'
    if failure=='extra_nic':pve.config['net1']='virtio=02:00:00:00:00:02,bridge=vmbr1'
    if failure=='vlan':pve.config['net0']+=',tag=100'
    if failure=='confirmation':request=request.model_copy(update={'migration_acknowledged':False})
    with pytest.raises(MigrateError):execute((service,pve,request))
    assert not pve.calls


def test_migrate_transport_is_offline_without_storage_remap_force_or_host_override():
    scope={'nodes':['node1','node2'],'vmids':[40000]};pieces=['nodes','node1','qemu','40000','migrate'];body=request_body('node2')
    assert request_allowed('POST',pieces,body,scope)
    for patch in ({'target':'node1'},{'target':'node3'},{'online':1},{'force':1},{'with-local-disks':1},
                  {'targetstorage':'other'},{'migration_type':'insecure'},{'migration_network':'10.0.0.0/8'},{'force':False}):
        assert not request_allowed('POST',pieces,{**body,**patch},scope)
