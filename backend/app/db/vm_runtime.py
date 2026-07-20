"""DB helpers for VM create requests and created VM records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.auth.roles import actor_evidence
from app.core.redaction import redact_secrets
from app.db.models import VmCreateRequestRecord, VmInstanceRecord
from app.db.session import session_scope
from app.vm_create.models import VmCreatePlan

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
TARGET_BLOCKING_VM_CREATE_STATUSES = ("running", "needs_reconciliation", "apply_failed", "completed")
_TARGET_STATUS_PRIORITY = {
    "running": 0,
    "needs_reconciliation": 1,
    "apply_failed": 2,
    "completed": 3,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _template_vmid(plan: VmCreatePlan) -> str:
    value = dict(plan.review_confirm or {}).get("template_vmid")
    return str(value or "")


def vm_create_plan_intent(payload: VmCreatePlan | dict[str, Any]) -> dict[str, Any]:
    """Return the stable Create VM intent used for idempotency comparisons.

    Plan artifacts and review checksum fields are deliberately excluded because
    they are execution evidence, not the Proxmox VM creation intent.
    """

    raw_payload = payload.to_dict() if isinstance(payload, VmCreatePlan) else dict(payload or {})
    redacted_payload = redact_secrets(raw_payload)
    intent = {key: redacted_payload.get(key) for key in _PLAN_INTENT_KEYS if key in redacted_payload}
    review = redacted_payload.get("review_confirm")
    if isinstance(review, dict):
        intent["review_confirm"] = {key: review.get(key) for key in _REVIEW_INTENT_KEYS if key in review}
    return intent


def _row_to_request_response(row: VmCreateRequestRecord) -> dict[str, Any]:
    response = {
        "request_id": row.request_id,
        "status": row.status,
        "target_node_id": row.target_node_id,
        "vmid": row.vmid,
        "vm_name": row.vm_name,
        "updated_at": row.updated_at,
    }
    if row.actor_user_id or row.actor_username or row.actor_role:
        response["actor_user_id"] = row.actor_user_id or ""
        response["actor_username"] = row.actor_username or ""
        response["actor_role"] = row.actor_role or ""
        response["actor"] = {
            "user_id": row.actor_user_id or "",
            "username": row.actor_username or "",
            "role": row.actor_role or "",
        }
    return response


def _row_to_full_request_record(row: VmCreateRequestRecord) -> dict[str, Any]:
    request_payload = redact_secrets(dict(row.request_payload or {}))
    approval = redact_secrets(dict(row.approval or {}))
    result = redact_secrets(dict(row.result or {}))
    return {
        **_row_to_request_response(row),
        "draft_id": row.draft_id,
        "manifest_id": row.manifest_id,
        "operator_id": row.operator_id,
        "profile_id": row.profile_id,
        "template_id": row.template_id,
        "storage_id": row.storage_id,
        "request_payload": request_payload,
        "approval": approval,
        "result": result,
        "plan_intent": vm_create_plan_intent(request_payload),
        "created_at": row.created_at,
    }


def get_vm_create_request_record(request_id: str) -> dict[str, Any] | None:
    """Return a redacted Create VM request record for idempotency checks."""

    with session_scope() as session:
        row = session.get(VmCreateRequestRecord, str(request_id))
        if row is None:
            return None
        return _row_to_full_request_record(row)


def find_vm_create_request_for_target(
    *,
    vmid: int | str,
    exclude_request_id: str | None = None,
    statuses: tuple[str, ...] = TARGET_BLOCKING_VM_CREATE_STATUSES,
) -> dict[str, Any] | None:
    """Return the highest-priority Create VM record already owning a target."""

    with session_scope() as session:
        statement = select(VmCreateRequestRecord).where(
            VmCreateRequestRecord.vmid == int(vmid),
            VmCreateRequestRecord.status.in_(statuses),
        )
        if exclude_request_id:
            statement = statement.where(VmCreateRequestRecord.request_id != str(exclude_request_id))
        rows = list(session.scalars(statement).all())
        if not rows:
            return None
        rows.sort(
            key=lambda row: (
                _TARGET_STATUS_PRIORITY.get(str(row.status), 99),
                str(row.updated_at or ""),
                str(row.request_id or ""),
            )
        )
        return _row_to_full_request_record(rows[0])


def get_vm_instance_record(node_id: str, vmid: int | str) -> dict[str, Any] | None:
    """Return the local VM instance record created by the native Create VM flow."""

    instance_id = f"{node_id}:{int(vmid)}"
    with session_scope() as session:
        row = session.get(VmInstanceRecord, instance_id)
        if row is None:
            return None
        return {
            "vm_instance_id": row.vm_instance_id,
            "node_id": row.node_id,
            "vmid": row.vmid,
            "name": row.name,
            "status": row.status,
            "updated_at": row.updated_at,
        }


def record_vm_create_request(
    plan: VmCreatePlan,
    *,
    status: str,
    approval: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist the latest request/result summary for a Create VM job."""
    now = _now_iso()
    request_payload = redact_secrets(plan.to_dict())
    approval_payload = redact_secrets(approval or {})
    result_payload = redact_secrets(result or {})
    actor_payload = actor_evidence(actor) if actor is not None else {}
    with session_scope() as session:
        row = session.get(VmCreateRequestRecord, plan.job_id)
        if row is None:
            row = VmCreateRequestRecord(
                request_id=plan.job_id,
                draft_id=plan.draft_id,
                manifest_id=plan.manifest_id,
                operator_id=str(request_payload.get("operator_id") or ""),
                status=status,
                target_node_id=plan.target_node_id,
                vmid=int(plan.vmid),
                vm_name=plan.vm_name,
                profile_id=plan.profile_id,
                template_id=plan.template_id or _template_vmid(plan),
                storage_id=plan.storage_id,
                actor_user_id=str(actor_payload.get("user_id") or "") or None,
                actor_username=str(actor_payload.get("username") or "") or None,
                actor_role=str(actor_payload.get("role") or "") or None,
                request_payload=request_payload,
                approval=approval_payload,
                result=result_payload,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        else:
            row.status = status
            row.target_node_id = plan.target_node_id
            row.vmid = int(plan.vmid)
            row.vm_name = plan.vm_name
            row.profile_id = plan.profile_id
            row.template_id = plan.template_id or _template_vmid(plan)
            row.storage_id = plan.storage_id
            row.actor_user_id = str(actor_payload.get("user_id") or "") or None
            row.actor_username = str(actor_payload.get("username") or "") or None
            row.actor_role = str(actor_payload.get("role") or "") or None
            row.request_payload = request_payload
            row.approval = approval_payload
            row.result = result_payload
            row.updated_at = now
        return _row_to_request_response(row)


def record_vm_instance_from_create(plan: VmCreatePlan, create_result: dict[str, Any]) -> dict[str, Any]:
    """Persist the VM created through the native Create VM flow."""
    now = _now_iso()
    observed_after = redact_secrets(dict(create_result.get("observed_after") or {}))
    observed_status = str(observed_after.get("status") or "").strip() or "stopped"
    hardware = dict(plan.hardware or {})
    access = dict(plan.access or {})
    instance_id = f"{plan.target_node_id}:{int(plan.vmid)}"
    with session_scope() as session:
        row = session.get(VmInstanceRecord, instance_id)
        if row is None:
            row = VmInstanceRecord(
                vm_instance_id=instance_id,
                node_id=plan.target_node_id,
                vmid=int(plan.vmid),
                name=plan.vm_name,
                status=observed_status,
                profile_id=plan.profile_id,
                template_id=plan.template_id or _template_vmid(plan),
                storage_id=plan.storage_id,
                cpu=int(hardware.get("cpu") or 0),
                memory_mb=int(hardware.get("memory_mb") or 0),
                disk_gb=int(hardware.get("disk_gb") or 0),
                network=dict(plan.network or {}),
                access=redact_secrets(access),
                observed_after=observed_after,
                create_job_id=plan.job_id,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        else:
            row.name = plan.vm_name
            row.status = observed_status
            row.profile_id = plan.profile_id
            row.template_id = plan.template_id or _template_vmid(plan)
            row.storage_id = plan.storage_id
            row.cpu = int(hardware.get("cpu") or 0)
            row.memory_mb = int(hardware.get("memory_mb") or 0)
            row.disk_gb = int(hardware.get("disk_gb") or 0)
            row.network = dict(plan.network or {})
            row.access = redact_secrets(access)
            row.observed_after = observed_after
            row.create_job_id = plan.job_id
            row.updated_at = now
        return {
            "vm_instance_id": row.vm_instance_id,
            "node_id": row.node_id,
            "vmid": row.vmid,
            "name": row.name,
            "status": row.status,
            "updated_at": row.updated_at,
        }
