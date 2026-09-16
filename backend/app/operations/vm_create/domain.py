"""Infrastructure-free Create VM operation identity and evidence rules."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from app.core.redaction import redact_secrets
from app.operations.core.domain import OperationActor
from app.operations.core.evidence import compact_proxmox_task, compact_proxmox_vm_status


VM_CREATE_OPERATION_TYPE = "vm_create"

_CREATE_RESULT_STATUSES = frozenset(
    {"completed", "failed", "needs_reconciliation", "blocked", "unknown"}
)
_CREATE_POST_CHECK_STATUSES = frozenset({"completed", "failed", "needs_reconciliation"})
_CREATE_POWER_POLICIES = frozenset({"stopped", "boot_and_verify"})
_CREATE_SIDE_EFFECTS = frozenset(
    {
        "proxmox_boot_post_check_observed",
        "proxmox_clone_invoked",
        "proxmox_clone_rejected",
        "proxmox_clone_state_unknown",
        "proxmox_cloud_init_status_checked",
        "proxmox_cloud_init_status_unavailable",
        "proxmox_config_updated",
        "proxmox_disk_resize_failed",
        "proxmox_disk_resize_invoked",
        "proxmox_disk_resize_not_needed",
        "proxmox_disk_resize_skipped_unknown",
        "proxmox_disk_resize_succeeded",
        "proxmox_guest_agent_observed",
        "proxmox_guest_agent_unavailable",
        "proxmox_post_check_observed",
        "proxmox_start_invoked",
        "proxmox_start_task_polled",
        "proxmox_task_poll_state_unknown",
        "proxmox_task_polled",
    }
)
_SAFE_ARTIFACT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_SAFE_DIGEST = re.compile(r"^sha256:[A-Za-z0-9._:-]{1,128}$")

_PLAN_INTENT_KEYS = (
    "draft_id",
    "job_id",
    "manifest_id",
    "profile_id",
    "vm_name",
    "vmid",
    "target_node_id",
    "storage_id",
    "template_id",
    "hardware",
    "profile_hardware_limits",
    "network",
    "access",
    "selected_template",
    "selected_bridge",
    "first_power_on_included",
    "power_policy",
    "smoke_timeout_summary",
    "risk_summary",
)
_REVIEW_INTENT_KEYS = (
    "profile_id",
    "vm_name",
    "vmid",
    "target_node_id",
    "storage_id",
    "template_id",
    "template_vmid",
    "template_node_id",
    "hardware",
    "profile_hardware_limits",
    "network",
    "access",
    "selected_template",
    "selected_bridge",
    "first_power_on_included",
    "power_policy",
    "smoke_timeout_summary",
    "risk_summary",
    "planned_git_diff_summary",
)


def vm_create_plan_intent(payload: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Return the redacted stable intent used by old and common projections."""

    raw_payload = payload.to_dict() if hasattr(payload, "to_dict") else dict(payload or {})
    redacted_payload = redact_secrets(raw_payload)
    if not isinstance(redacted_payload, dict):
        redacted_payload = {}
    intent = {key: redacted_payload.get(key) for key in _PLAN_INTENT_KEYS if key in redacted_payload}
    review = redacted_payload.get("review_confirm")
    if isinstance(review, dict):
        intent["review_confirm"] = {key: review.get(key) for key in _REVIEW_INTENT_KEYS if key in review}
    return intent


def vm_create_target_id(vmid: int) -> str:
    return f"vmid:{int(vmid)}"


@dataclass(frozen=True)
class VmCreateOperationPlan:
    operation_id: str
    draft_id: str
    target_node_id: str
    vmid: int
    vm_name: str
    profile_id: str
    plan_artifact_id: str
    plan_digest: str
    risk_level: str
    intent: Mapping[str, Any]
    actor: OperationActor

    def __post_init__(self) -> None:
        required = {
            "operation_id": self.operation_id,
            "draft_id": self.draft_id,
            "target_node_id": self.target_node_id,
            "vm_name": self.vm_name,
            "plan_artifact_id": self.plan_artifact_id,
            "plan_digest": self.plan_digest,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise ValueError(f"Create VM operation fields are required: {', '.join(missing)}")
        if int(self.vmid) < 1:
            raise ValueError("Create VM operation vmid must be positive")

    @property
    def target_id(self) -> str:
        return vm_create_target_id(self.vmid)


def compact_create_result(result: Mapping[str, Any] | None) -> dict[str, Any]:
    """Keep query-safe task, verification, artifact, and side-effect evidence."""

    payload = dict(result or {})
    task = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    observed_after = payload.get("observed_after") if isinstance(payload.get("observed_after"), dict) else {}
    artifact = payload.get("observed_after_artifact") if isinstance(payload.get("observed_after_artifact"), dict) else {}
    fingerprint = observed_after.get("fingerprint") if isinstance(observed_after.get("fingerprint"), dict) else {}
    boot_verification = (
        observed_after.get("boot_verification")
        if isinstance(observed_after.get("boot_verification"), dict)
        else {}
    )
    boot_checks = (
        boot_verification.get("checks")
        if isinstance(boot_verification.get("checks"), dict)
        else {}
    )
    guest_agent = (
        observed_after.get("guest_agent")
        if isinstance(observed_after.get("guest_agent"), dict)
        else {}
    )
    cloud_init = (
        observed_after.get("cloud_init")
        if isinstance(observed_after.get("cloud_init"), dict)
        else {}
    )
    result_status = str(payload.get("status") or "").strip().lower()
    if result_status not in _CREATE_RESULT_STATUSES:
        result_status = "unknown"
    compact_task = compact_proxmox_task(task)
    try:
        observed_vmid = int(observed_after.get("vmid") or 0)
    except (TypeError, ValueError, OverflowError):
        observed_vmid = 0
    compact_observed = compact_proxmox_vm_status(
        observed_after,
        node=str(observed_after.get("target_node_id") or ""),
        vmid=observed_vmid,
    )
    post_check_status = str(observed_after.get("post_check_status") or "").strip().lower()
    if post_check_status not in _CREATE_POST_CHECK_STATUSES:
        post_check_status = "needs_reconciliation"
    power_policy = str(observed_after.get("power_policy") or "").strip().lower()
    if power_policy not in _CREATE_POWER_POLICIES:
        power_policy = ""
    fingerprint_hash = str(fingerprint.get("hash") or "").strip().lower()
    if _SAFE_DIGEST.fullmatch(fingerprint_hash) is None:
        fingerprint_hash = ""
    artifact_id = str(artifact.get("artifact_id") or artifact.get("id") or "").strip()
    if _SAFE_ARTIFACT_ID.fullmatch(artifact_id) is None:
        artifact_id = ""
    artifact_checksum = str(artifact.get("checksum") or artifact.get("sha256") or "").strip().lower()
    if _SAFE_DIGEST.fullmatch(artifact_checksum) is None:
        artifact_checksum = ""
    message = {
        "completed": "Create VM completed with verified evidence.",
        "failed": "Create VM failed before a verified result was established.",
        "blocked": "Create VM was blocked before execution.",
        "needs_reconciliation": "Create VM requires reconciliation.",
        "unknown": "Create VM result is unknown.",
    }[result_status]
    return {
        "status": result_status,
        "success": payload.get("success") is True,
        "message": message,
        "task": compact_task,
        "observed_after": {
            "status": compact_observed["status"],
            "exists": observed_after.get("exists"),
            "fingerprint_hash": fingerprint_hash,
            "readiness": {
                "post_check_status": post_check_status,
                "message": (
                    "Create readiness is verified."
                    if post_check_status == "completed"
                    else "Create readiness requires reconciliation."
                ),
                "power_policy": power_policy,
                "guest_agent_available": guest_agent.get("available") is True,
                "cloud_init_completed": cloud_init.get("success") is True,
                "boot_verification_success": boot_verification.get("success") is True,
                "checks": {
                    str(key): value is True
                    for key, value in boot_checks.items()
                    if str(key) in {
                        "running",
                        "guest_agent_available",
                        "ip_observed",
                        "cloud_init_completed",
                    }
                },
            },
        },
        "observed_after_artifact": {
            "artifact_id": artifact_id,
            "checksum": artifact_checksum,
        },
        "side_effects": [
            str(item)
            for item in list(payload.get("side_effects") or [])
            if str(item) in _CREATE_SIDE_EFFECTS
        ],
    }


def completed_workload_history(operation, *, node_id: str, vmid: int) -> dict[str, Any] | None:
    """Validate the historical result; never infer it from current inventory."""
    details = operation.details
    target = details.get("target")
    workload = details.get("workload")
    if not isinstance(target, Mapping) or not isinstance(workload, Mapping):
        return None
    if (
        operation.operation_type != VM_CREATE_OPERATION_TYPE
        or operation.execution_mode != "managed_api"
        or operation.status != "succeeded"
        or operation.target_type != "proxmox_vm"
        or operation.target_id != f"vmid:{vmid}"
        or target.get("node_id") != node_id
        or type(target.get("vmid")) is not int or target["vmid"] != vmid
        or workload.get("vm_instance_id") != f"{node_id}:{vmid}"
        or workload.get("node_id") != node_id
        or type(workload.get("vmid")) is not int or workload["vmid"] != vmid
        or any(not isinstance(workload.get(key), str) or not workload[key].strip()
               for key in ("name", "status", "updated_at"))
    ):
        return None
    return {key: workload[key] for key in ("vm_instance_id", "node_id", "vmid", "name", "status", "updated_at")}
