"""DB helpers for VM create requests and created VM records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.redaction import redact_secrets
from app.db.models import VmCreateRequestRecord, VmInstanceRecord
from app.db.session import session_scope
from app.vm_create.models import VmCreatePlan


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _template_vmid(plan: VmCreatePlan) -> str:
    value = dict(plan.review_confirm or {}).get("template_vmid")
    return str(value or "")


def record_vm_create_request(
    plan: VmCreatePlan,
    *,
    status: str,
    approval: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist the latest request/result summary for a Create VM job."""
    now = _now_iso()
    request_payload = redact_secrets(plan.to_dict())
    approval_payload = redact_secrets(approval or {})
    result_payload = redact_secrets(result or {})
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
            row.request_payload = request_payload
            row.approval = approval_payload
            row.result = result_payload
            row.updated_at = now
        return {
            "request_id": row.request_id,
            "status": row.status,
            "target_node_id": row.target_node_id,
            "vmid": row.vmid,
            "vm_name": row.vm_name,
            "updated_at": row.updated_at,
        }


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
