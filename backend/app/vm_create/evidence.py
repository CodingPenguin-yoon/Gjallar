"""Read-only Create VM evidence summary helper."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from typing import Any, Sequence

from sqlalchemy import select

from app.core.redaction import redact_secrets
from app.db.models import JobArtifactRecord, JobRunRecord, VmCreateRequestRecord, VmInstanceRecord
from app.db.session import session_scope

NOT_RECORDED = "not_recorded"


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _text_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _risk_codes(risks: Any) -> list[str]:
    codes: list[str] = []
    for risk in risks if isinstance(risks, list) else []:
        if isinstance(risk, dict):
            code = _text_or_none(risk.get("code"))
        else:
            code = _text_or_none(risk)
        if code and code not in codes:
            codes.append(code)
    return codes


def _steps_summary(steps: Any) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for step in steps if isinstance(steps, list) else []:
        if not isinstance(step, dict):
            continue
        summaries.append(
            {
                "id": _text_or_none(step.get("id")),
                "label": _text_or_none(step.get("label")),
                "status": _text_or_none(step.get("status")),
                "message": _text_or_none(step.get("message")),
                "updated_at": _text_or_none(step.get("updated_at")),
            }
        )
    return summaries


def _job_summary(row: JobRunRecord | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "job_id": row.job_id,
        "job_type": row.job_type,
        "status": row.status,
        "current_stage": row.current_stage,
        "message": row.message,
        "risk_level": row.risk_level,
        "risk_codes": _risk_codes(row.risks),
        "timestamps": {
            "started_at": row.started_at,
            "finished_at": row.finished_at,
            "updated_at": row.updated_at,
            "created_at": _jsonable(row.created_at),
        },
        "steps": _steps_summary(row.steps),
    }


def _request_summary(row: VmCreateRequestRecord | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "request_id": row.request_id,
        "status": row.status,
        "target_node_id": row.target_node_id,
        "vmid": row.vmid,
        "vm_name": row.vm_name,
        "profile_id": row.profile_id,
        "template_id": row.template_id,
        "storage_id": row.storage_id,
        "actor_user_id": row.actor_user_id,
        "actor_username": row.actor_username,
        "actor_role": row.actor_role,
        "updated_at": row.updated_at,
    }


def _vm_instance_summary(row: VmInstanceRecord | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "vm_instance_id": row.vm_instance_id,
        "node_id": row.node_id,
        "vmid": row.vmid,
        "name": row.name,
        "status": row.status,
        "create_job_id": row.create_job_id,
        "updated_at": row.updated_at,
    }


def _artifact_summary(row: JobArtifactRecord) -> dict[str, Any]:
    return {
        "artifact_id": row.artifact_id,
        "type": row.type,
        "path": row.path,
        "checksum": row.checksum,
        "content_type": row.content_type,
        "size_bytes": row.size_bytes,
        "created_at": row.created_at,
    }


def _parse_observed_after_artifact(rows: list[JobArtifactRecord]) -> dict[str, Any]:
    for row in reversed(rows):
        if row.type != "observed_after":
            continue
        try:
            payload = json.loads(row.content_text)
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _observed_after_source(
    *,
    request: VmCreateRequestRecord | None,
    vm_instance: VmInstanceRecord | None,
    artifacts: list[JobArtifactRecord],
) -> dict[str, Any]:
    if vm_instance is not None and isinstance(vm_instance.observed_after, dict) and vm_instance.observed_after:
        return dict(vm_instance.observed_after)
    if request is not None and isinstance(request.result, dict):
        observed_after = request.result.get("observed_after")
        if isinstance(observed_after, dict) and observed_after:
            return dict(observed_after)
    return _parse_observed_after_artifact(artifacts)


def _cloud_init_summary(value: Any) -> dict[str, Any]:
    cloud_init = value if isinstance(value, dict) else {}
    return {
        "checked": cloud_init.get("checked"),
        "status": _text_or_none(cloud_init.get("status")) or NOT_RECORDED,
        "success": cloud_init.get("success"),
        "exitcode": cloud_init.get("exitcode"),
        "attempts": cloud_init.get("attempts"),
    }


def _boot_verification_summary(value: Any) -> dict[str, Any]:
    boot_verification = value if isinstance(value, dict) else {}
    checks = boot_verification.get("checks")
    safe_checks = {str(key): item for key, item in checks.items()} if isinstance(checks, dict) else {}
    return {
        "success": boot_verification.get("success"),
        "checks": safe_checks,
    }


def _guest_agent_summary(value: Any) -> dict[str, Any]:
    guest_agent = value if isinstance(value, dict) else {}
    return {
        "available": guest_agent.get("available"),
        "attempts": guest_agent.get("attempts"),
    }


def _observed_after_summary(value: Any) -> dict[str, Any]:
    observed_after = value if isinstance(value, dict) else {}
    fingerprint = observed_after.get("fingerprint")
    if not isinstance(fingerprint, dict):
        fingerprint = {}
    ip_addresses = observed_after.get("ip_addresses")
    if not isinstance(ip_addresses, list):
        ip_addresses = []
    return {
        "observed_at": _text_or_none(observed_after.get("observed_at")),
        "exists": observed_after.get("exists"),
        "status": _text_or_none(observed_after.get("status")),
        "post_check_status": _text_or_none(observed_after.get("post_check_status")) or NOT_RECORDED,
        "message": _text_or_none(observed_after.get("message")) or NOT_RECORDED,
        "power_policy": _text_or_none(observed_after.get("power_policy")) or NOT_RECORDED,
        "primary_ip": _text_or_none(observed_after.get("primary_ip")),
        "ip_addresses": [str(item) for item in ip_addresses if str(item or "").strip()],
        "fingerprint_hash": _text_or_none(fingerprint.get("hash")),
        "guest_agent": _guest_agent_summary(observed_after.get("guest_agent")),
        "cloud_init": _cloud_init_summary(observed_after.get("cloud_init")),
        "boot_verification": _boot_verification_summary(observed_after.get("boot_verification")),
    }


def _task_summary(value: Any) -> dict[str, Any]:
    task = value if isinstance(value, dict) else {}
    return {
        "upid": _text_or_none(task.get("upid")),
        "exitstatus": _text_or_none(task.get("exitstatus")),
    }


def _resize_summary(value: Any) -> dict[str, Any]:
    resize = value if isinstance(value, dict) else {}
    return {
        "action": _text_or_none(resize.get("action")) or NOT_RECORDED,
        "success": resize.get("success"),
        "reason": _text_or_none(resize.get("reason")) or NOT_RECORDED,
    }


def _proxmox_summary(request: VmCreateRequestRecord | None, observed_after: dict[str, Any]) -> dict[str, Any]:
    result = request.result if request is not None and isinstance(request.result, dict) else {}
    side_effects = result.get("side_effects")
    if not isinstance(side_effects, list):
        side_effects = []
    start_task = result.get("start_task")
    if not isinstance(start_task, dict):
        start_task = observed_after.get("start_task")
    return {
        "side_effects": [str(item) for item in side_effects],
        "clone_task": _task_summary(result.get("task")),
        "resize": _resize_summary(result.get("resize")),
        "start_task": _task_summary(start_task),
    }


def _runbook_fields(
    *,
    job_id: str,
    job: dict[str, Any] | None,
    request: dict[str, Any] | None,
    vm_instance: dict[str, Any] | None,
    artifacts: list[dict[str, Any]],
    proxmox: dict[str, Any],
    observed_after: dict[str, Any],
) -> dict[str, Any]:
    job_timestamps = dict((job or {}).get("timestamps") or {})
    request_id = (request or {}).get("request_id")
    vmid = (request or vm_instance or {}).get("vmid")
    vm_name = (request or {}).get("vm_name") or (vm_instance or {}).get("name")
    target_node = (request or {}).get("target_node_id") or (vm_instance or {}).get("node_id")
    return {
        "run_timestamp": job_timestamps.get("finished_at") or job_timestamps.get("updated_at") or observed_after.get("observed_at"),
        "code_revision": None,
        "endpoint_http_meta_status_message": {
            "endpoint": NOT_RECORDED,
            "http": NOT_RECORDED,
            "meta": NOT_RECORDED,
            "status": (job or request or {}).get("status"),
            "message": (job or {}).get("message"),
        },
        "job_id": (job or {}).get("job_id") or job_id,
        "request_id": request_id,
        "vmid_name": {"vmid": vmid, "name": vm_name},
        "target_node": target_node,
        "power_policy": observed_after.get("power_policy") or NOT_RECORDED,
        "actor_fields": {
            "actor_user_id": (request or {}).get("actor_user_id"),
            "actor_username": (request or {}).get("actor_username"),
            "actor_role": (request or {}).get("actor_role"),
        },
        "risk_level_codes": {
            "risk_level": (job or {}).get("risk_level"),
            "risk_codes": list((job or {}).get("risk_codes") or []),
        },
        "approval_evidence": {
            "approval_session": NOT_RECORDED,
            "proxmox_mutation_acknowledged": NOT_RECORDED,
        },
        "artifact_ids_types_paths_checksums": [
            {
                "artifact_id": artifact.get("artifact_id"),
                "type": artifact.get("type"),
                "path": artifact.get("path"),
                "checksum": artifact.get("checksum"),
            }
            for artifact in artifacts
        ],
        "proxmox_upid_task_resize_start_side_effects": proxmox,
        "observed_after_summary": {
            "status": observed_after.get("status"),
            "post_check_status": observed_after.get("post_check_status"),
            "message": observed_after.get("message"),
            "exists": observed_after.get("exists"),
            "fingerprint_hash": observed_after.get("fingerprint_hash"),
        },
        "guest_agent_ip": observed_after.get("primary_ip"),
        "cloud_init": observed_after.get("cloud_init"),
        "boot_verification": observed_after.get("boot_verification"),
        "db_vm_create_request_vm_instance_evidence": {
            "vm_create_request": "present" if request is not None else NOT_RECORDED,
            "vm_instance": "present" if vm_instance is not None else NOT_RECORDED,
        },
        "cleanup_decision": NOT_RECORDED,
        "remaining_risk": None,
    }


def _load_vm_instance(session: Any, job_id: str) -> VmInstanceRecord | None:
    return session.scalars(
        select(VmInstanceRecord)
        .where(VmInstanceRecord.create_job_id == job_id)
        .order_by(VmInstanceRecord.updated_at.desc(), VmInstanceRecord.vm_instance_id.asc())
    ).first()


def build_create_vm_evidence_summary(job_id: str) -> dict[str, Any]:
    """Return a curated, read-only Create VM evidence summary for one job."""
    with session_scope() as session:
        job = session.get(JobRunRecord, job_id)
        request = session.get(VmCreateRequestRecord, job_id)
        vm_instance = _load_vm_instance(session, job_id)
        artifact_rows = session.scalars(
            select(JobArtifactRecord)
            .where(JobArtifactRecord.job_id == job_id)
            .order_by(JobArtifactRecord.created_at.asc(), JobArtifactRecord.artifact_id.asc())
        ).all()

        observed_after_raw = _observed_after_source(
            request=request,
            vm_instance=vm_instance,
            artifacts=list(artifact_rows),
        )
        observed_after = _observed_after_summary(observed_after_raw)
        job_payload = _job_summary(job)
        request_payload = _request_summary(request)
        vm_instance_payload = _vm_instance_summary(vm_instance)
        artifact_payloads = [_artifact_summary(row) for row in artifact_rows]
        proxmox_payload = _proxmox_summary(request, observed_after_raw)
        summary = {
            "job_found": job is not None,
            "request_found": request is not None,
            "vm_instance_found": vm_instance is not None,
            "job": job_payload,
            "request": request_payload,
            "vm_instance": vm_instance_payload,
            "artifacts": artifact_payloads,
            "proxmox": proxmox_payload,
            "observed_after": observed_after,
            "runbook_fields": _runbook_fields(
                job_id=job_id,
                job=job_payload,
                request=request_payload,
                vm_instance=vm_instance_payload,
                artifacts=artifact_payloads,
                proxmox=proxmox_payload,
                observed_after=observed_after,
            ),
        }
    return _jsonable(redact_secrets(summary))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a read-only Create VM evidence summary.")
    parser.add_argument("--job-id", required=True, help="Create VM job id to summarize")
    args = parser.parse_args(argv)

    try:
        summary = build_create_vm_evidence_summary(str(args.job_id))
    except Exception as exc:
        print(f"error: failed to build Create VM evidence for job {args.job_id!r}: {exc}", file=sys.stderr)
        return 2
    if not summary.get("job_found"):
        print(f"error: job not found: {args.job_id}", file=sys.stderr)
        return 1
    json.dump(summary, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
