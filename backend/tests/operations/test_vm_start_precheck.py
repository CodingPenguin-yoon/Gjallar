"""Unit tests for infrastructure-free VM Start pre-check rules."""

import pytest

from app.operations.vm_start.precheck import VmStartPrecheckBlocked, evaluate_vm_start_precheck


class Inventory:
    def __init__(self, *, vms=None, templates=None):
        self.vms = list(vms or [])
        self.templates = list(templates or [])

    def list_vms(self):
        return list(self.vms)

    def list_templates(self):
        return list(self.templates)


def test_precheck_returns_exact_stopped_workload_context():
    result = evaluate_vm_start_precheck(
        Inventory(vms=[{"node_id": "node-a", "vmid": 306, "name": "app", "status": "stopped"}]),
        node_id="node-a",
        vmid=306,
        payload={"expected_name": "app", "expected_status": "stopped"},
    )

    assert result.target == {"node_id": "node-a", "vmid": 306, "name": "app"}
    assert result.observed_before["status"] == "stopped"


@pytest.mark.parametrize(
    ("inventory", "code"),
    [
        (Inventory(), "VM_START_MISSING_BLOCKED"),
        (
            Inventory(vms=[{"node_id": "node-b", "vmid": 306, "name": "app", "status": "stopped"}]),
            "VM_START_MOVED_BLOCKED",
        ),
        (
            Inventory(templates=[{"node_id": "node-a", "vmid": 306, "name": "base", "status": "stopped"}]),
            "VM_START_TEMPLATE_BLOCKED",
        ),
        (
            Inventory(vms=[{"node_id": "node-a", "vmid": 306, "name": "app", "status": "running"}]),
            "VM_START_NON_STOPPED_BLOCKED",
        ),
    ],
)
def test_precheck_reports_structured_block_reason(inventory, code):
    with pytest.raises(VmStartPrecheckBlocked) as raised:
        evaluate_vm_start_precheck(
            inventory,
            node_id="node-a",
            vmid=306,
            payload={},
        )

    assert raised.value.code == code
    assert raised.value.target["vmid"] == 306
