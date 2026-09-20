import json

import httpx
import pytest

from gjallar_client import cli, compute_workflow
from gjallar_client.api import Api
from gjallar_client.application import Application
from gjallar_client.connections import Connections
from gjallar_client.errors import ClientError
from gjallar_client.sessions import MemoryStore
from test_cli_workflows import WorkflowServer
from test_client import PASSWORD


class ComputeServer(WorkflowServer):
    def __call__(self, request):
        if request.url.path.endswith('/compute') and request.method == 'GET':
            self.calls.append(request)
            return httpx.Response(200, json={'ok': True, 'data': {
                'target': {'node_id': 'pve', 'vmid': 40000},
                'observed_before': {'name': 'test', 'digest': 'a' * 40, 'cores': 2, 'memory_mib': 2048},
                'warnings': ['stopped only'],
            }})
        return super().__call__(request)


@pytest.fixture
def flow(tmp_path):
    connections = Connections(tmp_path / 'config')
    connections.add('test', 'http://127.0.0.1:8000')
    server = ComputeServer()
    app = Application(connections, MemoryStore(), lambda profile: Api(profile, httpx.MockTransport(server)))
    app.login('operator', PASSWORD, 'test')
    review = tmp_path / 'review.json'
    result = compute_workflow.plan(app, vmid=40000, node='pve', cores=4, memory_mib=4096,
        request_id='test-compute', review_file=review)
    assert result['exit_code'] == 0
    assert not any('/actions/' in str(request.url) for request in server.calls)
    return app, server, review


def test_compute_review_execute_and_repeat_preserve_original_payload(flow):
    app, server, review = flow
    assert review.stat().st_mode & 0o777 == 0o600
    confirmed = []
    for _ in range(2):
        assert compute_workflow.execute(app, review, confirmed.append)['exit_code'] == 0
    posts = [request for request in server.calls if '/actions/' in str(request.url)]
    assert len(posts) == 2 and posts[0].content == posts[1].content
    assert json.loads(posts[0].content)['expected_digest'] == 'a' * 40
    assert confirmed[0]['target']['vmid'] == 40000


def test_compute_timeout_does_not_retry_and_unconfirmed_status_is_nonzero(flow):
    app, server, review = flow
    server.timeout_mutation = True
    with pytest.raises(ClientError) as failure:
        compute_workflow.execute(app, review, lambda _: None)
    assert failure.value.code == 'MUTATION_UNCONFIRMED'
    assert len([request for request in server.calls if '/actions/' in str(request.url)]) == 1
    server.timeout_mutation = False
    server.status = 'needs_reconciliation'
    assert compute_workflow.execute(app, review, lambda _: None)['exit_code'] == 8


def test_compute_wrong_connection_and_extra_fields_never_dispatch(flow):
    app, server, review = flow
    original = json.loads(review.read_text())
    review.write_text(json.dumps({**original, 'origin': 'https://different.test'}))
    with pytest.raises(ClientError, match='서버 연결'):
        compute_workflow.execute(app, review, lambda _: None)
    original['payload']['delete'] = 'scsi0'
    review.write_text(json.dumps(original))
    with pytest.raises(ClientError, match='입력 필드'):
        compute_workflow.execute(app, review, lambda _: None)
    assert not any('/actions/' in str(request.url) for request in server.calls)


def test_compute_cli_parser_supports_review_and_execute():
    args = cli.parser().parse_args(['vm', 'compute', 'plan', '40000', '--node', 'pve', '--cores', '4',
        '--memory-mib', '4096', '--request-id', 'compute-test', '--review-file', '/tmp/compute-test.json'])
    assert args.action == 'compute' and args.stage == 'plan' and args.memory_mib == 4096
