import json

import httpx
import pytest

from gjallar_client import cli, template_workflow
from gjallar_client.api import Api
from gjallar_client.application import Application
from gjallar_client.connections import Connections
from gjallar_client.errors import ClientError
from gjallar_client.sessions import MemoryStore
from test_cli_workflows import WorkflowServer
from test_client import PASSWORD


class TemplateServer(WorkflowServer):
    def __call__(self, request):
        if request.url.path.endswith('/template-conversion') and request.method == 'GET':
            self.calls.append(request)
            return httpx.Response(200, json={'ok': True, 'data': {
                'target': {'node_id': 'pve', 'vmid': 40000},
                'observed_before': {'name': 'test', 'digest': 'a' * 40, 'resources_digest': 'sha256:' + 'b' * 64,
                    'volumes': [{'volume_id': 'store1:40000/vm-40000-disk-0.qcow2'}], 'preserved_volumes': []},
                'warnings': ['템플릿 전환'],
            }})
        return super().__call__(request)


@pytest.fixture
def flow(tmp_path):
    connections = Connections(tmp_path / 'config')
    connections.add('test', 'http://127.0.0.1:8000')
    server = TemplateServer()
    app = Application(connections, MemoryStore(), lambda profile: Api(profile, httpx.MockTransport(server)))
    app.login('operator', PASSWORD, 'test')
    return app, server, tmp_path / 'template.json'


def plan(app, path, **kwargs):
    return template_workflow.plan(app, vmid=40000, node='pve', request_id='template-review', review_file=path,
        **{'confirmation': '40000/test', 'conversion_acknowledged': True, 'guest_prepared': True, **kwargs})


def test_template_review_keeps_confirmation_and_manifest_across_replay(flow):
    app, server, path = flow
    assert plan(app, path)['exit_code'] == 0
    assert path.stat().st_mode & 0o777 == 0o600
    assert not any('/actions/' in str(request.url) for request in server.calls)
    confirmed = []
    for _ in range(2):
        assert template_workflow.execute(app, path, confirmed.append)['exit_code'] == 0
    posts = [request for request in server.calls if '/actions/' in str(request.url)]
    assert len(posts) == 2 and posts[0].content == posts[1].content
    assert posts[0].url.path.endswith('/actions/template')
    payload = json.loads(posts[0].content)
    assert payload['confirmation'] == '40000/test' and payload['conversion_acknowledged'] is True
    assert payload['expected_resources_digest'] == 'sha256:' + 'b' * 64
    assert '템플릿 전환' in confirmed[0]['action'] and confirmed[0]['review']['observed_before']['volumes']


@pytest.mark.parametrize('kwargs', [{'confirmation': '40001/test'}, {'confirmation': '40000/other'},
                                   {'guest_prepared': False}, {'conversion_acknowledged': False}, {'conversion_acknowledged': 1}])
def test_wrong_identity_or_missing_ack_never_creates_review(flow, kwargs):
    app, _, path = flow
    with pytest.raises(ClientError):
        plan(app, path, **kwargs)
    assert not path.exists()


def test_template_timeout_never_resends(flow):
    app, server, path = flow
    plan(app, path)
    server.timeout_mutation = True
    with pytest.raises(ClientError) as failure:
        template_workflow.execute(app, path, lambda _: None)
    assert failure.value.code == 'MUTATION_UNCONFIRMED'
    assert len([request for request in server.calls if '/actions/' in str(request.url)]) == 1


def test_template_parser():
    args = cli.parser().parse_args(['vm', 'template', 'plan', '40000', '--node', 'pve', '--confirmation', '40000/test',
        '--ack-conversion', '--guest-prepared', '--request-id', 'template-review', '--review-file', '/tmp/template-review.json'])
    assert args.action == 'template' and args.ack_conversion and args.confirmation == '40000/test'
