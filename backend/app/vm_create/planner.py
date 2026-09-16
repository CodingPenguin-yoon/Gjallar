"""Dry-run Create VM plan builder for Set 6."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.vm_create.manifest import (
    build_vm_instance_manifest,
    vm_instance_manifest_path,
)
from app.vm_create.models import PreflightResult, VmCreateDraft


SMOKE_TIMEOUT_SUMMARY = {
    "first_power_on_minutes": 5,
    "cloud_init_minutes": 15,
    "guest_agent_minutes": 5,
    "ip_discovery_minutes": 5,
    "ssh_minutes": 5,
}


def _risk_summary(draft: VmCreateDraft, preflight: PreflightResult) -> dict[str, Any]:
    # IP uncertainty is acknowledged independently of other guests' live responses.
    # Static IP retains its own mandatory warning; DHCP retains discovery risk.
    # Keep per-guest failures in preflight, outside the exact creation plan.
    risks = [risk for risk in preflight.risks if not (
        risk.code == "inventory_guest_agent_incomplete"
        and risk.level == "yellow"
    )]
    return {
        "level": preflight.risk_level,
        "red": [risk.to_dict() for risk in risks if risk.level == "red"],
        "yellow": [risk.to_dict() for risk in risks if risk.level == "yellow"],
    }


def _plan_core(draft: VmCreateDraft, preflight: PreflightResult) -> dict[str, Any]:
    planned_manifest_path = vm_instance_manifest_path(draft.manifest_id)
    return {
        "draft_id": draft.draft_id,
        "job_id": draft.job_id,
        "manifest_id": draft.manifest_id,
        "execution_intent": "dry_run_plan_only",
        "profile_id": draft.profile_id,
        "vm_name": draft.vm_name,
        "vmid": draft.proposed_vmid,
        "target_node_id": draft.target_node_id,
        "storage_id": preflight.selected_storage_id,
        "template_id": preflight.selected_template_id,
        "template_vmid": preflight.selected_template_vmid,
        "template_node_id": preflight.selected_template_node_id,
        "hardware": draft.hardware.to_dict(),
        "profile_hardware_limits": dict(preflight.profile_hardware_limits),
        "network": {
            "bridge_id": preflight.selected_bridge_id,
            "ip_mode": draft.network.ip_mode,
            "static_ip": draft.network.static_ip,
            "prefix": draft.network.prefix,
            "gateway": draft.network.gateway,
            "ip_address": draft.network.static_ip,
        },
        "access": dict(preflight.access),
        "selected_template": dict(preflight.selected_template),
        "selected_bridge": dict(preflight.selected_bridge),
        "first_power_on_included": draft.first_power_on_included,
        "power_policy": draft.power_policy,
        "smoke_timeout_summary": dict(SMOKE_TIMEOUT_SUMMARY),
        "risk_summary": _risk_summary(draft, preflight),
        "planned_git_diff_summary": f"create {planned_manifest_path}",
        "side_effects": [],
    }


@dataclass(frozen=True)
class CalculatedVmCreatePlan:
    draft: VmCreateDraft
    preflight: PreflightResult
    core: dict[str, Any]
    manifest: dict[str, Any]
    planned_diff: str


def calculate_vm_create_plan(draft: VmCreateDraft, preflight: PreflightResult) -> CalculatedVmCreatePlan:
    """Calculate plan content without reading or writing persisted records."""
    if preflight.draft_id != draft.draft_id:
        raise ValueError("preflight result must belong to the same draft")
    return CalculatedVmCreatePlan(
        draft=draft,
        preflight=preflight,
        core=_plan_core(draft, preflight),
        manifest=build_vm_instance_manifest(draft, preflight),
        planned_diff=f"A {vm_instance_manifest_path(draft.manifest_id)}\n",
    )
