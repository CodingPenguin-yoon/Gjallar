import json
import httpx
import pytest
from gjallar_client import cli, restore_workflow
from gjallar_client.api import Api
from gjallar_client.application import Application
from gjallar_client.connections import Connections
from gjallar_client.errors import ClientError
from gjallar_client.sessions import MemoryStore
from test_cli_workflows import WorkflowServer
from test_client import PASSWORD

ARCHIVE='nfs:backup/vzdump-qemu-40000-2026_09_19-05_00_00.vma.zst'


class RestoreServer(WorkflowServer):
    def __call__(self,request):
        if request.url.path.endswith('/actions/restore'):self.payload=json.loads(request.content)
        if '/operations/' in request.url.path:
            self.calls.append(request)
            return httpx.Response(200,json={'ok':True,'data':{'operation':{'operation_id':'create-1','status':self.status,
                'operation_type':'vm_restore','target_type':'proxmox_vm','target_id':'vmid:40001',
                'details':{'target':{'node_id':'pve'},'requested':self.payload}}}})
        if request.url.path.endswith('/restore-review'):
            self.calls.append(request)
            return httpx.Response(200,json={'ok':True,'data':{'target':{'node_id':'pve','vmid':40000},
                'observed_before':{'name':'source','review_digest':'sha256:'+'a'*64,'archive':{'file':{'volume_id':ARCHIVE}},
                    'destination':{'vmid':40001,'storage_id':'target','bridge_id':'vmbr1'}},'warnings':['격리 복원']}})
        return super().__call__(request)


@pytest.fixture
def flow(tmp_path):
    connections=Connections(tmp_path/'config');connections.add('test','http://127.0.0.1:8000')
    server=RestoreServer();app=Application(connections,MemoryStore(),lambda profile:Api(profile,httpx.MockTransport(server)))
    app.login('operator',PASSWORD,'test')
    return app,server,tmp_path/'restore.json'


def plan(app,path,**kwargs):
    return restore_workflow.plan(app,**{'vmid':40000,'node':'pve','archive':ARCHIVE,'new_vmid':40001,'name':'restored',
        'storage':'target','bridge':'vmbr1','confirmation':'40000/40001/restored','ack_isolation':True,
        'request_id':'restore-test','review_file':path,**kwargs})


def test_restore_binds_review_source_and_canonical_new_target_without_auto_boot(flow):
    app,server,path=flow
    assert plan(app,path)['exit_code']==0 and path.stat().st_mode&0o777==0o600
    assert not any('/actions/' in str(request.url) for request in server.calls)
    confirmed=[]
    for _ in range(2):assert restore_workflow.execute(app,path,confirmed.append)['exit_code']==0
    posts=[request for request in server.calls if '/actions/' in str(request.url)]
    assert len(posts)==2 and posts[0].content==posts[1].content
    assert posts[0].url.path.endswith('/vms/40000/actions/restore')
    assert json.loads(posts[0].content)['new_vmid']==40001
    assert confirmed[0]['target']['vmid']==40000 and confirmed[0]['requested']['isolation_acknowledged'] is True


@pytest.mark.parametrize('kwargs',[{'confirmation':'40000/40002/restored'},{'ack_isolation':False},{'ack_isolation':1},
    {'new_vmid':40000},{'storage':'other'},{'bridge':'other'},{'archive':ARCHIVE.replace('40000','40002')}])
def test_restore_bad_target_or_missing_isolation_ack_does_not_save_intent(flow,kwargs):
    app,_,path=flow
    with pytest.raises(ClientError):plan(app,path,**kwargs)
    assert not path.exists()


def test_restore_timeout_preserves_request_without_retry(flow):
    app,server,path=flow;plan(app,path);server.timeout_mutation=True
    with pytest.raises(ClientError) as error:restore_workflow.execute(app,path,lambda _:None)
    assert error.value.code=='MUTATION_UNCONFIRMED'
    assert len([r for r in server.calls if '/actions/' in str(r.url)])==1


def test_restore_cannot_accept_success_of_source_vm(flow):
    app,server,path=flow;plan(app,path)
    original=app.request
    def request(target,**kwargs):
        result=original(target,**kwargs)
        if target.startswith('operations/'):result['data']['operation']['target_id']='vmid:40000'
        return result
    app.request=request
    with pytest.raises(ClientError) as error:restore_workflow.execute(app,path,lambda _:None)
    assert error.value.code=='MUTATION_UNCONFIRMED'


def test_restore_parser():
    args=cli.parser().parse_args(['vm','restore','plan','40000','--node','pve','--archive',ARCHIVE,
        '--new-vmid','40001','--name','restored','--storage','target','--bridge','vmbr1',
        '--confirmation','40000/40001/restored','--ack-isolation','--request-id','restore-test','--review-file','/tmp/test.json'])
    assert args.new_vmid==40001 and args.ack_isolation
    assert cli.parser().parse_args(['vm','restore','report','restore-test']).operation_id=='restore-test'
