import pytest
from pydantic import ValidationError

from app.operations.vm_network.domain import NetworkError, NetworkRequest, check_expected, observed_network, parse_net0, replace_network

NET = 'virtio=02:00:00:00:00:01,bridge=vmbr0,firewall=1,rate=10,mtu=1500,queues=2'
CONFIG = {'name': 'test-vm', 'net0': NET, 'digest': 'a' * 40}
SNAPSHOT = {'pending_changes': False, 'interfaces': [
    {'iface': 'vmbr0', 'type': 'bridge', 'active': 1, 'exists': 1},
    {'iface': 'vmbr1', 'type': 'bridge', 'active': 1, 'exists': 1, 'bridge_vlan_aware': 1},
]}


def request(**kwargs):
    return NetworkRequest(idempotency_key='network-test', expected_digest='a' * 40, expected_name='test-vm',
        expected_net0=NET, **{'bridge_id': 'vmbr1', 'vlan_tag': 100, **kwargs})


def test_mac_model_and_unrelated_options_preserved_and_tag_removed():
    before = parse_net0(NET)
    changed = replace_network(NET, 'vmbr1', 100)
    assert parse_net0(changed) == {**before, 'bridge': 'vmbr1', 'tag': '100'}
    assert replace_network(changed, 'vmbr0', None) == NET
    review = observed_network(CONFIG, {'status': 'stopped'}, [], SNAPSHOT)
    check_expected(review, request())


@pytest.mark.parametrize('net', [NET + ',trunks=10;20', NET + ',bridge=vmbr1', 'virtio=oops,bridge=vmbr0',
    'virtio=02:00:00:00:00:01', NET + ',tag=4095', NET + ',tag=0', NET + ',foo', NET + ',rate='])
def test_ambiguous_or_unsupported_nic_refused(net):
    with pytest.raises(NetworkError):
        parse_net0(net)


@pytest.mark.parametrize('patch,status,pending,snapshot,code', [
    ({'template': 1}, 'stopped', [], SNAPSHOT, 'LOCKED_OR_TEMPLATE'),
    ({'lock': 'backup'}, 'stopped', [], SNAPSHOT, 'LOCKED_OR_TEMPLATE'),
    ({}, 'running', [], SNAPSHOT, 'NOT_STOPPED'),
    ({}, 'stopped', [{'key': 'net0', 'pending': NET}], SNAPSHOT, 'PENDING_CONFIG'),
    ({}, 'stopped', [], {**SNAPSHOT, 'pending_changes': True}, 'HOST_PENDING'),
    ({}, 'stopped', [], {**SNAPSHOT, 'interfaces': []}, 'BRIDGE_UNAVAILABLE'),
    ({'digest': None}, 'stopped', [], SNAPSHOT, 'DIGEST_UNAVAILABLE'),
])
def test_observation_rejects_unsafe_state(patch, status, pending, snapshot, code):
    with pytest.raises(NetworkError) as failure:
        observed_network({**CONFIG, **patch}, {'status': status}, pending, snapshot)
    assert failure.value.code == 'VM_NETWORK_' + code


def test_vlan_and_bridge_selection_fail_closed():
    before = observed_network(CONFIG, {'status': 'stopped'}, [], SNAPSHOT)
    for desired, code in [(request(bridge_id='missing'), 'BRIDGE_UNAVAILABLE'),
                          (request(bridge_id='vmbr0'), 'VLAN_UNSUPPORTED'),
                          (request(bridge_id='vmbr0', vlan_tag=None), 'NO_CHANGE')]:
        with pytest.raises(NetworkError) as failure:
            check_expected(before, desired)
        assert failure.value.code == 'VM_NETWORK_' + code
    with pytest.raises(NetworkError, match='검토 후'):
        check_expected(before, request().model_copy(update={'expected_net0': NET + ',link_down=1'}))


@pytest.mark.parametrize('tag', [0, 4095, True, '100', -1])
def test_vlan_strict_bounds(tag):
    with pytest.raises(ValidationError):
        request(vlan_tag=tag)


def test_virtual_bridge_active_without_physical_exists_attribute_is_supported():
    snapshot = {'pending_changes': False, 'interfaces': [
        {'iface': 'vmbr0', 'type': 'bridge', 'active': 1},
        {'iface': 'vmbr1', 'type': 'bridge', 'active': 1, 'bridge_vlan_aware': 1},
        {'iface': 'vmbr2', 'type': 'bridge', 'active': 0},
        {'iface': 'ovs0', 'type': 'OVSBridge', 'active': 1},
    ]}
    before = observed_network(CONFIG, {'status': 'stopped'}, [], snapshot)
    assert [row['bridge_id'] for row in before['bridges']] == ['vmbr0', 'vmbr1']
    check_expected(before, request())
