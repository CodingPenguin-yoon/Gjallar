import json
import httpx
import pytest
from gjallar_client import cli, image_cleanup_workflow
from gjallar_client.api import Api
from gjallar_client.application import Application
from gjallar_client.connections import Connections
from gjallar_client.errors import ClientError
from gjallar_client.sessions import MemoryStore
from test_cli_workflows import WorkflowServer
from test_client import PASSWORD

PARENT = 'vm-image-build-' + 'a' * 64


class CleanupServer(WorkflowServer):
    def __call__(self, request):
        if request.url.path.endswith('/image-cleanup') and request.method == 'GET':
            self.calls.append(request)
            assert dict(request.url.params) == {'parent_operation_id': PARENT, 'resource': 'source'}
            return httpx.Response(200, json={'ok': True, 'data': {
                'target': {'node_id': 'pve', 'vmid': 40000}, 'observed_before': {
                    'name': 'alma-test', 'parent_operation_id': PARENT, 'resource': 'source', 'review_digest': 'sha256:'+'b'*64,
                    'deleted_volumes': [{'volume_id': 'stage:import/owned.qcow2'}], 'preserved_volumes': []},
                'warnings': ['영구 삭제'],
            }})
        return super().__call__(request)


@pytest.fixture
def flow(tmp_path):
    connections = Connections(tmp_path / 'config')
    connections.add('test', 'http://127.0.0.1:8000')
    server = CleanupServer()
    app = Application(connections, MemoryStore(), lambda profile: Api(profile, httpx.MockTransport(server)))
    app.login('operator', PASSWORD, 'test')
    return app, server, tmp_path / 'cleanup.json'


def plan(app, path, **kwargs):
    return image_cleanup_workflow.plan(app, vmid=40000, node='pve', parent_operation_id=PARENT, resource='source',
        request_id='cleanup-review', review_file=path, **{'confirmation': '40000/alma-test/source', 'acknowledged': True, **kwargs})


def test_cleanup_review_binds_parent_resource_confirmation_and_same_request(flow):
    app, server, path = flow
    plan(app, path)
    assert path.stat().st_mode & 0o777 == 0o600
    confirmed = []
    assert not any('/actions/' in str(row.url) for row in server.calls)
    for _ in range(2): assert image_cleanup_workflow.execute(app, path, confirmed.append)['exit_code'] == 0
    posts = [row for row in server.calls if '/actions/' in str(row.url)]
    assert len(posts) == 2 and posts[0].content == posts[1].content
    assert posts[0].url.path.endswith('/actions/image-cleanup')
    payload = json.loads(posts[0].content)
    assert payload['parent_operation_id'] == PARENT and payload['resource'] == 'source'
    assert payload['confirmation'] == '40000/alma-test/source' and payload['cleanup_acknowledged'] is True
    assert confirmed[0]['review']['observed_before']['deleted_volumes']


@pytest.mark.parametrize('patch', [{'acknowledged': False}, {'acknowledged': 1}, {'confirmation': '40000/alma-test/template'}, {'confirmation': '40001/alma-test/source'}])
def test_cleanup_identity_and_ack_are_required(flow, patch):
    app, _, path = flow
    with pytest.raises(ClientError): plan(app, path, **patch)
    assert not path.exists()


def test_cleanup_connection_loss_is_not_resent(flow):
    app, server, path = flow
    plan(app, path)
    server.timeout_mutation = True
    with pytest.raises(ClientError) as caught: image_cleanup_workflow.execute(app, path, lambda _: None)
    assert caught.value.code == 'MUTATION_UNCONFIRMED'
    assert len([row for row in server.calls if '/actions/' in str(row.url)]) == 1


def test_cleanup_parser():
    args = cli.parser().parse_args(['vm', 'image-cleanup', 'plan', '40000', '--node', 'pve', '--build-operation', PARENT,
        '--resource', 'source', '--confirmation', '40000/alma-test/source', '--ack-cleanup', '--request-id', 'cleanup-test', '--review-file', '/tmp/cleanup.json'])
    assert args.resource == 'source' and args.ack_cleanup
