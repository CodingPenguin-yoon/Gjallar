import json
import httpx
import pytest
from gjallar_client import cli, migrate_workflow
from gjallar_client.api import Api
from gjallar_client.application import Application
from gjallar_client.connections import Connections
from gjallar_client.errors import ClientError
from gjallar_client.sessions import MemoryStore
from test_cli_workflows import WorkflowServer
from test_client import PASSWORD


class MigrateServer(WorkflowServer):
    def __call__(self, request):
        if request.url.path.endswith('/actions/migrate'): self.payload=json.loads(request.content)
        if '/operations/' in request.url.path:
            self.calls.append(request)
            return httpx.Response(200,json={'ok':True,'data':{'operation':{'operation_id':'create-1','status':self.status,
                'operation_type':'vm_migrate','target_type':'proxmox_vm','target_id':'vmid:40000',
                'details':{'target':{'node_id':'pve'},'requested':self.payload}}}})
        if request.method == 'GET' and request.url.path.endswith('/migrate'):
            self.calls.append(request)
            return httpx.Response(200,json={'ok':True,'data':{'target':{'node_id':'pve','vmid':40000},
                'observed_before':{'name':'source','review_digest':'sha256:'+'a'*64,'destination':{'node_id':'dest'}},'warnings':['정지 이동']}})
        return super().__call__(request)


@pytest.fixture
def flow(tmp_path):
    connections=Connections(tmp_path/'config');connections.add('test','http://127.0.0.1:8000')
    server=MigrateServer();app=Application(connections,MemoryStore(),lambda profile:Api(profile,httpx.MockTransport(server)))
    app.login('operator',PASSWORD,'test')
    return app,server,tmp_path/'migrate.json'


def plan(app,path,**kwargs):
    return migrate_workflow.plan(app,**{'vmid':40000,'node':'pve','destination':'dest',
        'confirmation':'40000/source/pve->dest','ack_migration':True,'request_id':'migrate-test','review_file':path,**kwargs})


def test_migration_keeps_source_canonical_target_and_same_intent_on_explicit_replay(flow):
    app,server,path=flow
    assert plan(app,path)['exit_code']==0 and path.stat().st_mode&0o777==0o600
    assert not any('/actions/' in str(request.url) for request in server.calls)
    confirmed=[]
    for _ in range(2): assert migrate_workflow.execute(app,path,confirmed.append)['exit_code']==0
    posts=[r for r in server.calls if '/actions/' in str(r.url)]
    assert len(posts)==2 and posts[0].content==posts[1].content
    assert posts[0].url.path.endswith('/vms/40000/actions/migrate')
    assert json.loads(posts[0].content)['destination_node']=='dest'
    assert confirmed[0]['target']=={'node_id':'pve','vmid':40000}


@pytest.mark.parametrize('kwargs',[{'confirmation':'40000/source/other->dest'},{'confirmation':'40001/source/pve->dest'},
    {'ack_migration':False},{'ack_migration':1},{'destination':'pve'},{'destination':'other'},{'node':'other'},{'vmid':True}])
def test_migration_bad_scope_or_missing_confirmation_does_not_save(flow,kwargs):
    app,_,path=flow
    with pytest.raises(ClientError): plan(app,path,**kwargs)
    assert not path.exists()


def test_migration_timeout_preserves_request_without_retry(flow):
    app,server,path=flow;plan(app,path);server.timeout_mutation=True
    with pytest.raises(ClientError) as error: migrate_workflow.execute(app,path,lambda _:None)
    assert error.value.code=='MUTATION_UNCONFIRMED'
    assert len([r for r in server.calls if '/actions/' in str(r.url)])==1


def test_migration_rejects_operation_from_destination_node_instead_of_source(flow):
    app,server,path=flow;plan(app,path)
    original=app.request
    def request(target,**kwargs):
        result=original(target,**kwargs)
        if target.startswith('operations/'): result['data']['operation']['details']['target']['node_id']='dest'
        return result
    app.request=request
    with pytest.raises(ClientError) as error: migrate_workflow.execute(app,path,lambda _:None)
    assert error.value.code=='MUTATION_UNCONFIRMED'


def test_migration_parser():
    args=cli.parser().parse_args(['vm','migrate','plan','40000','--node','pve','--destination','dest',
        '--confirmation','40000/source/pve->dest','--ack-migration','--request-id','migrate-test','--review-file','/tmp/test.json'])
    assert args.destination=='dest' and args.ack_migration
