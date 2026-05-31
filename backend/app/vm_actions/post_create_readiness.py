"""Local-only post-create readiness evidence recorder."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.auth.roles import actor_detail_fields, actor_evidence
from app.jobs.artifacts import write_json_artifact
from app.jobs.runs import get_job_run, record_job_run, run_dir

ALLOWED_TOP_LEVEL_KEYS = {
    "post_create_readiness_evidence_acknowledged",
    "evidence_id",
    "idempotency_key",
    "summary",
    "limitations",
    "checks",
}
ALLOWED_CHECK_KEYS = {"name", "status", "observed_at", "summary", "evidence_ref"}
ALLOWED_CHECK_STATUSES = {
    "passed",
    "failed",
    "skipped",
    "unavailable",
    "unapproved",
    "not_run",
    "unknown",
}
DISALLOWED_KEY_MARKERS = {
    "ansible",
    "checknow",
    "cmd",
    "command",
    "credential",
    "endpoint",
    "guestagent",
    "logs",
    "password",
    "privatekey",
    "proxmoxendpoint",
    "rawpayload",
    "runlivechecks",
    "script",
    "secret",
    "shell",
    "ssh",
    "stderr",
    "stdout",
    "token",
    "url",
}

MAX_PAYLOAD_BYTES = 16_000
MAX_ID_LENGTH = 160
MAX_SUMMARY_LENGTH = 1_000
MAX_LIMITATIONS_LENGTH = 1_000
MAX_CHECKS = 25
MAX_CHECK_NAME_LENGTH = 120
MAX_CHECK_SUMMARY_LENGTH = 500
MAX_CHECK_EVIDENCE_REF_LENGTH = 240
MAX_OBSERVED_AT_LENGTH = 80

SECRET_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/\-]+=*", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\bPVEAPIToken\s*=", re.IGNORECASE),
    re.compile(r"\b[\w.+-]+@[\w.-]+![\w.-]+\s*=\s*\S+"),
    re.compile(r"\b(?:password|token|secret)\s*=\s*\S+", re.IGNORECASE),
    re.compile(
        r"(?m)(?:^|\s)(?:sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com|ssh-ed25519|ssh-rsa|rsa-sha2-256|rsa-sha2-512|ecdsa-sha2-[A-Za-z0-9@._+-]+)\s+[A-Za-z0-9+/=]+"
    ),
)


class PostCreateReadinessError(RuntimeError):
    """Raised when local post-create readiness evidence cannot be recorded."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = dict(details or {})

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "proxmox_mutation_enabled": False,
            "live_checks_performed_by_gjallar": False,
            "allowed_actions": [],
            "side_effects": [],
            **self.details,
        }


def _safe_segment(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value)).strip("-")
    return safe[:80] or "target"


def _normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _path(parent: str, key: Any) -> str:
    if isinstance(key, int):
        return f"{parent}[{key}]"
    return f"{parent}.{key}" if parent else f"$.{key}"


def _safe_target(node_id: str, vmid: int) -> dict[str, Any]:
    return {"node_id": str(node_id), "vmid": int(vmid)}


def _boundary() -> dict[str, Any]:
    return {
        "side_effects": [],
        "proxmox_mutation_enabled": False,
        "live_checks_performed_by_gjallar": False,
        "allowed_actions": [],
    }


def build_post_create_readiness_job_id(*, node_id: str, vmid: int, evidence_identity: str) -> str:
    digest = hashlib.sha256(f"{node_id}:{int(vmid)}:{evidence_identity}".encode("utf-8")).hexdigest()[:16]
    return f"post-create-readiness-{_safe_segment(node_id)}-{int(vmid)}-{digest}"


def _raise_schema(message: str, *, field: str = "$", code: str = "POST_CREATE_READINESS_INVALID_SCHEMA") -> None:
    raise PostCreateReadinessError(
        code,
        message,
        status_code=422,
        details={"field": field},
    )


def _reject_disallowed_keys(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = _normalized_key(key)
            if normalized in DISALLOWED_KEY_MARKERS or any(marker in normalized for marker in DISALLOWED_KEY_MARKERS):
                raise PostCreateReadinessError(
                    "POST_CREATE_READINESS_DISALLOWED_FIELD",
                    "Post-create readiness evidence cannot include live-check, command, endpoint, log, or credential fields",
                    status_code=422,
                    details={"field": _path(path, key)},
                )
            _reject_disallowed_keys(item, path=_path(path, key))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _reject_disallowed_keys(item, path=_path(path, index))


def _reject_secret_values(value: Any, *, path: str = "$") -> None:
    if isinstance(value, str):
        if any(pattern.search(value) for pattern in SECRET_VALUE_PATTERNS):
            raise PostCreateReadinessError(
                "POST_CREATE_READINESS_SECRET_VALUE_REJECTED",
                "Post-create readiness evidence cannot include secret or key material",
                status_code=422,
                details={"field": path},
            )
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_secret_values(item, path=_path(path, key))
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for index, item in enumerate(value):
            _reject_secret_values(item, path=_path(path, index))


def _reject_oversized_payload(payload: dict[str, Any]) -> None:
    try:
        size = len(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise PostCreateReadinessError(
            "POST_CREATE_READINESS_INVALID_SCHEMA",
            "Post-create readiness evidence must be JSON-serializable",
            status_code=422,
            details={"field": "$"},
        ) from exc
    if size > MAX_PAYLOAD_BYTES:
        _raise_schema("Post-create readiness evidence payload is too large", field="$")


def _require_narrow_top_level(payload: dict[str, Any]) -> None:
    extras = sorted(str(key) for key in payload if key not in ALLOWED_TOP_LEVEL_KEYS)
    if extras:
        _raise_schema("Post-create readiness evidence contains unsupported fields", field=f"$.{extras[0]}")


def _text_field(
    payload: Mapping[str, Any],
    key: str,
    *,
    max_length: int,
    required: bool = False,
    field: str | None = None,
) -> str:
    value = payload.get(key)
    path = field or f"$.{key}"
    if value is None:
        if required:
            _raise_schema(f"{key} is required", field=path)
        return ""
    if not isinstance(value, str):
        _raise_schema(f"{key} must be a string", field=path)
    text = value.strip()
    if required and not text:
        _raise_schema(f"{key} must be non-empty", field=path)
    if len(text) > max_length:
        _raise_schema(f"{key} is too long", field=path)
    return text


def _identity(payload: Mapping[str, Any]) -> tuple[str, str, str]:
    evidence_id = _text_field(payload, "evidence_id", max_length=MAX_ID_LENGTH)
    idempotency_key = _text_field(payload, "idempotency_key", max_length=MAX_ID_LENGTH)
    if evidence_id:
        return evidence_id, evidence_id, idempotency_key
    if idempotency_key:
        return idempotency_key, evidence_id, idempotency_key
    raise PostCreateReadinessError(
        "POST_CREATE_READINESS_IDENTITY_REQUIRED",
        "A non-empty evidence_id or idempotency_key is required before recording post-create readiness evidence",
        details=_boundary(),
    )


def _validate_checks(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    checks = payload.get("checks", [])
    if checks is None:
        return []
    if not isinstance(checks, list):
        _raise_schema("checks must be an array", field="$.checks")
    if len(checks) > MAX_CHECKS:
        _raise_schema("checks contains too many entries", field="$.checks")

    normalized_checks: list[dict[str, str]] = []
    for index, check in enumerate(checks):
        path = f"$.checks[{index}]"
        if not isinstance(check, Mapping):
            _raise_schema("each check must be an object", field=path)
        extras = sorted(str(key) for key in check if key not in ALLOWED_CHECK_KEYS)
        if extras:
            _raise_schema("check contains unsupported fields", field=f"{path}.{extras[0]}")

        status = check.get("status")
        if not isinstance(status, str) or status not in ALLOWED_CHECK_STATUSES:
            _raise_schema("check status must be one of the exact lowercase allowed statuses", field=f"{path}.status")

        normalized: dict[str, str] = {
            "name": _text_field(check, "name", max_length=MAX_CHECK_NAME_LENGTH, required=True, field=f"{path}.name"),
            "status": status,
        }
        observed_at = _text_field(check, "observed_at", max_length=MAX_OBSERVED_AT_LENGTH, field=f"{path}.observed_at")
        summary = _text_field(check, "summary", max_length=MAX_CHECK_SUMMARY_LENGTH, field=f"{path}.summary")
        evidence_ref = _text_field(check, "evidence_ref", max_length=MAX_CHECK_EVIDENCE_REF_LENGTH, field=f"{path}.evidence_ref")
        if observed_at:
            normalized["observed_at"] = observed_at
        if summary:
            normalized["summary"] = summary
        if evidence_ref:
            normalized["evidence_ref"] = evidence_ref
        normalized_checks.append(normalized)
    return normalized_checks


def _validated_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("post_create_readiness_evidence_acknowledged") is not True:
        raise PostCreateReadinessError(
            "POST_CREATE_READINESS_ACK_REQUIRED",
            "post_create_readiness_evidence_acknowledged=true is required before recording evidence",
            details=_boundary(),
        )
    _reject_oversized_payload(payload)
    _reject_disallowed_keys(payload)
    _reject_secret_values(payload)
    _require_narrow_top_level(payload)
    identity, evidence_id, idempotency_key = _identity(payload)
    checks = _validate_checks(payload)
    return {
        "identity": identity,
        "evidence_id": evidence_id,
        "idempotency_key": idempotency_key,
        "summary": _text_field(payload, "summary", max_length=MAX_SUMMARY_LENGTH),
        "limitations": _text_field(payload, "limitations", max_length=MAX_LIMITATIONS_LENGTH),
        "checks": checks,
    }


def _status_counts(checks: list[dict[str, str]]) -> dict[str, int]:
    counts = {status: 0 for status in ALLOWED_CHECK_STATUSES}
    for check in checks:
        counts[check["status"]] += 1
    return {status: counts[status] for status in sorted(counts) if counts[status]}


def _artifact_dict(artifact: Any) -> dict[str, Any]:
    return artifact.to_dict() if hasattr(artifact, "to_dict") else dict(artifact)


def _target_id(node_id: str, vmid: int) -> str:
    return f"{node_id}:{int(vmid)}"


def _result_from_existing(job: dict[str, Any]) -> dict[str, Any]:
    details = job.get("details") if isinstance(job.get("details"), dict) else {}
    stored = details.get("post_create_readiness_result") if isinstance(details.get("post_create_readiness_result"), dict) else {}
    artifacts = [artifact for artifact in job.get("artifacts") or [] if isinstance(artifact, dict)]
    evidence_artifacts = [artifact for artifact in artifacts if artifact.get("type") == "post_create_readiness_evidence"]
    result = {
        **stored,
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "message": job.get("message") or stored.get("message") or "Existing post-create readiness evidence returned.",
        "artifacts": stored.get("artifacts") or evidence_artifacts,
        "artifact": stored.get("artifact") or (evidence_artifacts[0] if evidence_artifacts else {}),
        "idempotent_replay": True,
        **_boundary(),
    }
    return result


def record_post_create_readiness_evidence(
    *,
    node_id: str,
    vmid: int,
    payload: dict[str, Any] | None,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record operator-supplied sanitized readiness evidence for an existing VM.

    This function is intentionally local-only. It performs no inventory,
    Proxmox, SSH, Ansible, guest-agent, shell, or network calls.
    """
    request_payload = dict(payload or {})
    evidence = _validated_evidence(request_payload)
    job_id = build_post_create_readiness_job_id(
        node_id=node_id,
        vmid=vmid,
        evidence_identity=evidence["identity"],
    )
    existing = get_job_run(job_id)
    if existing:
        return _result_from_existing(existing)

    actor_payload = actor_evidence(actor) if actor is not None else {}
    target = _safe_target(node_id, vmid)
    checks = list(evidence["checks"])
    counts = _status_counts(checks)
    evidence_summary = {
        "evidence_id": evidence["evidence_id"],
        "idempotency_key": evidence["idempotency_key"],
        "summary": evidence["summary"],
        "limitations": evidence["limitations"],
        "check_count": len(checks),
        "status_counts": counts,
    }
    artifact_payload = {
        "job_id": job_id,
        "operation": "post_create_readiness_evidence",
        "target": target,
        "evidence": {
            **evidence_summary,
            "checks": checks,
        },
        "boundary": _boundary(),
    }
    artifact_payload.update(actor_detail_fields(actor_payload))
    artifact = _artifact_dict(
        write_json_artifact(
            run_dir=run_dir(job_id),
            job_id=job_id,
            artifact_type="post_create_readiness_evidence",
            filename="post_create_readiness_evidence.json",
            payload=artifact_payload,
        )
    )

    result = {
        "job_id": job_id,
        "status": "completed",
        "message": "Post-create readiness evidence was recorded locally.",
        "target": target,
        "evidence_summary": evidence_summary,
        "checks": checks,
        "artifact": artifact,
        "artifacts": [artifact],
        "idempotent_replay": False,
        **_boundary(),
    }
    result.update(actor_detail_fields(actor_payload))
    details = {
        "target": target,
        "post_create_readiness": {
            "evidence_id": evidence["evidence_id"],
            "idempotency_key": evidence["idempotency_key"],
            "check_count": len(checks),
            "status_counts": counts,
            **_boundary(),
        },
        "post_create_readiness_result": result,
    }
    details.update(actor_detail_fields(actor_payload))
    record_job_run(
        job_id=job_id,
        job_type="post_create_readiness",
        status="completed",
        target_id=_target_id(node_id, vmid),
        risk_level="unknown",
        stage="evidence_record",
        step_status="completed",
        message=result["message"],
        artifacts=[artifact],
        risks=[],
        details=details,
    )
    return result
