"""Artifact persistence and response assembly for calculated Create VM plans."""

from pathlib import Path

from app.jobs.artifacts import write_json_artifact, write_text_artifact, write_yaml_artifact
from app.vm_create.approval import build_review_summary_payload
from app.vm_create.models import VmCreatePlan
from app.vm_create.planner import CalculatedVmCreatePlan, SMOKE_TIMEOUT_SUMMARY


def persist_vm_create_plan(calculated: CalculatedVmCreatePlan, *, run_dir: str | Path) -> VmCreatePlan:
    """Persist calculated content using the existing artifact and approval contract."""
    draft, preflight = calculated.draft, calculated.preflight
    run_path = Path(run_dir)
    preflight_artifact = write_json_artifact(
        run_dir=run_path,
        job_id=draft.job_id,
        artifact_type="preflight_report",
        filename="preflight_report.json",
        payload=preflight.to_dict(),
    )
    core = calculated.core
    manifest = calculated.manifest
    manifest_artifact = write_yaml_artifact(
        run_dir=run_path,
        job_id=draft.job_id,
        artifact_type="vm_instance_manifest",
        filename="vm_instance_manifest.yaml",
        payload=manifest,
    )
    planned_diff_artifact = write_text_artifact(
        run_dir=run_path,
        job_id=draft.job_id,
        artifact_type="planned_git_diff",
        filename="planned_git_diff.txt",
        text=calculated.planned_diff,
    )
    plan_artifact = write_json_artifact(
        run_dir=run_path,
        job_id=draft.job_id,
        artifact_type="plan",
        filename="plan.json",
        payload=core,
    )
    review_confirm = {
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
        "network": core["network"],
        "access": core["access"],
        "selected_template": core["selected_template"],
        "selected_bridge": core["selected_bridge"],
        "first_power_on_included": draft.first_power_on_included,
        "power_policy": draft.power_policy,
        "smoke_timeout_summary": dict(SMOKE_TIMEOUT_SUMMARY),
        "risk_summary": core["risk_summary"],
        "plan_artifact_id": plan_artifact.artifact_id,
        "planned_git_diff_summary": core["planned_git_diff_summary"],
        "planned_git_diff_artifact_id": planned_diff_artifact.artifact_id,
        "vm_instance_manifest_artifact_id": manifest_artifact.artifact_id,
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
        profile_id=draft.profile_id,
        vm_name=draft.vm_name,
        vmid=draft.proposed_vmid,
        target_node_id=draft.target_node_id,
        storage_id=preflight.selected_storage_id or "",
        template_id=preflight.selected_template_id or "",
        hardware=draft.hardware.to_dict(),
        profile_hardware_limits=dict(preflight.profile_hardware_limits),
        network=core["network"],
        access=core["access"],
        selected_template=core["selected_template"],
        selected_bridge=core["selected_bridge"],
        first_power_on_included=draft.first_power_on_included,
        power_policy=draft.power_policy,
        smoke_timeout_summary=dict(SMOKE_TIMEOUT_SUMMARY),
        risk_summary=core["risk_summary"],
        review_confirm=review_confirm,
        artifacts=[preflight_artifact, plan_artifact, manifest_artifact, planned_diff_artifact, review_summary_artifact],
        side_effects=[],
        _transient_ssh_public_key=draft.access.transient_ssh_public_key,
    )
