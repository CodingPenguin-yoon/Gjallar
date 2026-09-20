import pytest
from gjallar_client import cli
from gjallar_client.console_workflow import guide
from gjallar_client.errors import ClientError


class App:
    connection_name = 'test'
    connections = None

    def __init__(self):
        self.connections = self
        self.calls = []
        self.target = {'node_id': 'node1', 'vmid': 40000}

    def get(self, name):
        return name, {'origin': 'https://gjallar.example.test', 'id': 'profile'}

    def request(self, path, **kwargs):
        self.calls.append((path, kwargs))
        return {'data': {'target': self.target, 'warnings': ['guest input changes state']}, 'ok': True}


def test_console_guide_contains_only_web_target_not_credentials():
    app = App()
    result = guide(app, vmid=40000, node='node1')
    assert app.calls == [('nodes/node1/vms/40000/console', {'operator': True})]
    assert result['data']['web_url'] == 'https://gjallar.example.test/instances/40000#console'
    assert '브라우저에서 로그인' in result['message']
    args = cli.parser().parse_args(['vm', 'console', '40000', '--node', 'node1'])
    assert args.vmid == 40000 and args.action == 'console'


def test_wrong_target_cannot_be_presented_as_console_guide():
    app = App()
    app.target['vmid'] = 40001
    with pytest.raises(ClientError):
        guide(app, vmid=40000, node='node1')
