"""Real file-backed artifact writers for Gjallar job runs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from app.core.redaction import redact_secrets
from app.jobs.models import ArtifactRecord


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _artifact_path(run_dir: Path | str, filename: str) -> Path:
    """Return a safe file path under the caller-provided run directory."""
    name = Path(filename)
    if name.name != filename:
        raise ValueError("artifact filename must not contain path separators")
    path = Path(run_dir) / name.name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _checksum_for_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _artifact_id(job_id: str, artifact_type: str, filename: str) -> str:
    safe_type = artifact_type.replace("-", "_").replace("/", "_")
    safe_job = job_id.replace("-", "_").replace("/", "_")
    safe_file = Path(filename).stem.replace("-", "_")
    return f"artifact_{safe_type}_{safe_job}_{safe_file}"


def _record(*, job_id: str, artifact_type: str, filename: str, path: Path, content: bytes) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=_artifact_id(job_id, artifact_type, filename),
        job_id=job_id,
        type=artifact_type,
        path=str(path),
        checksum=_checksum_for_bytes(content),
        created_at=_now_iso(),
    )


def write_json_artifact(
    *,
    run_dir: Path | str,
    job_id: str,
    artifact_type: str,
    filename: str,
    payload: Any,
) -> ArtifactRecord:
    """Write a redacted JSON artifact and return checksum-backed metadata."""
    path = _artifact_path(run_dir, filename)
    redacted_payload = redact_secrets(payload)
    text = json.dumps(redacted_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    content = text.encode("utf-8")
    path.write_bytes(content)
    return _record(
        job_id=job_id,
        artifact_type=artifact_type,
        filename=filename,
        path=path,
        content=content,
    )


def write_text_artifact(
    *,
    run_dir: Path | str,
    job_id: str,
    artifact_type: str,
    filename: str,
    text: str,
) -> ArtifactRecord:
    """Write a redacted text artifact and return checksum-backed metadata."""
    path = _artifact_path(run_dir, filename)
    redacted_text = str(redact_secrets(text))
    content = redacted_text.encode("utf-8")
    path.write_bytes(content)
    return _record(
        job_id=job_id,
        artifact_type=artifact_type,
        filename=filename,
        path=path,
        content=content,
    )


def write_yaml_artifact(
    *,
    run_dir: Path | str,
    job_id: str,
    artifact_type: str,
    filename: str,
    payload: Any,
) -> ArtifactRecord:
    """Write a redacted YAML artifact from structured data."""
    path = _artifact_path(run_dir, filename)
    redacted_payload = redact_secrets(payload)
    text = yaml.safe_dump(redacted_payload, sort_keys=False, allow_unicode=True)
    content = text.encode("utf-8")
    path.write_bytes(content)
    return _record(
        job_id=job_id,
        artifact_type=artifact_type,
        filename=filename,
        path=path,
        content=content,
    )
