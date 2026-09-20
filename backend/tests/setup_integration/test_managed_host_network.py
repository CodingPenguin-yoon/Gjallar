import pytest
from pydantic import ValidationError

from app.operations.host_network.domain import BridgeChange, mutation_body
from app.proxmox.client import ProxmoxMutationError
from app.setup_integration.contracts import RegistrationIntent, SetupError
from app.setup_integration.planning import ROLE_PRIVILEGES, acl_plan, authority_warnings
from app.setup_integration.runtime import managed_mutation_client


@pytest.fixture
def managed(monkeypatch):
    calls = []
    class Transport:
        def __init__(self, *args):
            pass
        def request(self, method, path, *, data=None, response_metadata=False, **kwargs):
            calls.append((method, path, data))
            if path == '/access/permissions':
                return {data['path']: {'Sys.Modify': 1, 'Sys.Audit': 1, 'SDN.Audit': 1}}
            if method == 'GET' and path.endswith('/network'):
                rows = [{'iface': 'vmbr0'}, {'iface': 'vmbr40'}, {'iface': 'eno1'}]
                return {'data': rows, 'changes': 'sensitive staged diff'} if response_metadata else rows
            return None
    monkeypatch.setattr('app.setup_integration.transport.ProxmoxSetupTransport', Transport)
    selection = {'secret': 'synthetic', 'configuration': {
        'endpoint': 'https://pve.example.test', 'ca_pem': '', 'token_id': 'test@pve!test',
        'features': ['read'], 'scope': {'nodes': ['node1'], 'vmids': [101], 'storages': [], 'bridges': ['vmbr0']},
    }}
    return managed_mutation_client(selection), selection, calls


def test_explicit_host_network_capability_does_not_expand_vm_network_observation(managed):
    client, selection, calls = managed
    change = BridgeChange(mode='create', vlan_aware=True, vlan_ids='10 20-30')
    with pytest.raises(ProxmoxMutationError):
        client.stage_host_bridge(node='node1', bridge='vmbr40', change=change)
    with pytest.raises(ProxmoxMutationError):
        client.get_host_network_snapshot(node='node1')
    assert not calls
    selection['configuration']['features'] = ['read', 'host_network']
    selection['configuration']['scope']['host_bridges'] = ['vmbr40']
    client.stage_host_bridge(node='node1', bridge='vmbr40', change=change)
    client.reload_host_network(node='node1')
    assert calls == [('POST', '/nodes/node1/network', mutation_body(change, bridge_id='vmbr40')),
                     ('PUT', '/nodes/node1/network', {'regenerate-frr': 0})]
    assert len(client.get_host_network_snapshot(node='node1')['interfaces']) == 3
    original = client.get_node_network_snapshot(node='node1')
    assert original == {'interfaces': [{'iface': 'vmbr0'}], 'pending_changes': True}
    assert 'sensitive' not in str(original)
    permissions = client.get_host_network_permissions(node='node1')
    assert 'SDN.Audit' in permissions['/sdn/zones/localnetwork']
    count = len(calls)
    for method, path, data in [
        ('DELETE', '/nodes/node1/network', {}),
        ('DELETE', '/nodes/node1/network/vmbr40', {}),
        ('POST', '/nodes/node2/network', mutation_body(change, bridge_id='vmbr40')),
        ('POST', '/nodes/node1/network', mutation_body(change, bridge_id='vmbr0')),
        ('PUT', '/nodes/node1/network', {'regenerate-frr': 1}),
        ('PUT', '/nodes/node1/network/vmbr40', {'type': 'bridge', 'address': '192.0.2.2'}),
        ('GET', '/nodes/node1/network/vmbr0', None),
        ('PUT', '/nodes/node1/qemu/101/config', {'net0': 'virtio,bridge=vmbr40'}),
        ('POST', '/nodes/node1/status', {'command': 'reboot'}),
    ]:
        with pytest.raises(SetupError):
            client._request(method, path, data=data)
    assert len(calls) == count


def test_role_and_scope_disclose_node_wide_authority_without_granting_guest_changes():
    intent = RegistrationIntent(endpoint='https://pve.example.test', owner='test@pve', expires_at=2000000000,
        features=['read', 'host_network'], scope={'nodes': ['node1'], 'host_bridges': ['vmbr40']})
    acls = acl_plan(intent)
    assert acls == [
        {'path': '/nodes/node1', 'role': 'GjallarNodeReadV1', 'propagate': 1},
        {'path': '/nodes/node1', 'role': 'GjallarHostNetworkV1', 'propagate': 1},
        {'path': '/sdn/zones/localnetwork', 'role': 'GjallarBridgeReadV1', 'propagate': 1},
    ]
    assert ROLE_PRIVILEGES['GjallarHostNetworkV1'] == ['Sys.Modify']
    assert 'Sys.Modify' in authority_warnings(intent)[0]
    for patch in ({'features': ['read']}, {'scope': {'nodes': ['node1']}},
                  {'scope': {'nodes': ['node1'], 'host_bridges': ['eno1']}}):
        with pytest.raises(ValidationError):
            RegistrationIntent(**{**intent.model_dump(), **patch})
