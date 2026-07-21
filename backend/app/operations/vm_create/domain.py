"""Infrastructure-free Create VM operation identity and evidence rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.core.redaction import redact_secrets
from app.operations.core.domain import OperationActor


VM_CREATE_OPERATION_TYPE = "vm_create"

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
            "profile_id": self.profile_id,
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
    return {
        "status": str(payload.get("status") or ""),
        "success": payload.get("success") is True,
        "message": str(payload.get("message") or "")[:1000],
        "task": {
            "upid": str(task.get("upid") or ""),
            "status": str(task.get("status") or ""),
            "exitstatus": str(task.get("exitstatus") or ""),
        },
        "observed_after": {
            "status": str(observed_after.get("status") or ""),
            "exists": observed_after.get("exists"),
            "fingerprint_hash": str(fingerprint.get("hash") or ""),
        },
        "observed_after_artifact": {
            "artifact_id": str(artifact.get("artifact_id") or artifact.get("id") or ""),
            "checksum": str(artifact.get("checksum") or ""),
        },
        "side_effects": [str(item) for item in list(payload.get("side_effects") or [])],
    }
