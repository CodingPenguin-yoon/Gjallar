import json
import httpx
import pytest
from gjallar_client import cli, host_network_workflow
from gjallar_client.api import Api
from gjallar_client.application import Application
from gjallar_client.connections import Connections
from gjallar_client.errors import ClientError
from gjallar_client.sessions import MemoryStore
from test_cli_workflows import WorkflowServer
from test_client import PASSWORD


class HostServer(WorkflowServer):
    def __init__(self):
        super().__init__()
        self.role = 'admin'
        self.operation_patch = {}
    def __call__(self,request):
        if request.url.path.endswith('/host-network/vmbr40/review'):
            self.calls.append(request)
            change = json.loads(request.content)
            return httpx.Response(200,json={'ok':True,'data':{'target':{'node_id':'pve','bridge_id':'vmbr40'},
                'mode':'update','review_digest':'sha256:'+'a'*64,'confirmation':'pve/vmbr40/update',
                'desired':{**change,'ports':['eno2']},'warnings':['cluster-wide']}})
        if request.url.path.endswith('/actions/configure'):
            self.calls.append(request)
            if self.timeout_mutation:
                raise httpx.ReadTimeout('synthetic hidden response')
            self.payload = json.loads(request.content)
            return httpx.Response(200,json={'ok':True,'data':{'operation':{'operation_id':'host-1'}}})
        if '/operations/' in request.url.path:
            self.calls.append(request)
            return httpx.Response(200,json={'ok':True,'data':{'operation':{'operation_id':'host-1','status':self.status,
                'operation_type':'host_network','target_type':'proxmox_network','target_id':'node:pve/bridge:vmbr40',
                'details':{'target':{'node_id':'pve','bridge_id':'vmbr40'},'requested':self.payload},**self.operation_patch}}})
        return super().__call__(request)


@pytest.fixture
def flow(tmp_path):
    connections=Connections(tmp_path/'config');connections.add('test','http://127.0.0.1:8000')
    server=HostServer();app=Application(connections,MemoryStore(),lambda profile:Api(profile,httpx.MockTransport(server)))
    app.login('admin',PASSWORD,'test')
    return app,server,tmp_path/'host-network.json'


def plan(app,path,**patch):
    return host_network_workflow.plan(app,**{'node':'pve','bridge':'vmbr40','mode':'update','autostart':True,
        'vlan_aware':True,'vlan_ids':'10 20-30','request_id':'test','confirmation':'pve/vmbr40/update',
        'acknowledge':True,'review_file':path,**patch})


def test_host_network_review_is_private_and_execution_checks_canonical_non_vm_target(flow):
    app,server,path=flow
    assert plan(app,path)['exit_code']==0 and path.stat().st_mode&0o777==0o600
    assert not any('/actions/' in str(request.url) for request in server.calls)
    confirmed=[]
    assert host_network_workflow.execute(app,path,confirmed.append)['exit_code']==0
    assert confirmed[0]['target']=={'node_id':'pve','bridge_id':'vmbr40'}
    assert len([row for row in server.calls if '/actions/' in str(row.url)])==1
    assert server.payload['expected_review_digest']=='sha256:'+'a'*64


@pytest.mark.parametrize('patch',[{'target_type':'proxmox_vm'}, {'target_id':'node:pve/bridge:vmbr99'}, {'operation_type':'host_storage'},
    {'details':{'target':{'node_id':'other','bridge_id':'vmbr40'},'requested':{}}}])
def test_wrong_canonical_operation_never_reports_success_or_retries(flow,patch):
    app,server,path=flow
    plan(app,path);server.operation_patch=patch
    with pytest.raises(ClientError) as failure: host_network_workflow.execute(app,path,lambda value:None)
    assert failure.value.code=='MUTATION_UNCONFIRMED'
    assert len([row for row in server.calls if '/actions/' in str(row.url)])==1


@pytest.mark.parametrize('patch',[{'confirmation':'pve/vmbr99/update'},{'acknowledge':False},{'vlan_ids':'4095'},
    {'vlan_aware':False,'vlan_ids':'10'},{'bridge':'eno1'}])
def test_invalid_target_acknowledgement_or_path_never_dispatches(flow,patch):
    app,server,path=flow
    with pytest.raises(ClientError): plan(app,path,**patch)
    assert not any('/actions/' in str(row.url) for row in server.calls)


def test_review_file_remains_bound_to_server_and_pending_is_not_success(flow):
    app,server,path=flow
    plan(app,path);server.status='needs_reconciliation'
    assert host_network_workflow.execute(app,path,lambda value:None)['exit_code']==8
    record=json.loads(path.read_text());record['origin']='https://different.example';path.write_text(json.dumps(record))
    with pytest.raises(ClientError,match='서버 연결'): host_network_workflow.execute(app,path,lambda value:None)
    assert len([row for row in server.calls if '/actions/' in str(row.url)])==1


def test_lost_response_does_not_retry_or_disclose_transport_details(flow):
    app,server,path=flow
    plan(app,path);server.timeout_mutation=True
    with pytest.raises(ClientError) as failure: host_network_workflow.execute(app,path,lambda value:None)
    assert failure.value.code=='MUTATION_UNCONFIRMED' and 'hidden response' not in str(failure.value)
    assert len([row for row in server.calls if '/actions/' in str(row.url)])==1


def test_host_network_parser_keeps_plan_and_execute_explicit():
    args=cli.parser().parse_args(['host','network','plan','vmbr40','--node','pve','--mode','create',
        '--vlan-aware','--vlan-ids','10 20-30','--request-id','test','--confirmation','pve/vmbr40/create','--ack-node-reload','--review-file','test.json'])
    assert args.stage=='plan' and args.vlan_ids=='10 20-30'
