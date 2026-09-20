import json

import httpx
import pytest

from gjallar_client import cli, backup_workflow
from gjallar_client.api import Api
from gjallar_client.application import Application
from gjallar_client.connections import Connections
from gjallar_client.errors import ClientError
from gjallar_client.sessions import MemoryStore
from test_cli_workflows import WorkflowServer
from test_client import PASSWORD


class BackupServer(WorkflowServer):
    def __call__(self, request):
        if '/actions/backup' in request.url.path:
            self.payload = json.loads(request.content)
        if '/operations/' in request.url.path:
            self.calls.append(request)
            return httpx.Response(200,json={'ok':True,'data':{'operation':{
                'operation_id':'create-1','status':self.status,'operation_type':'vm_backup','target_type':'proxmox_vm',
                'target_id':'vmid:40000','details':{'target':{'node_id':'pve'},'requested':self.payload}}}})
        if request.url.path.endswith('/backup-review') and request.method == 'GET':
            self.calls.append(request)
            return httpx.Response(200, json={'ok': True, 'data': {
                'target': {'node_id': 'pve', 'vmid': 40000},
                'observed_before': {'name': 'test', 'storage_id': 'store1', 'review_digest': 'sha256:' + 'b' * 64,
                    'volumes': [{'volume_id': 'store1:40000/vm-40000-disk-0.qcow2'}], 'archives': []},
                'warnings': ['백업'],
            }})
        return super().__call__(request)


@pytest.fixture
def flow(tmp_path):
    connections = Connections(tmp_path / 'config')
    connections.add('test', 'http://127.0.0.1:8000')
    server = BackupServer()
    app = Application(connections, MemoryStore(), lambda profile: Api(profile, httpx.MockTransport(server)))
    app.login('operator', PASSWORD, 'test')
    return app, server, tmp_path / 'backup.json'


def plan(app, path, **kwargs):
    return backup_workflow.plan(app, vmid=40000, node='pve', request_id='backup-review', review_file=path,
        **{'storage': 'store1', 'confirmation': '40000/test', 'backup_acknowledged': True, **kwargs})


def test_backup_review_keeps_confirmation_and_manifest_across_replay(flow):
    app, server, path = flow
    assert plan(app, path)['exit_code'] == 0
    assert path.stat().st_mode & 0o777 == 0o600
    assert not any('/actions/' in str(request.url) for request in server.calls)
    confirmed = []
    for _ in range(2):
        assert backup_workflow.execute(app, path, confirmed.append)['exit_code'] == 0
    posts = [request for request in server.calls if '/actions/' in str(request.url)]
    assert len(posts) == 2 and posts[0].content == posts[1].content
    assert posts[0].url.path.endswith('/actions/backup')
    payload = json.loads(posts[0].content)
    assert payload['confirmation'] == '40000/test' and payload['backup_acknowledged'] is True
    assert payload['expected_review_digest'] == 'sha256:' + 'b' * 64
    assert '백업' in confirmed[0]['action'] and confirmed[0]['review']['observed_before']['volumes']


@pytest.mark.parametrize('kwargs', [{'confirmation': '40001/test'}, {'confirmation': '40000/other'},
                                   {'backup_acknowledged': False}, {'backup_acknowledged': 1}])
def test_wrong_identity_or_missing_ack_never_creates_review(flow, kwargs):
    app, _, path = flow
    with pytest.raises(ClientError):
        plan(app, path, **kwargs)
    assert not path.exists()


def test_backup_timeout_never_resends(flow):
    app, server, path = flow
    plan(app, path)
    server.timeout_mutation = True
    with pytest.raises(ClientError) as failure:
        backup_workflow.execute(app, path, lambda _: None)
    assert failure.value.code == 'MUTATION_UNCONFIRMED'
    assert len([request for request in server.calls if '/actions/' in str(request.url)]) == 1


def test_backup_parser():
    args = cli.parser().parse_args(['vm', 'backup', 'plan', '40000', '--node', 'pve', '--confirmation', '40000/test',
        '--ack-backup', '--storage', 'store1', '--request-id', 'backup-review', '--review-file', '/tmp/backup-review.json'])
    assert args.action == 'backup' and args.ack_backup and args.confirmation == '40000/test'


def test_backup_canonical_read_cannot_confirm_another_request(flow):
    app,server,path=flow
    plan(app,path)
    original=app.request
    def request(target, **kwargs):
        result=original(target,**kwargs)
        if target.startswith('operations/'):
            result['data']['operation']['details']['requested']={**server.payload,'idempotency_key':'unrelated-success'}
        return result
    app.request=request
    with pytest.raises(ClientError) as failure: backup_workflow.execute(app,path,lambda _:None)
    assert failure.value.code=='MUTATION_UNCONFIRMED'
    assert len([request for request in server.calls if '/actions/' in str(request.url)])==1
