"""DB-backed artifact writers for Gjallar job runs."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.roles import restore_trusted_actor_evidence
from app.core.redaction import redact_secrets
from app.db.models import JobArtifactRecord
from app.db.session import session_scope
from app.jobs.models import ArtifactRecord


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _checksum_for_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _safe_token(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", str(value)).strip("_")[:120] or "artifact"


def _artifact_id(job_id: str, artifact_type: str, filename: str) -> str:
    safe_type = _safe_token(artifact_type)
    safe_job = _safe_token(job_id)
    safe_file = _safe_token(Path(filename).stem)
    return f"artifact_{safe_type}_{safe_job}_{safe_file}"


def _db_path(artifact_id: str) -> str:
    return f"db://job-artifacts/{artifact_id}"


def _record_from_row(row: JobArtifactRecord) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=row.artifact_id,
        job_id=row.job_id,
        type=row.type,
        path=row.path,
        checksum=row.checksum,
        created_at=row.created_at,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        storage_backend=row.storage_backend,
    )


def _artifact_row_in_session(
    session: Session,
    artifact_id: str,
    *,
    expected_job_id: str | None = None,
    expected_artifact_type: str | None = None,
    lock_for_update: bool = False,
) -> JobArtifactRecord | None:
    statement = select(JobArtifactRecord).where(JobArtifactRecord.artifact_id == artifact_id)
    if lock_for_update:
        statement = statement.with_for_update()
    row = session.scalar(statement)
    if row is None:
        return None
    if expected_job_id is not None and row.job_id != expected_job_id:
        raise ValueError("Artifact identity belongs to a different job or artifact type")
    if expected_artifact_type is not None and row.type != expected_artifact_type:
        raise ValueError("Artifact identity belongs to a different job or artifact type")
    return row


def get_artifact_record_in_session(
    session: Session,
    artifact_id: str,
    *,
    expected_job_id: str | None = None,
    expected_artifact_type: str | None = None,
) -> ArtifactRecord | None:
    """Return exact artifact metadata without opening or committing a transaction."""
    row = _artifact_row_in_session(
        session,
        artifact_id,
        expected_job_id=expected_job_id,
        expected_artifact_type=expected_artifact_type,
        lock_for_update=expected_job_id is not None or expected_artifact_type is not None,
    )
    return _record_from_row(row) if row is not None else None


def list_artifact_records_in_session(session: Session, job_id: str) -> list[dict[str, Any]]:
    """Return one job's artifact metadata through the caller-owned transaction."""
    rows = session.scalars(
        select(JobArtifactRecord)
        .where(JobArtifactRecord.job_id == job_id)
        .order_by(JobArtifactRecord.created_at.asc(), JobArtifactRecord.artifact_id.asc())
    ).all()
    return [_record_from_row(row).to_dict() for row in rows]


def _upsert_artifact_in_session(
    session: Session,
    *,
    job_id: str,
    artifact_type: str,
    filename: str,
    text: str,
    content_type: str,
) -> ArtifactRecord:
    content = text.encode("utf-8")
    artifact_id = _artifact_id(job_id, artifact_type, filename)
    now = _now_iso()
    checksum = _checksum_for_bytes(content)
    row = _artifact_row_in_session(
        session,
        artifact_id,
        expected_job_id=job_id,
        expected_artifact_type=artifact_type,
        lock_for_update=True,
    )
    if row is None:
        row = JobArtifactRecord(
            artifact_id=artifact_id,
            job_id=job_id,
            type=artifact_type,
            path=_db_path(artifact_id),
            checksum=checksum,
            content_type=content_type,
            content_text=text,
            size_bytes=len(content),
            storage_backend="db",
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.path = _db_path(artifact_id)
        row.checksum = checksum
        row.content_type = content_type
        row.content_text = text
        row.size_bytes = len(content)
        row.storage_backend = "db"
        row.updated_at = now
    session.flush()
    return _record_from_row(row)


def write_json_artifact_in_session(
    session: Session,
    *,
    run_dir: Path | str,
    job_id: str,
    artifact_type: str,
    filename: str,
    payload: Any,
) -> ArtifactRecord:
    """Store redacted JSON through a caller-owned transaction without committing it."""
    _ = run_dir
    redacted_payload = restore_trusted_actor_evidence(payload, redact_secrets(payload))
    text = json.dumps(redacted_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return _upsert_artifact_in_session(
        session,
        job_id=job_id,
        artifact_type=artifact_type,
        filename=filename,
        text=text,
        content_type="application/json",
    )


def write_json_artifact(
    *,
    run_dir: Path | str,
    job_id: str,
    artifact_type: str,
    filename: str,
    payload: Any,
) -> ArtifactRecord:
    """Store a redacted JSON artifact and return checksum-backed metadata."""
    with session_scope() as session:
        return write_json_artifact_in_session(
            session,
            run_dir=run_dir,
            job_id=job_id,
            artifact_type=artifact_type,
            filename=filename,
            payload=payload,
        )


def write_text_artifact(
    *,
    run_dir: Path | str,
    job_id: str,
    artifact_type: str,
    filename: str,
    text: str,
) -> ArtifactRecord:
    """Store a redacted text artifact and return checksum-backed metadata."""
    _ = run_dir
    redacted_text = str(redact_secrets(text))
    with session_scope() as session:
        return _upsert_artifact_in_session(
            session,
            job_id=job_id,
            artifact_type=artifact_type,
            filename=filename,
            text=redacted_text,
            content_type="text/plain",
        )


def write_yaml_artifact(
    *,
    run_dir: Path | str,
    job_id: str,
    artifact_type: str,
    filename: str,
    payload: Any,
) -> ArtifactRecord:
    """Store a redacted YAML artifact from structured data."""
    _ = run_dir
    redacted_payload = redact_secrets(payload)
    text = yaml.safe_dump(redacted_payload, sort_keys=False, allow_unicode=True)
    with session_scope() as session:
        return _upsert_artifact_in_session(
            session,
            job_id=job_id,
            artifact_type=artifact_type,
            filename=filename,
            text=text,
            content_type="application/yaml",
        )


def get_artifact_record(artifact_id: str) -> ArtifactRecord | None:
    """Return artifact metadata by id."""
    with session_scope() as session:
        return get_artifact_record_in_session(session, artifact_id)


def list_artifact_records(job_id: str) -> list[dict[str, Any]]:
    """Return artifact metadata for a job without exposing payload content."""
    with session_scope() as session:
        return list_artifact_records_in_session(session, job_id)


def _artifact_id_from_reference(reference: ArtifactRecord | dict[str, Any] | str) -> str:
    if isinstance(reference, ArtifactRecord):
        return reference.artifact_id
    if isinstance(reference, dict):
        artifact_id = str(reference.get("artifact_id") or reference.get("id") or "").strip()
        if artifact_id:
            return artifact_id
        reference = str(reference.get("path") or "")
    text = str(reference or "").strip()
    if text.startswith("db://job-artifacts/"):
        return text.removeprefix("db://job-artifacts/")
    return text


def read_artifact_text_in_session(
    session: Session,
    reference: ArtifactRecord | dict[str, Any] | str,
    *,
    expected_job_id: str | None = None,
    expected_artifact_type: str | None = None,
    expected_checksum: str | None = None,
) -> str:
    """Read exact artifact content without opening or committing a transaction."""
    artifact_id = _artifact_id_from_reference(reference)
    if artifact_id:
        row = _artifact_row_in_session(
            session,
            artifact_id,
            expected_job_id=expected_job_id,
            expected_artifact_type=expected_artifact_type,
            lock_for_update=any(
                value is not None
                for value in (expected_job_id, expected_artifact_type, expected_checksum)
            ),
        )
        if row is not None:
            if expected_checksum is not None and row.checksum != expected_checksum:
                raise ValueError("Artifact checksum does not match expected evidence")
            if (
                expected_checksum is not None
                and _checksum_for_bytes(row.content_text.encode("utf-8")) != expected_checksum
            ):
                raise ValueError("Artifact content checksum does not match expected evidence")
            return row.content_text

    if any(value is not None for value in (expected_job_id, expected_artifact_type, expected_checksum)):
        raise FileNotFoundError(f"artifact content is not available: {artifact_id}")

    path_text = str(reference.get("path") if isinstance(reference, dict) else reference)
    if path_text and not path_text.startswith("db://"):
        path = Path(path_text).expanduser()
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"artifact content is not available: {artifact_id or path_text}")


def read_artifact_text(reference: ArtifactRecord | dict[str, Any] | str) -> str:
    """Read artifact content from DB, with a legacy file-path fallback."""
    with session_scope() as session:
        return read_artifact_text_in_session(session, reference)
