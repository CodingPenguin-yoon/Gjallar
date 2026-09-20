import json

import httpx
import pytest

from gjallar_client import cli, clone_workflow
from gjallar_client.api import Api
from gjallar_client.application import Application
from gjallar_client.connections import Connections
from gjallar_client.errors import ClientError
from gjallar_client.sessions import MemoryStore
from test_cli_workflows import WorkflowServer
from test_client import PASSWORD


class CloneServer(WorkflowServer):
    def __call__(self, request):
        if request.url.path.endswith('/clone') and request.method == 'GET':
            self.calls.append(request)
            assert request.url.params['new_vmid'] == '40001' and request.url.params['storage_id'] == 'dest'
            return httpx.Response(200, json={'ok': True, 'data': {
                'target': {'node_id': 'pve', 'vmid': 40000},
                'observed_before': {'source': {'name': 'original', 'digest': 'a' * 40,
                    'volume_id': 'source:40000/vm-40000-disk-0.qcow2', 'size_bytes': 20 * 1024 ** 3},
                    'destination': {'node_id': 'pve', 'vmid': 40001, 'storage_id': 'dest'}},
            }})
        return super().__call__(request)


@pytest.fixture
def flow(tmp_path):
    connections = Connections(tmp_path / 'config')
    connections.add('test', 'http://127.0.0.1:8000')
    server = CloneServer()
    app = Application(connections, MemoryStore(), lambda profile: Api(profile, httpx.MockTransport(server)))
    app.login('operator', PASSWORD, 'test')
    return app, server, tmp_path / 'clone.json'


def plan(app, path, **changes):
    return clone_workflow.plan(app, vmid=40000, node='pve', new_vmid=40001, name='copy-test', storage='dest',
        request_id='clone-1', review_file=path, **{'ack_guest_identity': True, **changes})


def test_clone_review_preserves_source_and_new_target_then_verifies_operation(flow):
    app, server, path = flow
    result = plan(app, path)
    assert result['data']['destination']['status'] == 'stopped'
    assert path.stat().st_mode & 0o777 == 0o600
    assert not any('/actions/' in str(row.url) for row in server.calls)
    confirmations = []
    for _ in range(2):
        assert clone_workflow.execute(app, path, confirmations.append)['exit_code'] == 0
    posts = [row for row in server.calls if '/actions/' in str(row.url)]
    assert posts[0].content == posts[1].content
    assert posts[0].url.path == '/api/v1/nodes/pve/vms/40000/actions/clone'
    assert json.loads(posts[0].content)['new_vmid'] == 40001
    assert confirmations[0]['target']['vmid'] == 40000


def test_guest_identity_requires_ack_before_saving_review(flow):
    app, _, path = flow
    with pytest.raises(ClientError) as failure:
        plan(app, path, ack_guest_identity=False)
    assert failure.value.code == 'IDENTITY_ACK_REQUIRED' and not path.exists()


def test_unknown_clone_response_is_not_retried_and_points_to_destination(flow):
    app, server, path = flow
    plan(app, path)
    server.timeout_mutation = True
    with pytest.raises(ClientError) as failure:
        clone_workflow.execute(app, path, lambda _: None)
    assert failure.value.code == 'MUTATION_UNCONFIRMED'
    assert '40001' in str(failure.value)
    assert len([row for row in server.calls if '/actions/' in str(row.url)]) == 1


def test_clone_cli_parser_keeps_explicit_guest_identity_ack():
    args = cli.parser().parse_args(['vm', 'clone', 'plan', '40000', '--node', 'pve', '--new-vmid', '40001',
        '--name', 'copy-test', '--storage', 'dest', '--request-id', 'clone-1', '--review-file', '/tmp/clone.json', '--ack-guest-identity'])
    assert args.ack_guest_identity and args.new_vmid == 40001 and args.vmid == 40000
