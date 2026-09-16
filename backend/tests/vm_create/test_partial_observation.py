"""Create distinguishes missing IP evidence from other inventory failures."""
from dataclasses import replace

import pytest

from app.proxmox.inventory import FakeProxmoxInventoryAdapter
from app.proxmox.models import InventoryAvailability, InventorySourceAvailability
from app.vm_create import application
from app.vm_create.preflight import run_preflight
from app.workloads.inventory import ObservedInventoryAdapter, WorkloadInventoryQuery, WorkloadInventoryUnavailableError


def partial(source):
    base = FakeProxmoxInventoryAdapter().snapshot()
    return ObservedInventoryAdapter(replace(base, availability=InventoryAvailability(sources=(
        InventorySourceAvailability(source=source, expected_targets=2, observed_targets=1, failed_targets=('node:101',)),
    ))), is_test_fixture=True)


def payload(adapter, mode):
    template = adapter.list_templates()[0]
    return {'creation_mode': 'template', 'template_node_id': template.node_id,
            'template_vmid': template.vmid, 'target_node_id': template.node_id,
            'bridge_id': 'vmbr0', 'ip_mode': mode,
            'static_ip': '192.168.2.222', 'prefix': 24, 'gateway': '192.168.2.1',
            'access': {'cloud_init_user': 'operator'}}


@pytest.mark.parametrize('mode,level', [('static', 'yellow'), ('dhcp', 'yellow')])
def test_guest_failure_has_explicit_mode_specific_risk(mode, level):
    adapter = partial('guest_agent')
    draft = application.build_draft_from_payload('draft-partial', payload(adapter, mode), inventory_adapter=adapter)
    result = run_preflight(draft, profiles={}, inventory_adapter=adapter)
    risk = next(r for r in result.risks if r.code == 'inventory_guest_agent_incomplete')
    assert risk.level == level
    assert risk.detail['failed_targets'] == ['node:101']
    assert result.risk_level != 'red'


@pytest.mark.parametrize('fresh', [False, True])
def test_create_guest_failure_does_not_relax_other_mutation_gate(fresh):
    query = WorkloadInventoryQuery(partial('guest_agent'))
    assert not query.require_create_adapter(fresh=fresh).snapshot().availability.complete
    with pytest.raises(WorkloadInventoryUnavailableError):
        query.require_mutation_adapter()


@pytest.mark.parametrize('source', ['storage', 'network', 'vm_config', 'vm_detail'])
@pytest.mark.parametrize('fresh', [False, True])
def test_other_incomplete_sources_block_create(source, fresh):
    adapter = partial(source)
    with pytest.raises(WorkloadInventoryUnavailableError):
        WorkloadInventoryQuery(adapter).require_create_adapter(fresh=fresh)
    draft = application.build_draft_from_payload('draft-partial', payload(adapter, 'dhcp'), inventory_adapter=adapter)
    result = run_preflight(draft, profiles={}, inventory_adapter=adapter)
    assert any(r.code == f'inventory_{source}_incomplete' and r.level == 'red' for r in result.risks)


def test_initial_create_gate_preserves_live_fresh_observer():
    from unittest.mock import Mock
    snapshot = partial('guest_agent').snapshot()
    live = Mock(source='proxmox', is_test_fixture=False)
    live.snapshot.return_value = snapshot
    live.fresh_snapshot.return_value = snapshot
    initial = WorkloadInventoryQuery(live).require_create_adapter()
    assert initial is live
    observed = WorkloadInventoryQuery(initial).require_create_adapter(fresh=True)
    assert observed.snapshot() is snapshot
    live.fresh_snapshot.assert_called_once()


@pytest.mark.parametrize('before,after', [
    (('node:101', 'node:900'), ('node:101',)),
    (('node:101',), ()),
    ((), ('node:900',)),
])
def test_dhcp_observation_changes_preserve_review_and_approval(before, after):
    import asyncio
    from app.jobs.artifacts import read_artifact_text

    def observation(failed):
        base = FakeProxmoxInventoryAdapter().snapshot()
        return ObservedInventoryAdapter(replace(base, availability=InventoryAvailability(sources=(
            InventorySourceAvailability(source='guest_agent', expected_targets=2,
                                        observed_targets=2-len(failed), failed_targets=failed),
        ))), is_test_fixture=True)

    original, current = observation(before), observation(after)
    request = {**payload(original, 'dhcp'), 'job_id': 'dhcp-changing-observation'}
    planned = asyncio.run(application.plan_draft('dhcp-review', request, actor=None, inventory_adapter=original)).data
    review = planned['review_confirm']
    artifacts = [a for a in planned['artifacts'] if a['type'] in ('plan', 'review_summary')]
    contents = [read_artifact_text(a) for a in artifacts]
    request.update(plan_artifact_id=review['plan_artifact_id'],
                   review_summary_checksum=review['review_summary_checksum'],
                   yellow_risk_acknowledged=False)
    blocked = asyncio.run(application.approve_draft('dhcp-review', request, actor=None, inventory_adapter=current)).data
    assert blocked['can_execute'] is False
    request['yellow_risk_acknowledged'] = True
    approved = asyncio.run(application.approve_draft('dhcp-review', request, actor=None, inventory_adapter=current)).data
    assert approved['can_execute'] is True
    assert contents == [read_artifact_text(a) for a in artifacts]
    plan = application.build_preview_plan('dhcp-review', request, inventory_adapter=current)
    application._validate_fresh_create_state(plan, request, original)
    assert any(r['code'] == 'dhcp_requires_discovery' for r in plan.risk_summary['yellow'])
    assert not any(r['code'] == 'inventory_guest_agent_incomplete' for r in plan.risk_summary['yellow'])


def test_static_missing_guest_observation_requires_ack_without_blocking_plan():
    adapter = partial('guest_agent')
    plan = application.build_preview_plan('static-partial', payload(adapter, 'static'), inventory_adapter=adapter)
    assert plan.risk_summary['level'] == 'yellow'
    assert any(r['code'] == 'static_ip_usage_unverified' for r in plan.risk_summary['yellow'])
    assert not any(r['code'] == 'inventory_guest_agent_incomplete' for r in plan.risk_summary['yellow'])
