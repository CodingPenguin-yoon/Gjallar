import json

import httpx
import pytest

from gjallar_client import cli, network_workflow
from gjallar_client.api import Api
from gjallar_client.application import Application
from gjallar_client.connections import Connections
from gjallar_client.errors import ClientError
from gjallar_client.sessions import MemoryStore
from test_cli_workflows import WorkflowServer
from test_client import PASSWORD


class NetworkServer(WorkflowServer):
    def __call__(self, request):
        if request.url.path.endswith('/network') and request.method == 'GET':
            self.calls.append(request)
            return httpx.Response(200, json={'ok': True, 'data': {
                'target': {'node_id': 'pve', 'vmid': 40000},
                'observed_before': {'name': 'test', 'digest': 'a' * 40,
                    'net0': 'virtio=02:00:00:00:00:01,bridge=vmbr0,firewall=1', 'bridge_id': 'vmbr0', 'vlan_tag': None,
                    'bridges': [{'bridge_id': 'vmbr0', 'vlan_aware': False}, {'bridge_id': 'vmbr1', 'vlan_aware': True}]},
            }})
        return super().__call__(request)


@pytest.fixture
def flow(tmp_path):
    connections = Connections(tmp_path / 'config')
    connections.add('test', 'http://127.0.0.1:8000')
    server = NetworkServer()
    app = Application(connections, MemoryStore(), lambda profile: Api(profile, httpx.MockTransport(server)))
    app.login('operator', PASSWORD, 'test')
    return app, server, tmp_path / 'network.json'


def plan(app, path, **changes):
    return network_workflow.plan(app, vmid=40000, node='pve', request_id='network-1', review_file=path,
                                **{'bridge_id': 'vmbr1', 'vlan_tag': 100, **changes})


def test_network_review_preserves_nic_and_request_identity(flow):
    app, server, path = flow
    result = plan(app, path)
    assert result['exit_code'] == 0 and path.stat().st_mode & 0o777 == 0o600
    assert not any('/actions/' in str(request.url) for request in server.calls)
    confirmations = []
    for _ in range(2):
        assert network_workflow.execute(app, path, confirmations.append)['exit_code'] == 0
    posts = [request for request in server.calls if '/actions/' in str(request.url)]
    assert posts[0].content == posts[1].content and posts[0].url.path.endswith('/actions/network')
    payload = json.loads(posts[0].content)
    assert payload['vlan_tag'] == 100 and payload['expected_net0'].endswith('firewall=1')
    assert '게스트 통신' in confirmations[0]['action']


@pytest.mark.parametrize('changes', [{'bridge_id': 'missing'}, {'bridge_id': 'vmbr0'}, {'bridge_id': 'vmbr0', 'vlan_tag': None}, {'vlan_tag': 4095}])
def test_invalid_network_review_is_not_saved(flow, changes):
    app, server, path = flow
    with pytest.raises(ClientError):
        plan(app, path, **changes)
    assert not path.exists()
    assert not any('/actions/' in str(request.url) for request in server.calls)


def test_network_timeout_does_not_retry(flow):
    app, server, path = flow
    plan(app, path, vlan_tag=None)
    server.timeout_mutation = True
    with pytest.raises(ClientError) as failure:
        network_workflow.execute(app, path, lambda _: None)
    assert failure.value.code == 'MUTATION_UNCONFIRMED'
    assert len([request for request in server.calls if '/actions/' in str(request.url)]) == 1


def test_network_cli_requires_explicit_vlan_choice():
    args = ['vm', 'network', 'plan', '40000', '--node', 'pve', '--bridge', 'vmbr1',
            '--request-id', 'network-1', '--review-file', '/tmp/network-review.json']
    with pytest.raises(ClientError):
        cli.parser().parse_args(args)
    parsed = cli.parser().parse_args(args + ['--untagged'])
    assert parsed.vlan_tag is None and parsed.untagged
    assert cli.parser().parse_args(args + ['--vlan-tag', '100']).vlan_tag == 100
