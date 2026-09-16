"""IP evidence distinguishes observed occupancy from acknowledged uncertainty."""

import asyncio
from dataclasses import replace
from unittest.mock import Mock

import pytest

from app.jobs.artifacts import read_artifact_text
from app.proxmox.inventory import FakeProxmoxInventoryAdapter
from app.proxmox.models import InventoryAvailability, InventorySourceAvailability
from app.vm_create import application, preflight
from app.vm_create.ip_probe import IpProbeResult
from app.workloads.inventory import ObservedInventoryAdapter


IP = "192.168.2.222"


def adapter_with(*, failed=(), conflict=False):
    snapshot = FakeProxmoxInventoryAdapter().snapshot()
    vms = snapshot.vms
    if conflict:
        vms = (replace(vms[0], ip_addresses=(IP,)), *vms[1:])
    return ObservedInventoryAdapter(replace(
        snapshot, vms=vms,
        availability=InventoryAvailability(sources=(InventorySourceAvailability(
            source="guest_agent", expected_targets=2,
            observed_targets=2-len(failed), failed_targets=failed,
        ),)),
    ), is_test_fixture=True)


def request_for(adapter):
    template = adapter.list_templates()[0]
    return {
        "job_id": "job-ip-observation", "creation_mode": "template",
        "template_node_id": template.node_id, "template_vmid": template.vmid,
        "target_node_id": template.node_id, "bridge_id": "vmbr0", "ip_mode": "static",
        "static_ip": IP, "prefix": 24, "gateway": "192.168.2.1",
        "access": {"cloud_init_user": "operator"},
    }


@pytest.mark.parametrize("status", ["reply", "no_reply", "unavailable"])
@pytest.mark.parametrize("failed", [(), ("node:101", "node:900")])
@pytest.mark.parametrize("conflict", [False, True])
def test_inventory_and_ping_each_block_observed_occupancy(monkeypatch, status, failed, conflict):
    adapter = adapter_with(failed=failed, conflict=conflict)
    probe = Mock(return_value=IpProbeResult(status))
    monkeypatch.setattr(preflight, "probe_ipv4", probe)
    draft = application.build_draft_from_payload("ip-draft", request_for(adapter), inventory_adapter=adapter)
    result = preflight.run_preflight(draft, profiles={}, inventory_adapter=adapter)
    check = next(check for check in result.checks if check.code == "static_ip_available")
    occupied = conflict or status == "reply"
    assert result.risk_level == ("red" if occupied else "yellow")
    assert check.detail["result"] == ("in_use" if occupied else "unverified")
    assert check.detail["ping"]["status"] == status
    assert check.detail["inventory"]["failed_targets"] == list(failed)
    assert bool(check.detail["conflicts"]) == conflict
    probe.assert_called_once_with(IP)


def test_dhcp_does_not_probe_any_address(monkeypatch):
    adapter = adapter_with(failed=("node:101",))
    probe = Mock(side_effect=AssertionError("DHCP has no operator-chosen address to probe"))
    monkeypatch.setattr(preflight, "probe_ipv4", probe)
    draft = application.build_draft_from_payload(
        "dhcp-ip", {**request_for(adapter), "ip_mode": "dhcp"}, inventory_adapter=adapter,
    )
    assert preflight.run_preflight(draft, profiles={}, inventory_adapter=adapter).risk_level == "yellow"
    probe.assert_not_called()


@pytest.mark.parametrize("after_status", ["no_reply", "unavailable"])
def test_uncertainty_changes_preserve_exact_plan_and_require_ack(monkeypatch, after_status):
    original = adapter_with(failed=("node:101", "node:900"))
    current = adapter_with(failed=())
    request = request_for(original)
    plan_response = asyncio.run(application.plan_draft(
        "ip-review", request, actor=None, inventory_adapter=original,
    )).data
    check = next(c for c in plan_response["preflight"]["checks"] if c["code"] == "static_ip_available")
    assert check["detail"]["result"] == "unverified"
    review = plan_response["review_confirm"]
    artifacts = [a for a in plan_response["artifacts"] if a["type"] in ("plan", "review_summary")]
    contents = [read_artifact_text(a) for a in artifacts]
    request.update(plan_artifact_id=review["plan_artifact_id"],
                   review_summary_checksum=review["review_summary_checksum"],
                   yellow_risk_acknowledged=False)
    monkeypatch.setattr(preflight, "probe_ipv4", lambda address: IpProbeResult(after_status))
    blocked = asyncio.run(application.approve_draft(
        "ip-review", request, actor=None, inventory_adapter=current,
    )).data
    assert not blocked["can_execute"]
    assert blocked["requires_yellow_ack"]
    request["yellow_risk_acknowledged"] = True
    approved = asyncio.run(application.approve_draft(
        "ip-review", request, actor=None, inventory_adapter=current,
    )).data
    assert approved["can_execute"]
    assert contents == [read_artifact_text(a) for a in artifacts]
    plan = application.build_preview_plan("ip-review", request, inventory_adapter=current)
    application._validate_fresh_create_state(plan, request, original)


@pytest.mark.parametrize("change", ["ping_reply", "inventory_conflict"])
def test_new_occupancy_at_final_recheck_prevents_first_mutation(monkeypatch, change):
    adapter = FakeProxmoxInventoryAdapter()
    request = request_for(adapter)
    plan = application.build_preview_plan("ip-fresh", request, inventory_adapter=adapter)
    request.update(plan_artifact_id=plan.review_confirm["plan_artifact_id"],
                   review_summary_checksum=plan.review_confirm["review_summary_checksum"],
                   yellow_risk_acknowledged=True, proxmox_mutation_acknowledged=True)
    if change == "ping_reply":
        probe = Mock(side_effect=[IpProbeResult("no_reply"), IpProbeResult("reply")])
    else:
        probe = Mock(return_value=IpProbeResult("no_reply"))
        snapshot = adapter.snapshot()
        occupied = replace(snapshot, vms=(replace(snapshot.vms[0], ip_addresses=(IP,)), *snapshot.vms[1:]))
        monkeypatch.setattr(adapter, "snapshot", Mock(side_effect=[snapshot, occupied]))
    monkeypatch.setattr(preflight, "probe_ipv4", probe)
    factory, runner = Mock(), Mock()
    monkeypatch.setattr(application, "run_proxmox_create", runner)
    with pytest.raises(application.VmCreateApplicationError) as error:
        asyncio.run(application.execute_proxmox_create(
            "ip-fresh", request, actor=None, inventory_adapter=adapter, mutation_client_factory=factory,
        ))
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "PROXMOX_CREATE_STATE_CHANGED"
    factory.assert_not_called()
    runner.assert_not_called()
    assert probe.call_count == 2
