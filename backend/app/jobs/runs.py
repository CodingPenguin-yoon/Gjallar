"""File-backed job run status records for the /api/v1 Jobs/Runs screen."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.redaction import redact_secrets

STEP_ORDER = ["draft", "preflight", "plan", "approval", "workspace", "commit", "create"]
STEP_LABELS = {
    "draft": "요청 입력",
    "preflight": "사전 검토",
    "plan": "생성 계획",
    "approval": "승인 확인",
    "workspace": "생성 준비",
    "commit": "요청 저장",
    "create": "VM 생성",
}
TERMINAL_STATUSES = {"completed", "failed", "blocked"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_segment(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value)).strip("-")
    return safe[:120] or "job"


def runs_root() -> Path:
    configured = os.getenv("GJALLAR_RUNS_ROOT")
    if configured:
        return Path(configured).expanduser()
    return Path(tempfile.gettempdir()) / "gjallar-set6-api-preview"


def run_dir(job_id: str) -> Path:
    return runs_root() / _safe_segment(job_id)


def _status_path(job_id: str) -> Path:
    return run_dir(job_id) / "job_status.json"


def _status_artifact(job_id: str, created_at: str) -> dict[str, Any]:
    path = _status_path(job_id)
    checksum = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
    return {
        "artifact_id": f"artifact_status_{_safe_segment(job_id)}",
        "job_id": job_id,
        "type": "job_status",
        "path": str(path),
        "checksum": checksum,
        "created_at": created_at,
    }


def _empty_steps() -> list[dict[str, Any]]:
    return [
        {"id": step, "label": STEP_LABELS[step], "status": "pending", "updated_at": ""}
        for step in STEP_ORDER
    ]


def _merge_steps(
    current_steps: list[dict[str, Any]],
    *,
    stage: str,
    step_status: str,
    message: str,
    updated_at: str,
) -> list[dict[str, Any]]:
    by_id = {step.get("id"): dict(step) for step in current_steps if step.get("id")}
    steps = []
    stage_index = STEP_ORDER.index(stage) if stage in STEP_ORDER else -1
    for index, step_id in enumerate(STEP_ORDER):
        step = by_id.get(step_id, {"id": step_id, "label": STEP_LABELS[step_id]})
        previous_status = str(step.get("status") or "pending")
        if stage_index < 0:
            next_status = previous_status
        elif index < stage_index:
            next_status = "completed"
        elif index == stage_index:
            next_status = step_status
        else:
            next_status = "pending"
        steps.append(
            {
                "id": step_id,
                "label": STEP_LABELS[step_id],
                "status": next_status,
                "message": message if index == stage_index else str(step.get("message") or ""),
                "updated_at": updated_at if index <= stage_index else str(step.get("updated_at") or ""),
            }
        )
    return steps


def _progress_percent(steps: list[dict[str, Any]]) -> int:
    score = 0.0
    for step in steps:
        status = str(step.get("status") or "")
        if status == "completed":
            score += 1.0
        elif status in {"running", "in_progress"}:
            score += 0.5
    return int(round((score / len(STEP_ORDER)) * 100))


def _load_status(job_id: str) -> dict[str, Any] | None:
    path = _status_path(job_id)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _artifact_dicts(artifacts: list[Any]) -> list[dict[str, Any]]:
    result = []
    for artifact in artifacts:
        if hasattr(artifact, "to_dict"):
            result.append(artifact.to_dict())
        elif isinstance(artifact, dict):
            result.append(dict(artifact))
    return result


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
    """Persist the latest job status for a Create VM run."""
    now = _now_iso()
    previous = _load_status(job_id) or {}
    run_path = run_dir(job_id)
    run_path.mkdir(parents=True, exist_ok=True)

    risk_dicts = []
    for risk in risks or []:
        if hasattr(risk, "to_dict"):
            risk_dicts.append(risk.to_dict())
        elif isinstance(risk, dict):
            risk_dicts.append(dict(risk))

    existing_artifacts = [
        artifact for artifact in (previous.get("artifacts") if isinstance(previous.get("artifacts"), list) else [])
        if isinstance(artifact, dict) and artifact.get("type") != "job_status"
    ]
    next_artifacts = _artifact_dicts(artifacts or [])
    artifact_index = {
        str(item.get("artifact_id") or item.get("id") or item.get("path")): item
        for item in [*existing_artifacts, *next_artifacts]
        if isinstance(item, dict)
    }

    steps = _merge_steps(
        previous.get("steps") if isinstance(previous.get("steps"), list) else _empty_steps(),
        stage=stage,
        step_status=step_status,
        message=message,
        updated_at=now,
    )
    progress = 100 if status == "completed" else _progress_percent(steps)
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
        "artifact_count": len(artifact_index),
        "risk_count": len(risk_dicts),
        "artifacts": list(artifact_index.values()),
        "risks": risk_dicts,
        "details": redact_secrets(details or previous.get("details") or {}),
        "updated_at": now,
    }
    path = _status_path(job_id)
    path.write_text(json.dumps(redact_secrets(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    payload["artifact_count"] = len(artifact_index) + 1
    payload["artifacts"] = [*payload["artifacts"], _status_artifact(job_id, now)]
    path.write_text(json.dumps(redact_secrets(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def list_job_runs() -> list[dict[str, Any]]:
    runs = []
    for path in sorted(runs_root().glob("*/job_status.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("job_id"):
            runs.append(payload)
    return sorted(runs, key=lambda item: str(item.get("updated_at") or item.get("started_at") or ""), reverse=True)


def get_job_run(job_id: str) -> dict[str, Any] | None:
    return _load_status(job_id)
