from copy import deepcopy
from difflib import unified_diff

import pytest
from pydantic import ValidationError

from app.operations.host_network.domain import (
    BridgeChange, BridgeError, BridgeRequest, assert_pending_diff, make_review,
    mutation_body, network_request_allowed, observe_configuration, vlan_ranges,
)


def bridge(**patch):
    return {'iface': 'vmbr40', 'type': 'bridge', 'families': ['inet'], 'method': 'manual',
            'bridge_ports': 'eno2', 'bridge_stp': 'off', 'bridge_fd': '0',
            'autostart': 1, 'active': 1, **patch}


def snapshot(row=None, changes=''):
    return {'interfaces': [
        {'iface': 'vmbr0', 'type': 'bridge', 'address': '192.0.2.2', 'gateway': '192.0.2.1', 'active': 1},
        *([row] if row else []),
    ], 'changes': changes}


def review(row=None, **change):
    model = BridgeChange(mode='update' if row else 'create', vlan_aware=True, vlan_ids='10 20-30', **change)
    return make_review(node_id='node1', bridge_id='vmbr40', change=model, snapshot=snapshot(row))


def diff(before, after):
    return ''.join(unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile='/etc/network/interfaces', tofile='/etc/network/interfaces.new', fromfiledate='before', tofiledate='after'))


OLD = 'auto vmbr40\niface vmbr40 inet manual\n\tbridge-ports eno2\n\tbridge-stp off\n\tbridge-fd 0\n'
NEW = OLD + '\tbridge-vlan-aware yes\n\tbridge-vids 10 20-30\n'


def test_vlan_ranges_are_canonical_and_not_an_arbitrary_command():
    assert vlan_ranges('20-30 10 25 11-19') == '10-30'
    assert vlan_ranges('4094 1') == '1 4094'
    for invalid in ('0', '4095', '20-10', '10,20', '10;id', '', '01', '1-40940'):
        with pytest.raises(ValueError):
            vlan_ranges(invalid)


@pytest.mark.parametrize('patch', [
    {'address': '192.0.2.3'}, {'gateway6': '2001:db8::1'}, {'method': 'dhcp'},
    {'method6': 'auto'}, {'families': ['inet', 'inet6']}, {'options': ['post-up sensitive-command']},
    {'type': 'OVSBridge'}, {'bridge_ports': ['eno2']}, {'bridge_vlan_aware': 'unknown'},
])
def test_management_or_unsupported_bridge_is_rejected_without_exposing_configuration(patch):
    with pytest.raises(BridgeError) as failure:
        review(bridge(**patch))
    assert '192.0.2.3' not in str(failure.value.to_detail())
    assert 'sensitive-command' not in str(failure.value.to_detail())


def test_existing_pending_changes_are_never_adopted():
    with pytest.raises(BridgeError, match='대기 변경'):
        make_review(node_id='node1', bridge_id='vmbr40', change=BridgeChange(mode='create'),
                    snapshot=snapshot(changes='private host diff'))


def test_review_displays_only_target_and_hashes_other_host_configuration():
    plan = review(bridge())
    assert plan['desired']['ports'] == ['eno2']
    assert '192.0.2.2' not in str(plan)
    assert plan['confirmation'] == 'node1/vmbr40/update'
    assert review(bridge(active=0, exists=0, priority=99))['review_digest'] == plan['review_digest']


def test_staged_update_preserves_other_interfaces_and_original_target_options():
    plan = review(bridge())
    row = bridge(bridge_vlan_aware=1, bridge_vids='10 20-30')
    observed = observe_configuration(snapshot=snapshot(row, diff(OLD, NEW)), review=plan, staged=True)
    assert observed['pending_changes'] is True
    assert observed['guest_connectivity_verified'] is False
    assert observed['kernel_vlan_table_verified'] is False
    final = observe_configuration(snapshot=snapshot(row), review=plan, staged=False)
    assert final['configuration']['active'] is True
    for altered in (bridge(bridge_vlan_aware=1, bridge_vids='10 20-30', bridge_ports='eno3'),
                    bridge(bridge_vlan_aware=1, bridge_vids='10 20-30', mtu=9000)):
        with pytest.raises(BridgeError, match='설정이 검토와 다릅니다'):
            observe_configuration(snapshot=snapshot(altered, diff(OLD, NEW)), review=plan, staged=True)


def test_creation_has_no_uplink_and_requires_both_exact_diff_and_new_configuration():
    plan = review()
    text = NEW.replace('eno2', 'none')
    row = bridge(bridge_ports='', bridge_vlan_aware=1, bridge_vids='10 20-30')
    result = observe_configuration(snapshot=snapshot(row, diff('', text)), review=plan, staged=True)
    assert result['configuration']['ports'] == []
    with pytest.raises(BridgeError):
        observe_configuration(snapshot=snapshot(row, diff('', text.replace('none', 'eno2'))), review=plan, staged=True)


def test_other_interface_change_blocks_reload_even_with_allowed_vlan_diff():
    plan = review(bridge())
    current = snapshot(bridge(bridge_vlan_aware=1, bridge_vids='10 20-30'), diff(OLD, NEW))
    current['interfaces'][0]['bridge_vlan_aware'] = 1
    with pytest.raises(BridgeError, match='다른 interface'):
        observe_configuration(snapshot=current, review=plan, staged=True)


@pytest.mark.parametrize('new_line', [
    'source /tmp/foreign', 'auto vmbr0', 'iface vmbr0 inet manual', '\taddress 192.0.2.4',
    '\tpost-up private-command', '\tbridge-ports eno3', '\tmtu 9000', '\tbridge-vids 1-4094',
])
def test_foreign_global_or_unreviewed_directives_cannot_be_reloaded(new_line):
    with pytest.raises(BridgeError):
        assert_pending_diff(diff(OLD, NEW + new_line + '\n'), review(bridge()))


@pytest.mark.parametrize('alter', [
    lambda value: value.replace('--- /etc/network/interfaces\t', '--- /tmp/other\t'),
    lambda value: value.replace('@@ -3,3 +3,5 @@', '@@ -3,3 +3,9 @@'),
    lambda value: value + '+\n',
    lambda value: value.replace('+\tbridge-vids 10 20-30\n', ''),
    lambda value: '',
])
def test_malformed_diff_cannot_be_treated_as_exact_stage(alter):
    with pytest.raises(BridgeError):
        assert_pending_diff(alter(diff(OLD, NEW)), review(bridge()))


def test_inactive_result_or_remaining_pending_cannot_be_success():
    plan = review(bridge())
    for current in (
        snapshot(bridge(bridge_vlan_aware=1, bridge_vids='10 20-30', active=0)),
        snapshot(bridge(bridge_vlan_aware=1, bridge_vids='10 20-30', active=None)),
        snapshot(bridge(bridge_vlan_aware=1, bridge_vids='10 20-30'), diff(OLD, NEW)),
    ):
        with pytest.raises(BridgeError):
            observe_configuration(snapshot=current, review=plan, staged=False)


@pytest.mark.parametrize('physical_exists', [None, 0, 1])
def test_virtual_bridge_activation_does_not_require_physical_nic_marker(physical_exists):
    plan = review(bridge())
    row = bridge(bridge_vlan_aware=1, bridge_vids='10 20-30')
    if physical_exists is not None:
        row['exists'] = physical_exists
    result = observe_configuration(snapshot=snapshot(row), review=plan, staged=False)
    assert result['configuration']['active'] is True


def test_autostart_off_does_not_claim_immediate_down():
    plan = review(bridge(), autostart=False)
    current = snapshot(bridge(bridge_vlan_aware=1, bridge_vids='10 20-30', autostart=0, active=1))
    result = observe_configuration(snapshot=current, review=plan, staged=False)
    assert result['configuration']['active'] is True
    assert result['immediate_down_verified'] is False


def test_request_requires_strict_inputs_and_node_wide_acknowledgement():
    change = BridgeChange(mode='create')
    plan = make_review(node_id='node1', bridge_id='vmbr40', change=change, snapshot=snapshot())
    payload = {**change.model_dump(), 'idempotency_key': 'test', 'expected_review_digest': plan['review_digest'],
               'confirmation': plan['confirmation'], 'acknowledge_node_reload': True}
    BridgeRequest(**payload)
    for patch in ({'acknowledge_node_reload': 1}, {'acknowledge_node_reload': False}, {'autostart': 'yes'},
                  {'bridge_ports': 'eno1'}, {'vlan_ids': '2-4094'}):
        with pytest.raises(ValidationError):
            BridgeRequest(**{**payload, **patch})


def test_request_policy_allows_only_selected_bridge_fields_and_fixed_reload():
    scope = {'nodes': ['node1'], 'host_bridges': ['vmbr40']}
    body = mutation_body(BridgeChange(mode='create', vlan_aware=True, vlan_ids='20 10'), bridge_id='vmbr40')
    assert network_request_allowed('POST', ['nodes', 'node1', 'network'], body, scope)
    assert network_request_allowed('PUT', ['nodes', 'node1', 'network'], {'regenerate-frr': 0}, scope)
    for method, path, data in [
        ('PUT', ['nodes', 'node1', 'network'], {'regenerate-frr': 1}),
        ('PUT', ['nodes', 'node1', 'network'], {}),
        ('DELETE', ['nodes', 'node1', 'network'], None),
        ('POST', ['nodes', 'node2', 'network'], body),
        ('POST', ['nodes', 'node1', 'network'], {**body, 'iface': 'vmbr0'}),
        ('POST', ['nodes', 'node1', 'network'], {**body, 'bridge_ports': 'eno1'}),
        ('POST', ['nodes', 'node1', 'network'], {**body, 'address': '192.0.2.3'}),
        ('POST', ['nodes', 'node1', 'network'], {**body, 'autostart': '1'}),
    ]:
        assert not network_request_allowed(method, path, data, scope)
    update = mutation_body(BridgeChange(mode='update'), bridge_id='vmbr40')
    assert update['delete'] == 'bridge_vids'
    assert network_request_allowed('PUT', ['nodes', 'node1', 'network', 'vmbr40'], update, scope)
    assert not network_request_allowed('PUT', ['nodes', 'node1', 'network', 'vmbr40'], {**update, 'delete': 'gateway'}, scope)


def test_duplicate_interfaces_cannot_hide_management_configuration():
    current = snapshot(bridge())
    current['interfaces'].append(deepcopy(current['interfaces'][0]))
    with pytest.raises(BridgeError):
        make_review(node_id='node1', bridge_id='vmbr40', change=BridgeChange(mode='update'), snapshot=current)
