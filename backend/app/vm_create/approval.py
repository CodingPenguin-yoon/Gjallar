"""Review & Confirm approval policy helpers for the non-destructive MVP flow."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.jobs.artifacts import write_json_artifact
from app.jobs.models import ApprovalRecord, ArtifactRecord

REVIEW_CONFIRM_REQUIRED_KEYS = (
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
    "terraform_state_path",
    "first_power_on_included",
    "smoke_timeout_summary",
    "risk_summary",
    "plan_artifact_id",
    "planned_git_diff_summary",
)


@dataclass(frozen=True)
class ApprovalGateDecision:
    """Result of evaluating a Review & Confirm approval request."""

    risk_level: str
    can_approve: bool
    can_execute: bool
    requires_yellow_ack: bool
    reason: str
    side_effects: list[str] = field(default_factory=list)
    approval_record: ApprovalRecord | None = None
    approval_artifact: ArtifactRecord | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["approval_record"] = self.approval_record.to_dict() if self.approval_record else None
        data["approval_artifact"] = self.approval_artifact.to_dict() if self.approval_artifact else None
        data["side_effects"] = list(self.side_effects)
        return data


def _risk_to_dict(risk: Any) -> dict[str, Any]:
    if hasattr(risk, "to_dict"):
        return dict(risk.to_dict())
    if isinstance(risk, dict):
        return dict(risk)
    return {"level": str(getattr(risk, "level", "unknown")), "code": str(getattr(risk, "code", "unknown"))}


def _risk_level(risks: list[dict[str, Any]]) -> str:
    levels = {str(risk.get("level", "")).lower() for risk in risks}
    if "red" in levels:
        return "red"
    if "yellow" in levels:
        return "yellow"
    return "green"


def _decision(
    *,
    risk_level: str,
    can_approve: bool,
    can_execute: bool,
    requires_yellow_ack: bool,
    reason: str,
    approval_record: ApprovalRecord | None = None,
    approval_artifact: ArtifactRecord | None = None,
) -> ApprovalGateDecision:
    return ApprovalGateDecision(
        risk_level=risk_level,
        can_approve=can_approve,
        can_execute=can_execute,
        requires_yellow_ack=requires_yellow_ack,
        reason=reason,
        side_effects=[],
        approval_record=approval_record,
        approval_artifact=approval_artifact,
    )


def evaluate_approval_gate(*, risks: list[Any], yellow_risk_acknowledged: bool = False) -> ApprovalGateDecision:
    """Apply MVP Review & Confirm policy without executing live side effects."""
    normalized = [_risk_to_dict(risk) for risk in risks]
    level = _risk_level(normalized)
    acknowledged = yellow_risk_acknowledged is True
    if level == "red":
        return _decision(
            risk_level="red",
            can_approve=False,
            can_execute=False,
            requires_yellow_ack=False,
            reason="red risk blocks approval and execution",
        )
    if level == "yellow" and not acknowledged:
        return _decision(
            risk_level="yellow",
            can_approve=False,
            can_execute=False,
            requires_yellow_ack=True,
            reason="yellow risk requires explicit acknowledgement before approval",
        )
    if level == "yellow":
        return _decision(
            risk_level="yellow",
            can_approve=True,
            can_execute=True,
            requires_yellow_ack=False,
            reason="yellow risk acknowledged; approval gate is open",
        )
    return _decision(
        risk_level="green",
        can_approve=True,
        can_execute=True,
        requires_yellow_ack=False,
        reason="green risk; approval gate is open",
    )


def build_review_summary_payload(review_confirm: dict[str, Any]) -> dict[str, Any]:
    """Return the 13 required Review & Confirm display items as a stable artifact payload."""
    missing = [key for key in REVIEW_CONFIRM_REQUIRED_KEYS if key not in review_confirm]
    if missing:
        raise ValueError(f"review_confirm is missing required keys: {', '.join(missing)}")
    return {key: review_confirm[key] for key in REVIEW_CONFIRM_REQUIRED_KEYS}


def _risks_from_summary(risk_summary: dict[str, Any]) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for key in ("red", "yellow"):
        for risk in risk_summary.get(key, []) or []:
            risk_dict = _risk_to_dict(risk)
            risk_dict.setdefault("level", key)
            risks.append(risk_dict)
    if not risks and risk_summary.get("level") not in (None, "green"):
        risks.append({"level": risk_summary.get("level"), "code": "summary_level"})
    return risks


def validate_approval_request(
    plan: Any,
    *,
    plan_artifact_id: str,
    review_summary_checksum: str,
    yellow_risk_acknowledged: bool,
    run_dir: str | Path | None = None,
) -> ApprovalGateDecision:
    """Validate approval metadata against the artifact-backed dry-run plan.

    This deliberately performs no commit/push/apply/Proxmox action. It only checks
    that the operator approved the exact plan and review summary artifacts.
    """
    review = dict(plan.review_confirm)
    expected_plan_artifact_id = review.get("plan_artifact_id")
    expected_review_checksum = review.get("review_summary_checksum")
    artifacts_by_type = {artifact.type: artifact for artifact in plan.artifacts}
    plan_artifact = artifacts_by_type.get("plan")
    review_artifact = artifacts_by_type.get("review_summary")

    if not plan_artifact_id:
        return _decision(
            risk_level=str(plan.risk_summary.get("level", "unknown")),
            can_approve=False,
            can_execute=False,
            requires_yellow_ack=False,
            reason="plan_artifact_id is required",
        )
    if plan_artifact is None or plan_artifact_id != expected_plan_artifact_id or plan_artifact_id != plan_artifact.artifact_id:
        return _decision(
            risk_level=str(plan.risk_summary.get("level", "unknown")),
            can_approve=False,
            can_execute=False,
            requires_yellow_ack=False,
            reason="plan_artifact_id does not match the stored plan artifact",
        )
    if not review_summary_checksum or review_summary_checksum != expected_review_checksum:
        return _decision(
            risk_level=str(plan.risk_summary.get("level", "unknown")),
            can_approve=False,
            can_execute=False,
            requires_yellow_ack=False,
            reason="review_summary_checksum does not match the plan review summary",
        )
    if review_artifact is None or review_summary_checksum != review_artifact.checksum:
        return _decision(
            risk_level=str(plan.risk_summary.get("level", "unknown")),
            can_approve=False,
            can_execute=False,
            requires_yellow_ack=False,
            reason="review summary artifact checksum is missing or mismatched",
        )

    gate = evaluate_approval_gate(
        risks=_risks_from_summary(plan.risk_summary),
        yellow_risk_acknowledged=yellow_risk_acknowledged,
    )
    approval_record = ApprovalRecord(
        job_id=plan.job_id,
        plan_artifact_id=plan_artifact_id,
        review_summary_checksum=review_summary_checksum,
        yellow_risk_acknowledged=yellow_risk_acknowledged,
        decision="approved" if gate.can_approve else "blocked",
    )
    approval_artifact = None
    if run_dir is not None:
        approval_artifact = write_json_artifact(
            run_dir=run_dir,
            job_id=plan.job_id,
            artifact_type="approval",
            filename="approval.json",
            payload={"approval": approval_record.to_dict(), "gate": gate.to_dict()},
        )
    return _decision(
        risk_level=gate.risk_level,
        can_approve=gate.can_approve,
        can_execute=gate.can_execute,
        requires_yellow_ack=gate.requires_yellow_ack,
        reason=gate.reason,
        approval_record=approval_record,
        approval_artifact=approval_artifact,
    )
