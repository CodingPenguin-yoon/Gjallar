import json

import httpx
import pytest

from gjallar_client import cli, disk_workflow
from gjallar_client.api import Api
from gjallar_client.application import Application
from gjallar_client.connections import Connections
from gjallar_client.errors import ClientError
from gjallar_client.sessions import MemoryStore
from test_cli_workflows import WorkflowServer
from test_client import PASSWORD


class DiskServer(WorkflowServer):
    def __call__(self, request):
        if request.url.path.endswith('/disks/scsi0') and request.method == 'GET':
            self.calls.append(request)
            return httpx.Response(200, json={'ok': True, 'data': {
                'target': {'node_id': 'pve', 'vmid': 40000},
                'observed_before': {'name': 'test', 'digest': 'a' * 40,
                    'volume_id': 'store1:40000/vm-40000-disk-0.qcow2', 'size_bytes': 20 * 1024 ** 3},
            }})
        return super().__call__(request)


@pytest.fixture
def flow(tmp_path):
    connections = Connections(tmp_path / 'config')
    connections.add('test', 'http://127.0.0.1:8000')
    server = DiskServer()
    app = Application(connections, MemoryStore(), lambda profile: Api(profile, httpx.MockTransport(server)))
    app.login('operator', PASSWORD, 'test')
    return app, server, tmp_path / 'disk.json'


def test_disk_review_is_absolute_and_original_payload_is_preserved(flow):
    app, server, path = flow
    result = disk_workflow.plan(app, vmid=40000, node='pve', size_gib=24, request_id='disk-review-1', review_file=path)
    assert result['exit_code'] == 0 and path.stat().st_mode & 0o777 == 0o600
    assert not any('/actions/' in str(request.url) for request in server.calls)
    confirmed = []
    for _ in range(2):
        assert disk_workflow.execute(app, path, confirmed.append)['exit_code'] == 0
    posts = [request for request in server.calls if '/actions/' in str(request.url)]
    assert len(posts) == 2 and posts[0].content == posts[1].content
    assert posts[0].url.path.endswith('/actions/disk-resize')
    payload = json.loads(posts[0].content)
    assert payload['size_gib'] == 24 and payload['expected_size_bytes'] == 20 * 1024 ** 3
    assert 'filesystem' in confirmed[0]['action']


def test_disk_shrink_does_not_create_review_and_timeout_does_not_retry(flow):
    app, server, path = flow
    with pytest.raises(ClientError, match='축소'):
        disk_workflow.plan(app, vmid=40000, node='pve', size_gib=20, request_id='disk-review-1', review_file=path)
    assert not path.exists()
    disk_workflow.plan(app, vmid=40000, node='pve', size_gib=24, request_id='disk-review-1', review_file=path)
    server.timeout_mutation = True
    with pytest.raises(ClientError) as failure:
        disk_workflow.execute(app, path, lambda _: None)
    assert failure.value.code == 'MUTATION_UNCONFIRMED'
    assert len([request for request in server.calls if '/actions/' in str(request.url)]) == 1


def test_disk_cli_parser():
    args = cli.parser().parse_args(['vm', 'disk', 'plan', '40000', '--node', 'pve', '--size-gib', '24',
                                  '--request-id', 'disk-review', '--review-file', '/tmp/disk-review.json'])
    assert args.action == 'disk' and args.size_gib == 24
