"""Pure workload observation rules for graceful VM Shutdown."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.operations.vm_shutdown.domain import vm_shutdown_expected_context, vm_shutdown_target
from app.operations.vm_shutdown.ports import WorkloadInventoryPort


@dataclass(frozen=True)
class VmShutdownPrecheck:
    target: dict[str, Any]
    observed_before: dict[str, Any]
    expected: dict[str, Any]


class VmShutdownPrecheckBlocked(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        target: dict[str, Any],
        expected: dict[str, Any],
        observed_before: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.target = dict(target)
        self.expected = dict(expected)
        self.observed_before = dict(observed_before or {})
        super().__init__(message)


def normalize_vm_status(value: object) -> str:
    return str(value or "").strip().lower()


def _to_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return dict(value)
    return {}


def _vm_node_id(value: Any) -> str:
    data = _to_dict(value)
    return str(data.get("node_id") or data.get("node") or "").strip()


def _vm_vmid(value: Any) -> int | None:
    data = _to_dict(value)
    try:
        return int(data.get("vmid") if data.get("vmid") is not None else data.get("id"))
    except (TypeError, ValueError):
        return None


def evaluate_vm_shutdown_precheck(
    adapter: WorkloadInventoryPort,
    *,
    node_id: str,
    vmid: int,
    payload: dict[str, Any],
) -> VmShutdownPrecheck:
    expected = vm_shutdown_expected_context(payload)
    target = vm_shutdown_target(node_id=node_id, vmid=vmid, name=expected.get("expected_name", ""))
    vms = list(adapter.list_vms())
    exact_vm = next((vm for vm in vms if _vm_vmid(vm) == int(vmid) and _vm_node_id(vm) == node_id), None)
    moved_vm = next((vm for vm in vms if _vm_vmid(vm) == int(vmid) and _vm_node_id(vm) != node_id), None)
    template = next(
        (
            item
            for item in adapter.list_templates()
            if _vm_vmid(item) == int(vmid) and (not _vm_node_id(item) or _vm_node_id(item) == node_id)
        ),
        None,
    )

    if template is not None:
        observed = _to_dict(template)
        raise VmShutdownPrecheckBlocked(
            "VM_SHUTDOWN_TEMPLATE_BLOCKED",
            "VM shutdown is blocked for templates",
            target={**target, "name": str(observed.get("name") or target.get("name") or "")},
            expected=expected,
            observed_before={**observed, "template": True},
        )
    if exact_vm is None:
        if moved_vm is not None:
            observed = _to_dict(moved_vm)
            raise VmShutdownPrecheckBlocked(
                "VM_SHUTDOWN_MOVED_BLOCKED",
                "VM shutdown target moved from the requested node",
                target={**target, "name": str(observed.get("name") or target.get("name") or "")},
                expected=expected,
                observed_before=observed,
            )
        raise VmShutdownPrecheckBlocked(
            "VM_SHUTDOWN_MISSING_BLOCKED",
            "VM shutdown target was not found in fresh inventory",
            target=target,
            expected=expected,
        )

    observed_before = _to_dict(exact_vm)
    target = vm_shutdown_target(
        node_id=node_id,
        vmid=vmid,
        name=str(observed_before.get("name") or target.get("name") or ""),
    )
    if bool(observed_before.get("template")):
        raise VmShutdownPrecheckBlocked(
            "VM_SHUTDOWN_TEMPLATE_BLOCKED",
            "VM shutdown is blocked for templates",
            target=target,
            expected=expected,
            observed_before=observed_before,
        )

    status = normalize_vm_status(observed_before.get("status"))
    expected_name = str(expected.get("expected_name") or "").strip()
    observed_name = str(observed_before.get("name") or "").strip()
    if expected_name and observed_name != expected_name:
        raise VmShutdownPrecheckBlocked(
            "VM_SHUTDOWN_CONTEXT_MISMATCH",
            f"VM shutdown context mismatch: expected name {expected_name}, observed {observed_name or 'unknown'}",
            target=target,
            expected=expected,
            observed_before=observed_before,
        )
    expected_status = normalize_vm_status(expected.get("expected_status"))
    if expected_status and status != expected_status:
        raise VmShutdownPrecheckBlocked(
            "VM_SHUTDOWN_CONTEXT_MISMATCH",
            f"VM shutdown context mismatch: expected status {expected_status}, observed {status or 'unknown'}",
            target=target,
            expected=expected,
            observed_before=observed_before,
        )
    if status != "running":
        raise VmShutdownPrecheckBlocked(
            "VM_SHUTDOWN_NON_RUNNING_BLOCKED",
            f"VM shutdown requires a running VM; observed {status or 'unknown'}",
            target=target,
            expected=expected,
            observed_before=observed_before,
        )
    return VmShutdownPrecheck(target=target, observed_before=observed_before, expected=expected)
