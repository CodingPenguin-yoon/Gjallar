"""DB-backed job run status records for the /api/v1 Jobs/Runs screen."""

from __future__ import annotations

import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.auth.roles import restore_trusted_actor_evidence
from app.core.redaction import redact_secrets
from app.db.models import JobRunRecord
from app.db.session import session_scope
from app.jobs.artifacts import list_artifact_records, write_json_artifact

VM_CREATE_STEP_ORDER = ["draft", "preflight", "plan", "approval", "create"]
VM_CREATE_STEP_LABELS = {
    "draft": "요청 입력",
    "preflight": "사전 검토",
    "plan": "생성 계획",
    "approval": "승인 확인",
    "create": "VM 생성",
}
VM_START_STEP_ORDER = ["precheck", "start", "task_poll", "post_check"]
VM_START_STEP_LABELS = {
    "precheck": "시작 사전 확인",
    "start": "VM 시작 요청",
    "task_poll": "Proxmox 작업 확인",
    "post_check": "시작 후 확인",
}
DRS_MIGRATION_STEP_ORDER = [
    "recommendation",
    "final_precheck",
    "approval",
    "job_intent",
    "operation_lock",
    "migration",
    "task_poll",
    "post_check",
    "reconciliation",
]
DRS_MIGRATION_STEP_LABELS = {
    "recommendation": "DRS 추천 확인",
    "final_precheck": "최종 사전 확인",
    "approval": "DRS 승인 패킷",
    "job_intent": "로컬 작업 의도",
    "operation_lock": "DRS 작업 잠금",
    "migration": "Proxmox 마이그레이션 요청",
    "task_poll": "Proxmox 작업 확인",
    "post_check": "마이그레이션 후 확인",
    "reconciliation": "조정 필요",
}
TERMINAL_STATUSES = {"completed", "failed", "blocked", "timed_out", "ambiguous", "needs_reconciliation"}


def _step_order(job_type: str) -> list[str]:
    if job_type == "vm_start":
        return VM_START_STEP_ORDER
    if job_type == "drs_migration":
        return DRS_MIGRATION_STEP_ORDER
    return VM_CREATE_STEP_ORDER


def _step_labels(job_type: str) -> dict[str, str]:
    if job_type == "vm_start":
        return VM_START_STEP_LABELS
    if job_type == "drs_migration":
        return DRS_MIGRATION_STEP_LABELS
    return VM_CREATE_STEP_LABELS


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_segment(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value)).strip("-")
    return safe[:120] or "job"


def runs_root() -> Path:
    """Return a local runtime scratch root for locks and legacy call compatibility."""
    return Path(tempfile.gettempdir()) / "gjallar-runtime"


def run_dir(job_id: str) -> Path:
    return runs_root() / _safe_segment(job_id)


def _empty_steps(job_type: str) -> list[dict[str, Any]]:
    step_order = _step_order(job_type)
    step_labels = _step_labels(job_type)
    return [
        {"id": step, "label": step_labels[step], "status": "pending", "updated_at": ""}
        for step in step_order
    ]


def _merge_steps(
    current_steps: list[dict[str, Any]],
    *,
    job_type: str,
    stage: str,
    step_status: str,
    message: str,
    updated_at: str,
) -> list[dict[str, Any]]:
    by_id = {step.get("id"): dict(step) for step in current_steps if step.get("id")}
    steps = []
    step_order = _step_order(job_type)
    step_labels = _step_labels(job_type)
    stage_index = step_order.index(stage) if stage in step_order else -1
    for index, step_id in enumerate(step_order):
        step = by_id.get(step_id, {"id": step_id, "label": step_labels[step_id]})
        previous_status = str(step.get("status") or "pending")
        if stage_index < 0:
            next_status = previous_status
        elif job_type == "drs_migration" and stage == "reconciliation" and step_id == "post_check":
            next_status = previous_status if previous_status in {"completed", "blocked", "failed"} else "pending"
        elif index < stage_index:
            next_status = "completed"
        elif index == stage_index:
            next_status = step_status
        else:
            next_status = "pending"
        steps.append(
            {
                "id": step_id,
                "label": step_labels[step_id],
                "status": next_status,
                "message": message if index == stage_index else str(step.get("message") or ""),
                "updated_at": updated_at if index <= stage_index else str(step.get("updated_at") or ""),
            }
        )
    return steps


def _progress_percent(steps: list[dict[str, Any]]) -> int:
    if not steps:
        return 0
    score = 0.0
    for step in steps:
        status = str(step.get("status") or "")
        if status == "completed":
            score += 1.0
        elif status in {"running", "in_progress"}:
            score += 0.5
    return int(round((score / len(steps)) * 100))


def _artifact_dicts(artifacts: list[Any]) -> list[dict[str, Any]]:
    result = []
    for artifact in artifacts:
        if hasattr(artifact, "to_dict"):
            result.append(artifact.to_dict())
        elif isinstance(artifact, dict):
            result.append(dict(artifact))
    return result


def _risk_dicts(risks: list[Any] | None) -> list[dict[str, Any]]:
    result = []
    for risk in risks or []:
        if hasattr(risk, "to_dict"):
            result.append(risk.to_dict())
        elif isinstance(risk, dict):
            result.append(dict(risk))
    return result


def _row_to_payload(row: JobRunRecord, *, artifacts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    artifact_list = artifacts if artifacts is not None else list_artifact_records(row.job_id)
    return {
        "job_id": row.job_id,
        "job_type": row.job_type,
        "status": row.status,
        "target_id": row.target_id,
        "risk_level": row.risk_level,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "current_stage": row.current_stage,
        "message": row.message,
        "progress_percent": row.progress_percent,
        "steps": list(row.steps or []),
        "artifact_count": len(artifact_list),
        "risk_count": len(row.risks or []),
        "artifacts": artifact_list,
        "risks": list(row.risks or []),
        "details": dict(row.details or {}),
        "updated_at": row.updated_at,
    }


def _load_status(job_id: str) -> dict[str, Any] | None:
    with session_scope() as session:
        row = session.get(JobRunRecord, job_id)
        if row is None:
            return None
        return _row_to_payload(row)


def _dedupe_artifacts(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    artifact_index: dict[str, dict[str, Any]] = {}
    for group in groups:
        for item in group:
            if not isinstance(item, dict):
                continue
            key = str(item.get("artifact_id") or item.get("id") or item.get("path") or "")
            if not key:
                continue
            artifact_index[key] = item
    return list(artifact_index.values())


def _write_status_artifact(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    artifact_payload = {**payload, "artifacts": [item for item in payload.get("artifacts") or [] if item.get("type") != "job_status"]}
    record = write_json_artifact(
        run_dir=run_dir(job_id),
        job_id=job_id,
        artifact_type="job_status",
        filename="job_status.json",
        payload=artifact_payload,
    )
    return record.to_dict()


def record_job_run(
    *,
    job_id: str,
    job_type: str,
    status: str,
    target_id: str,
    risk_level: str,
    stage: str,
    step_status: str,
    message: str,
    artifacts: list[Any] | None = None,
    risks: list[Any] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist the latest job status for an operator-visible run."""
    now = _now_iso()
    previous = _load_status(job_id) or {}
    risk_dicts = _risk_dicts(risks)
    if not risk_dicts and isinstance(previous.get("risks"), list):
        risk_dicts = [dict(item) for item in previous["risks"] if isinstance(item, dict)]

    existing_artifacts = [
        artifact
        for artifact in list_artifact_records(job_id)
        if isinstance(artifact, dict) and artifact.get("type") != "job_status"
    ]
    next_artifacts = _artifact_dicts(artifacts or [])
    artifacts_without_status = [
        artifact for artifact in _dedupe_artifacts(existing_artifacts, next_artifacts)
        if artifact.get("type") != "job_status"
    ]

    steps = _merge_steps(
        previous.get("steps") if isinstance(previous.get("steps"), list) else _empty_steps(job_type),
        job_type=job_type,
        stage=stage,
        step_status=step_status,
        message=message,
        updated_at=now,
    )
    progress = 100 if status == "completed" else _progress_percent(steps)
    details_payload = details or previous.get("details") or {}
    payload = {
        "job_id": job_id,
        "job_type": job_type,
        "status": status,
        "target_id": target_id,
        "risk_level": risk_level,
        "started_at": previous.get("started_at") or now,
        "finished_at": now if status in TERMINAL_STATUSES else None,
        "current_stage": stage,
        "message": message,
        "progress_percent": progress,
        "steps": steps,
        "artifact_count": len(artifacts_without_status),
        "risk_count": len(risk_dicts),
        "artifacts": artifacts_without_status,
        "risks": risk_dicts,
        "details": restore_trusted_actor_evidence(details_payload, redact_secrets(details_payload)),
        "updated_at": now,
    }

    with session_scope() as session:
        row = session.get(JobRunRecord, job_id)
        if row is None:
            row = JobRunRecord(
                job_id=job_id,
                job_type=job_type,
                status=status,
                target_id=target_id,
                risk_level=risk_level,
                started_at=str(payload["started_at"]),
                finished_at=payload["finished_at"],
                current_stage=stage,
                message=message,
                progress_percent=progress,
                steps=steps,
                risks=risk_dicts,
                details=payload["details"],
                artifact_count=len(artifacts_without_status),
                risk_count=len(risk_dicts),
                updated_at=now,
            )
            session.add(row)
        else:
            row.job_type = job_type
            row.status = status
            row.target_id = target_id
            row.risk_level = risk_level
            row.finished_at = payload["finished_at"]
            row.current_stage = stage
            row.message = message
            row.progress_percent = progress
            row.steps = steps
            row.risks = risk_dicts
            row.details = payload["details"]
            row.artifact_count = len(artifacts_without_status)
            row.risk_count = len(risk_dicts)
            row.updated_at = now

    status_artifact = _write_status_artifact(job_id, payload)
    all_artifacts = _dedupe_artifacts(artifacts_without_status, [status_artifact])
    payload["artifacts"] = all_artifacts
    payload["artifact_count"] = len(all_artifacts)
    with session_scope() as session:
        row = session.get(JobRunRecord, job_id)
        if row is not None:
            row.artifact_count = len(all_artifacts)
    return payload


def list_job_runs() -> list[dict[str, Any]]:
    try:
        with session_scope() as session:
            rows = session.scalars(select(JobRunRecord).order_by(JobRunRecord.updated_at.desc())).all()
            return [_row_to_payload(row) for row in rows]
    except Exception:
        return []


def get_job_run(job_id: str) -> dict[str, Any] | None:
    try:
        return _load_status(job_id)
    except Exception:
        return None
