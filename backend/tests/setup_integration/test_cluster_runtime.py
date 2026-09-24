import pytest

from app.setup_integration.contracts import FEATURES, Scope, SetupError
from app.setup_integration.runtime import ManagedRequests


@pytest.fixture
def cluster(monkeypatch):
    calls, replies = [], {}
    class Transport:
        def __init__(self, *args):
            pass
        def request(self, method, path, **kwargs):
            calls.append((method, path, kwargs.get('data')))
            return replies.get(path)
    monkeypatch.setattr('app.setup_integration.transport.ProxmoxSetupTransport', Transport)
    client = ManagedRequests({'secret': 'synthetic', 'configuration': {
        'endpoint': 'https://pve.example.test', 'ca_pem': '', 'token_id': 'root@pam!test',
        'access_mode': 'cluster', 'features': sorted(FEATURES), 'scope': Scope().model_dump()}})
    return client, calls, replies


def test_inventory_includes_resources_added_after_registration(cluster):
    client, _, replies = cluster
    for path, rows in {
        '/nodes': [{'node': 'new-node'}], '/nodes/new-node/qemu': [{'vmid': 65001}],
        '/nodes/new-node/storage': [{'storage': 'new-store'}], '/nodes/new-node/network': [{'iface': 'vmbr99'}],
        '/storage': [{'storage': 'new-store'}], '/cluster/resources': [{'vmid': 65001}],
    }.items():
        replies[path] = rows
        assert client.request('GET', path, data={'type': 'vm'} if path == '/cluster/resources' else None) == rows
    replies['/nodes'] = {'invalid': 'list'}
    with pytest.raises(SetupError):
        client.request('GET', '/nodes')


@pytest.mark.parametrize('method,path,data', [
    ('POST', '/nodes/new-node/qemu/65001/status/start', {}),
    ('PUT', '/nodes/new-node/qemu/65001/config', {'cores': 4, 'memory': 8192, 'digest': 'a'*40}),
    ('POST', '/nodes/new-node/qemu/65001/template', {}),
    ('POST', '/nodes/new-node/qemu/65001/vncproxy', {'websocket': 1}),
    ('DELETE', '/nodes/new-node/qemu/65001', {'purge': 0, 'destroy-unreferenced-disks': 0}),
    ('GET', '/nodes/new-node/qemu/65001/config?current=1', None),
    ('GET', '/cluster/nextid?vmid=65001', None),
    ('GET', '/nodes/new-node/storage/new-store/content?content=backup&vmid=65001', None),
    ('GET', '/nodes/new-node/vzdump/defaults?storage=new-store', None),
    ('GET', '/access/permissions?path=%2Fvms%2F65001', None),
    ('GET', '/nodes/new-node/qemu/65001/rrddata?timeframe=day&cf=AVERAGE', None),
    ('POST', '/nodes/new-node/qemu/65001/clone', {'newid': 65002, 'name': 'new-vm', 'target': 'other-node', 'storage': 'new-store', 'full': 1}),
])
def test_future_targets_use_existing_operation_policies(cluster, method, path, data):
    client, calls, _ = cluster
    client.request(method, path, data=data)
    assert len(calls) == 1


@pytest.mark.parametrize('method,path,data', [
    ('POST', '/nodes/new-node/execute', {'command': 'sh'}),
    ('POST', '/nodes/new-node/qemu/65001/agent/exec', [('command', 'sh')]),
    ('PUT', '/nodes/new-node/qemu/65001/config', {'args': '-something'}),
    ('DELETE', '/storage/new-store', {}),
    ('DELETE', '/nodes/new-node/qemu/65001', {'purge': 1}),
    ('GET', '/nodes/new-node/qemu/65001/rrddata?timeframe=day&cf=MAX', None),
])
def test_cluster_access_does_not_bypass_operation_field_validation(cluster, method, path, data):
    client, calls, _ = cluster
    with pytest.raises(SetupError):
        client.request(method, path, data=data)
    assert not calls
