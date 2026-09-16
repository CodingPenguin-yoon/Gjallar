"""Fresh provider observations gate the first mutation without replacing history."""

import asyncio
from dataclasses import replace
from unittest.mock import Mock

import pytest

from app.jobs.artifacts import read_artifact_text
from app.proxmox.inventory import FakeProxmoxInventoryAdapter, LiveProxmoxInventoryAdapter
from app.proxmox.models import InventoryAvailability, InventorySourceAvailability
from app.vm_create import application
from app.workloads.inventory import WorkloadInventoryQuery, WorkloadInventoryUnavailableError


def _review(ip_mode="static"):
    adapter = FakeProxmoxInventoryAdapter()
    payload = {
        "job_id": "job-fresh-create", "bridge_id": "vmbr0",
        "static_ip": "192.168.2.142", "prefix": 24, "gateway": "192.168.2.1",
        "ip_mode": ip_mode,
    }
    plan = application.build_preview_plan("draft-fresh-create", payload, inventory_adapter=adapter)
    payload.update({
        "plan_artifact_id": plan.review_confirm["plan_artifact_id"],
        "review_summary_checksum": plan.review_confirm["review_summary_checksum"],
        "yellow_risk_acknowledged": True, "proxmox_mutation_acknowledged": True,
    })
    return adapter, payload, plan


@pytest.mark.parametrize("change", ["template", "vmid", "bridge", "storage", "offline", "partial", "unavailable"])
@pytest.mark.parametrize("ip_mode", ["static", "dhcp"])
def test_fresh_change_blocks_mutation_and_closes_pre_dispatch_coordination(monkeypatch, change, ip_mode):
    from app.operations.facade import get_operation
    from app.operations.target_lock import acquire_target_operation_lock, release_target_operation_lock

    adapter, payload, plan = _review(ip_mode)
    original = adapter.snapshot()
    snapshot = original
    if change == "template":
        snapshot = replace(snapshot, templates=())
    elif change == "vmid":
        snapshot = replace(snapshot, vms=(*snapshot.vms, replace(snapshot.vms[0], vmid=plan.vmid)))
    elif change in {"bridge", "storage", "offline"}:
        changes = {"networks": ()} if change == "bridge" else {"storage": ()} if change == "storage" else {"status": "offline"}
        snapshot = replace(snapshot, nodes=tuple(
            replace(node, **changes) if node.node_id == plan.target_node_id else node for node in snapshot.nodes
        ))
    elif change == "partial":
        snapshot = replace(snapshot, availability=InventoryAvailability(sources=(
            InventorySourceAvailability(source="vm_config", expected_targets=1, observed_targets=0, failed_targets=("vm",)),
        )))
    observer = Mock(side_effect=[original, RuntimeError("provider unavailable") if change == "unavailable" else snapshot])
    monkeypatch.setattr(adapter, "snapshot", observer)
    before = [(a.artifact_id, read_artifact_text(a)) for a in plan.artifacts]
    factory, runner = Mock(), Mock()
    monkeypatch.setattr(application, "run_proxmox_create", runner)
    with pytest.raises(application.VmCreateApplicationError) as error:
        asyncio.run(application.execute_proxmox_create(
            plan.draft_id, payload, actor=None, inventory_adapter=adapter, mutation_client_factory=factory,
        ))
    assert error.value.status_code == (503 if change in {"partial", "unavailable"} else 409)
    assert error.value.detail["side_effects"] == []
    factory.assert_not_called()
    runner.assert_not_called()
    assert observer.call_count == 2
    assert before == [(a.artifact_id, read_artifact_text(a)) for a in plan.artifacts]
    assert get_operation(plan.job_id)["operation"]["status"] == "failed"
    # No mutation happened: a new operation can acquire the target again.
    handle = acquire_target_operation_lock(
        target_type="proxmox_vm", target_id=f"vmid:{plan.vmid}", owner_id="next-operation", operation_type="vm_create",
    )
    release_target_operation_lock(handle)


def test_unrelated_vm_state_does_not_invalidate_approved_plan(monkeypatch):
    adapter, payload, plan = _review()
    snapshot = adapter.snapshot()
    snapshot = replace(snapshot, vms=tuple(replace(vm, status="stopped") for vm in snapshot.vms))
    monkeypatch.setattr(adapter, "snapshot", lambda: snapshot)
    application._validate_fresh_create_state(plan, payload, adapter)


def test_fresh_live_snapshot_bypasses_warm_detail_cache_and_keeps_read_cache():
    disk_size = [50]
    fail = [False]
    config_calls = []

    def get(path, **kwargs):
        if fail[0]:
            raise RuntimeError("provider unavailable")
        if path == "/nodes/node-a/qemu":
            return [{"node": "node-a", "vmid": 9001, "name": "ubuntu-template", "template": 1, "status": "stopped"}]
        if path == "/nodes":
            return [{"node": "node-a", "status": "online"}]
        if path.endswith("/config"):
            config_calls.append(path)
            return {"scsi0": f"local-lvm:base-9001-disk-0,size={disk_size[0]}G", "ide2": "local-lvm:cloudinit", "agent": "1"}
        return []

    adapter = LiveProxmoxInventoryAdapter(
        api_url="https://example.invalid", token_id="test", token_secret="test", request_get=get, cache_ttl_seconds=60,
    )
    old = adapter.snapshot()
    disk_size[0] = 80
    fresh = WorkloadInventoryQuery(adapter).require_fresh_mutation_adapter()
    assert old.templates[0].disk_gb == 50
    assert fresh.list_templates()[0].disk_gb == 80
    assert adapter.snapshot() is old
    assert len(config_calls) == 2
    fail[0] = True
    with pytest.raises(WorkloadInventoryUnavailableError):
        WorkloadInventoryQuery(adapter).require_fresh_mutation_adapter()
    # No fallback to the warm cache; already captured request views stay fixed.
    assert fresh.list_templates()[0].disk_gb == 80
