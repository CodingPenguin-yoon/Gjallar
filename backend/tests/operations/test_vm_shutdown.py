"""Pure contract tests for graceful VM Shutdown."""

from __future__ import annotations

import pytest

from app.operations.vm_shutdown.domain import VmShutdownCommand, build_vm_shutdown_job_id
from app.operations.vm_shutdown.precheck import VmShutdownPrecheckBlocked, evaluate_vm_shutdown_precheck
from app.proxmox.models import VmInventory


class Inventory:
    def __init__(self, *, vms=None, templates=None) -> None:
        self._vms = list(vms or [])
        self._templates = list(templates or [])

    def list_vms(self):
        return list(self._vms)

    def list_templates(self):
        return list(self._templates)


def vm(*, vmid=306, node_id="node-a", name="app", status="running", template=False):
    return VmInventory(
        vmid=vmid,
        name=name,
        node_id=node_id,
        status=status,
        template=template,
        cpu=2,
        memory_mb=2048,
        disk_gb=20,
    )


def test_shutdown_command_has_stable_scoped_intent_and_job_identity():
    command = VmShutdownCommand.from_request(
        node_id="node/a",
        vmid=306,
        payload={"expected_name": "app", "expected_status": "running"},
        actor={"user_id": "user-1"},
    )

    assert command.stable_intent == {
        "schema": "vm_shutdown_intent.v1",
        "operation": "vm_shutdown",
        "target": {"node_id": "node/a", "vmid": 306},
        "expected": {"expected_name": "app", "expected_status": "running"},
    }
    assert build_vm_shutdown_job_id(node_id="node/a", vmid=306, idempotency_key="idem") == (
        build_vm_shutdown_job_id(node_id="node/a", vmid=306, idempotency_key="idem")
    )
    assert build_vm_shutdown_job_id(node_id="node/a", vmid=306, idempotency_key="idem").startswith(
        "vm-shutdown-node-a-306-"
    )


def test_shutdown_precheck_accepts_exact_running_non_template():
    result = evaluate_vm_shutdown_precheck(
        Inventory(vms=[vm()]),
        node_id="node-a",
        vmid=306,
        payload={"expected_name": "app", "expected_status": "running"},
    )

    assert result.target == {"node_id": "node-a", "vmid": 306, "name": "app"}
    assert result.observed_before["status"] == "running"


@pytest.mark.parametrize(
    ("inventory", "payload", "code"),
    [
        (Inventory(vms=[vm(status="stopped")]), {}, "VM_SHUTDOWN_NON_RUNNING_BLOCKED"),
        (Inventory(vms=[vm(node_id="node-b")]), {}, "VM_SHUTDOWN_MOVED_BLOCKED"),
        (Inventory(), {}, "VM_SHUTDOWN_MISSING_BLOCKED"),
        (Inventory(templates=[vm(template=True)]), {}, "VM_SHUTDOWN_TEMPLATE_BLOCKED"),
        (Inventory(vms=[vm()]), {"expected_name": "other"}, "VM_SHUTDOWN_CONTEXT_MISMATCH"),
        (Inventory(vms=[vm()]), {"expected_status": "stopped"}, "VM_SHUTDOWN_CONTEXT_MISMATCH"),
    ],
)
def test_shutdown_precheck_blocks_unsafe_context(inventory, payload, code):
    with pytest.raises(VmShutdownPrecheckBlocked) as raised:
        evaluate_vm_shutdown_precheck(inventory, node_id="node-a", vmid=306, payload=payload)

    assert raised.value.code == code
