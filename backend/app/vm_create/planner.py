"""Dry-run Create VM plan builder for Set 6."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.jobs.artifacts import write_json_artifact, write_text_artifact
from app.vm_create.approval import build_review_summary_payload
from app.vm_create.models import PreflightResult, VmCreateDraft, VmCreatePlan


SMOKE_TIMEOUT_SUMMARY = {
    "first_power_on_minutes": 5,
    "cloud_init_minutes": 15,
    "guest_agent_minutes": 5,
    "ip_discovery_minutes": 5,
    "ssh_minutes": 5,
}


def _risk_summary(preflight: PreflightResult) -> dict[str, Any]:
    return {
        "level": preflight.risk_level,
        "red": [risk.to_dict() for risk in preflight.risks if risk.level == "red"],
        "yellow": [risk.to_dict() for risk in preflight.risks if risk.level == "yellow"],
    }


def _plan_core(draft: VmCreateDraft, preflight: PreflightResult) -> dict[str, Any]:
    return {
        "draft_id": draft.draft_id,
        "job_id": draft.job_id,
        "manifest_id": draft.manifest_id,
        "execution_intent": "dry_run_plan_only",
        "vm_name": draft.vm_name,
        "vmid": draft.proposed_vmid,
        "target_node_id": draft.target_node_id,
        "storage_id": preflight.selected_storage_id,
        "template_id": preflight.selected_template_id,
        "hardware": draft.hardware.to_dict(),
        "network": {
            "network_id": draft.network.network_id,
            "bridge_id": preflight.selected_bridge_id,
            "ip_mode": draft.network.ip_mode,
            "ip_address": draft.network.static_ip,
        },
        "terraform_state_path": draft.terraform_state_path,
        "first_power_on_included": draft.first_power_on_included,
        "smoke_timeout_summary": dict(SMOKE_TIMEOUT_SUMMARY),
        "risk_summary": _risk_summary(preflight),
        "planned_git_diff_summary": "not_generated_in_set6_dry_run_plan",
        "side_effects": [],
    }


def build_vm_create_plan(draft: VmCreateDraft, preflight: PreflightResult, *, run_dir: str | Path) -> VmCreatePlan:
    """Build an artifact-backed dry-run plan without commit/push/apply/create/power-on."""
    if preflight.draft_id != draft.draft_id:
        raise ValueError("preflight result must belong to the same draft")
    run_path = Path(run_dir)
    preflight_artifact = write_json_artifact(
        run_dir=run_path,
        job_id=draft.job_id,
        artifact_type="preflight_report",
        filename="preflight_report.json",
        payload=preflight.to_dict(),
    )
    core = _plan_core(draft, preflight)
    planned_diff_artifact = write_text_artifact(
        run_dir=run_path,
        job_id=draft.job_id,
        artifact_type="planned_git_diff",
        filename="planned_git_diff.txt",
        text="Set 6 dry-run planner: no Git diff generated; commit/push/apply are approval-gated.\n",
    )
    plan_artifact = write_json_artifact(
        run_dir=run_path,
        job_id=draft.job_id,
        artifact_type="plan",
        filename="plan.json",
        payload=core,
    )
    review_confirm = {
        "vm_name": draft.vm_name,
        "vmid": draft.proposed_vmid,
        "target_node_id": draft.target_node_id,
        "storage_id": preflight.selected_storage_id,
        "template_id": preflight.selected_template_id,
        "hardware": draft.hardware.to_dict(),
        "network": core["network"],
        "terraform_state_path": draft.terraform_state_path,
        "first_power_on_included": draft.first_power_on_included,
        "smoke_timeout_summary": dict(SMOKE_TIMEOUT_SUMMARY),
        "risk_summary": core["risk_summary"],
        "plan_artifact_id": plan_artifact.artifact_id,
        "planned_git_diff_summary": "not_generated_in_set6_dry_run_plan",
        "planned_git_diff_artifact_id": planned_diff_artifact.artifact_id,
    }
    review_summary_artifact = write_json_artifact(
        run_dir=run_path,
        job_id=draft.job_id,
        artifact_type="review_summary",
        filename="review_summary.json",
        payload=build_review_summary_payload(review_confirm),
    )
    review_confirm = {
        **review_confirm,
        "review_summary_artifact_id": review_summary_artifact.artifact_id,
        "review_summary_checksum": review_summary_artifact.checksum,
    }
    return VmCreatePlan(
        draft_id=draft.draft_id,
        job_id=draft.job_id,
        manifest_id=draft.manifest_id,
        execution_intent="dry_run_plan_only",
        vm_name=draft.vm_name,
        vmid=draft.proposed_vmid,
        target_node_id=draft.target_node_id,
        storage_id=preflight.selected_storage_id or "",
        template_id=preflight.selected_template_id or "",
        hardware=draft.hardware.to_dict(),
        network=core["network"],
        terraform_state_path=draft.terraform_state_path,
        first_power_on_included=draft.first_power_on_included,
        smoke_timeout_summary=dict(SMOKE_TIMEOUT_SUMMARY),
        risk_summary=core["risk_summary"],
        review_confirm=review_confirm,
        artifacts=[preflight_artifact, plan_artifact, planned_diff_artifact, review_summary_artifact],
        side_effects=[],
    )
