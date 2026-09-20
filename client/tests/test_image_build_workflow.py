import json

import httpx
import pytest

from gjallar_client import cli, image_build_workflow
from gjallar_client.api import Api
from gjallar_client.application import Application
from gjallar_client.connections import Connections
from gjallar_client.errors import ClientError
from gjallar_client.sessions import MemoryStore
from test_cli_workflows import WorkflowServer
from test_client import PASSWORD

CONFIG = dict(image_id='alma-9-test', name='alma-test', storage_id='target', staging_storage_id='stage', bridge_id='vmbr1')


class BuildServer(WorkflowServer):
    def __call__(self, request):
        if request.url.path.endswith('/image-build') and request.method == 'GET':
            self.calls.append(request)
            assert dict(request.url.params) == CONFIG
            return httpx.Response(200, json={'ok': True, 'data': {
                'target': {'node_id': 'pve', 'vmid': 40000, 'name': CONFIG['name']},
                'observed_before': CONFIG, 'review_digest': 'sha256:' + 'b' * 64,
                'warnings': ['부분 자원 보존'],
            }})
        return super().__call__(request)


@pytest.fixture
def flow(tmp_path):
    connections = Connections(tmp_path / 'config')
    connections.add('test', 'http://127.0.0.1:8000')
    server = BuildServer()
    app = Application(connections, MemoryStore(), lambda profile: Api(profile, httpx.MockTransport(server)))
    app.login('operator', PASSWORD, 'test')
    return app, server, tmp_path / 'image.json'


def plan(app, path, **kwargs):
    return image_build_workflow.plan(app, vmid=40000, node='pve', configuration=CONFIG,
        request_id='image-review', review_file=path, **{'confirmation': '40000/alma-test', 'acknowledged': True, **kwargs})


def test_image_review_preserves_configuration_and_same_request(flow):
    app, server, path = flow
    plan(app, path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert not any('/actions/' in str(row.url) for row in server.calls)
    confirms = []
    for _ in range(2):
        assert image_build_workflow.execute(app, path, confirms.append)['exit_code'] == 0
    posts = [row for row in server.calls if '/actions/' in str(row.url)]
    assert len(posts) == 2 and posts[0].content == posts[1].content
    assert posts[0].url.path.endswith('/actions/image-build')
    body = json.loads(posts[0].content)
    assert all(body[key] == value for key, value in CONFIG.items())
    assert body['image_build_acknowledged'] is True
    assert confirms[0]['review']['warnings'] == ['부분 자원 보존']


@pytest.mark.parametrize('patch', [{'confirmation': '40001/alma-test'}, {'confirmation': '40000/other'},
                                   {'acknowledged': False}, {'acknowledged': 1}])
def test_incomplete_image_confirmation_is_rejected(flow, patch):
    app, _, path = flow
    with pytest.raises(ClientError): plan(app, path, **patch)
    assert not path.exists()


def test_image_timeout_never_repeats_post(flow):
    app, server, path = flow
    plan(app, path)
    server.timeout_mutation = True
    with pytest.raises(ClientError) as caught:
        image_build_workflow.execute(app, path, lambda _: None)
    assert caught.value.code == 'MUTATION_UNCONFIRMED'
    assert len([row for row in server.calls if '/actions/' in str(row.url)]) == 1


def test_image_parser_and_tampered_input(flow):
    args = cli.parser().parse_args(['vm', 'image-build', 'plan', '40000', '--node', 'pve', '--image-id', 'alma-9-test',
        '--name', 'alma-test', '--storage', 'target', '--staging-storage', 'stage', '--bridge', 'vmbr1',
        '--confirmation', '40000/alma-test', '--ack-image-build', '--request-id', 'image-review', '--review-file', '/tmp/image.json'])
    assert args.ack_image_build and args.stage == 'plan'
    app, server, path = flow
    plan(app, path)
    record = json.loads(path.read_text())
    record['payload']['url'] = 'https://untrusted.example/image'
    path.write_text(json.dumps(record))
    with pytest.raises(ClientError): image_build_workflow.execute(app, path, lambda _: None)
    assert not any('/actions/' in str(row.url) for row in server.calls)
