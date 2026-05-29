"""Local-only DRS approval packet and migration job intent helpers."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from app.auth.roles import actor_detail_fields
from app.core.redaction import redact_secrets
from app.db.models import DrsApprovalPacketRecord, DrsMigrationJobRecord
from app.db.session import session_scope
from app.jobs.artifacts import write_json_artifact
from app.jobs.runs import record_job_run, run_dir

DRS_MIGRATION_JOB_TYPE = "drs_migration"
LIVE_EXECUTION_BLOCKER = "live_migration_execution_not_implemented"
PROXMOX_NOT_COLLECTED_CHECKS = (
    "proxmox_active_task",
    "proxmox_ha_state",
    "proxmox_cluster_quorum",
)


class DrsApprovalBlockedError(Exception):
    """Raised when local DRS approval/job intent cannot be created."""

    def __init__(self, *, code: str, message: str, readiness: dict[str, Any]) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.readiness = readiness

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "approval_readiness": self.readiness,
            "side_effects": [],
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _as_text(value: Any, fallback: str = "") -> str:
    text = str(value if value is not None else "").strip()
    return text or fallback


def _as_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _strict_bool(value: Any) -> bool:
    return value is True


def _safe_segment(value: Any) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", _as_text(value, "unknown")).strip("-")
    return safe[:80] or "unknown"


def _checksum_payload(payload: Any) -> str:
    redacted = redact_secrets(payload)
    text = json.dumps(redacted, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _artifact_dict(artifact: Any) -> dict[str, Any]:
    return artifact.to_dict() if hasattr(artifact, "to_dict") else dict(artifact)


def _identity_evidence(check_result: dict[str, Any]) -> dict[str, Any]:
    recommendation = check_result.get("recommendation") if isinstance(check_result.get("recommendation"), dict) else {}
    evidence = check_result.get("identity_evidence") or recommendation.get("identity_evidence") or {}
    return dict(evidence) if isinstance(evidence, dict) else {}


def _policy_evidence(check_result: dict[str, Any]) -> dict[str, Any]:
    recommendation = check_result.get("recommendation") if isinstance(check_result.get("recommendation"), dict) else {}
    evidence = check_result.get("policy_evidence") or recommendation.get("policy_evidence") or {}
    return dict(evidence) if isinstance(evidence, dict) else {}


def _recommendation(check_result: dict[str, Any]) -> dict[str, Any]:
    recommendation = check_result.get("recommendation")
    return dict(recommendation) if isinstance(recommendation, dict) else {}


def _locator(identity_evidence: dict[str, Any]) -> dict[str, Any]:
    components = identity_evidence.get("fingerprint_components")
    if not isinstance(components, dict):
        return {}
    locator = components.get("locator")
    return dict(locator) if isinstance(locator, dict) else {}


def _cluster_id(check_result: dict[str, Any]) -> str:
    identity = _identity_evidence(check_result)
    locator = _locator(identity)
    if locator.get("cluster_id"):
        return _as_text(locator.get("cluster_id"))
    operation_lock = _operation_lock_evidence(check_result)
    return _as_text(operation_lock.get("cluster_id"), "gjallar-mvp")


def _compact_identity(identity_evidence: dict[str, Any]) -> dict[str, Any]:
    locator = _locator(identity_evidence)
    return {
        "vm_identity_id": identity_evidence.get("vm_identity_id"),
        "stable_fingerprint": _as_text(identity_evidence.get("stable_fingerprint")),
        "match_confidence": _as_text(identity_evidence.get("match_confidence"), "unknown"),
        "match_reason": _as_text(identity_evidence.get("match_reason")),
        "identity_status": _as_text(identity_evidence.get("identity_status"), "unknown"),
        "conflict_signal": identity_evidence.get("conflict_signal") is True,
        "locator": {
            "cluster_id": _as_text(locator.get("cluster_id"), "gjallar-mvp"),
            "node_id": _as_text(locator.get("node_id")),
            "vmid": _as_int(locator.get("vmid"), 0),
            "name": _as_text(locator.get("name")),
        },
    }


def _compact_policy(policy_evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "policy_id": policy_evidence.get("policy_id"),
        "vm_identity_id": policy_evidence.get("vm_identity_id"),
        "policy": _as_text(policy_evidence.get("policy"), "unknown"),
        "source": _as_text(policy_evidence.get("source"), "default"),
        "updated_by": policy_evidence.get("updated_by"),
    }


def _operation_lock_evidence(check_result: dict[str, Any]) -> dict[str, Any]:
    checks = (check_result.get("check") or {}).get("checks") if isinstance(check_result.get("check"), dict) else {}
    operation_lock = checks.get("operation_lock") if isinstance(checks, dict) else {}
    evidence = operation_lock.get("evidence") if isinstance(operation_lock, dict) else {}
    return dict(evidence) if isinstance(evidence, dict) else {}


def _compact_lock(lock: dict[str, Any]) -> dict[str, Any]:
    return {
        "operation_lock_id": lock.get("operation_lock_id"),
        "status": lock.get("status"),
        "scope_type": lock.get("scope_type"),
        "scope_key": lock.get("scope_key"),
        "vm_identity_id": lock.get("vm_identity_id"),
        "vmid": lock.get("vmid"),
        "source_node_id": lock.get("source_node_id"),
        "target_node_id": lock.get("target_node_id"),
        "owner_id": lock.get("owner_id"),
        "reason": lock.get("reason"),
    }


def _compact_operation_lock_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    matching_locks = [
        _compact_lock(lock)
        for lock in _as_list(evidence.get("matching_locks"))
        if isinstance(lock, dict)
    ]
    return {
        "operation_type": evidence.get("operation_type"),
        "cluster_id": evidence.get("cluster_id"),
        "checked_scopes": [
            {"scope_type": scope.get("scope_type"), "scope_key": scope.get("scope_key")}
            for scope in _as_list(evidence.get("checked_scopes"))
            if isinstance(scope, dict)
        ],
        "matching_locks": matching_locks,
        "matching_lock_ids": [
            lock["operation_lock_id"]
            for lock in matching_locks
            if lock.get("operation_lock_id")
        ],
        "matching_statuses": list(evidence.get("matching_statuses") or []),
        "blocking": evidence.get("blocking") is True,
    }


def _check_statuses(check_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    check = check_result.get("check") if isinstance(check_result.get("check"), dict) else {}
    checks = check.get("checks") if isinstance(check.get("checks"), dict) else {}
    result: dict[str, dict[str, Any]] = {}
    for key in sorted(checks):
        item = checks[key] if isinstance(checks[key], dict) else {}
        result[key] = {
            "status": item.get("status"),
            "blocker": item.get("blocker"),
        }
    return result


def _compact_proxmox_conflicts(check_result: dict[str, Any]) -> dict[str, Any]:
    checks = (check_result.get("check") or {}).get("checks") if isinstance(check_result.get("check"), dict) else {}
    proxmox = checks.get("proxmox_conflicts") if isinstance(checks, dict) else {}
    evidence = proxmox.get("evidence") if isinstance(proxmox, dict) else {}
    evidence = evidence if isinstance(evidence, dict) else {}
    return {
        "status": proxmox.get("status") if isinstance(proxmox, dict) else None,
        "blocker": proxmox.get("blocker") if isinstance(proxmox, dict) else None,
        "config_lock": {
            "status": (evidence.get("config_lock") or {}).get("status") if isinstance(evidence.get("config_lock"), dict) else None,
            "blocking": (evidence.get("config_lock") or {}).get("blocking") if isinstance(evidence.get("config_lock"), dict) else None,
            "source": (evidence.get("config_lock") or {}).get("source") if isinstance(evidence.get("config_lock"), dict) else None,
            "lock": (evidence.get("config_lock") or {}).get("lock") if isinstance(evidence.get("config_lock"), dict) else None,
        },
        "active_task": {
            "status": (evidence.get("active_task") or {}).get("status") if isinstance(evidence.get("active_task"), dict) else None,
            "blocking": (evidence.get("active_task") or {}).get("blocking") if isinstance(evidence.get("active_task"), dict) else None,
        },
        "ha_state": {
            "status": (evidence.get("ha_state") or {}).get("status") if isinstance(evidence.get("ha_state"), dict) else None,
            "blocking": (evidence.get("ha_state") or {}).get("blocking") if isinstance(evidence.get("ha_state"), dict) else None,
        },
        "cluster_quorum": {
            "status": (evidence.get("cluster_quorum") or {}).get("status") if isinstance(evidence.get("cluster_quorum"), dict) else None,
            "blocking": (evidence.get("cluster_quorum") or {}).get("blocking") if isinstance(evidence.get("cluster_quorum"), dict) else None,
        },
    }


def compact_recommendation_binding(check_result: dict[str, Any]) -> dict[str, Any]:
    """Return compact recommendation evidence safe to bind with a checksum."""
    recommendation = _recommendation(check_result)
    identity = _identity_evidence(check_result)
    policy = _policy_evidence(check_result)
    return {
        "kind": "drs_recommendation_binding",
        "recommendation_id": _as_text(check_result.get("recommendation_id") or recommendation.get("id")),
        "vmid": _as_int(recommendation.get("vmid"), 0),
        "vm_name": _as_text(recommendation.get("vm_name")),
        "source_node_id": _as_text(recommendation.get("source_node_id")),
        "target_node_id": _as_text(recommendation.get("target_node_id")),
        "risk_level": _as_text(recommendation.get("risk_level"), "unknown"),
        "blockers": list(recommendation.get("blockers") or []),
        "identity": _compact_identity(identity),
        "policy": _compact_policy(policy),
        "estimated_effect": dict(recommendation.get("estimated_effect") or {}),
        "thresholds": dict(recommendation.get("thresholds") or check_result.get("thresholds") or {}),
        "read_only": True,
        "executable": False,
        "allowed_actions": [],
    }


def compact_final_precheck_binding(check_result: dict[str, Any]) -> dict[str, Any]:
    """Return compact final pre-check evidence safe to bind with a checksum."""
    check = check_result.get("check") if isinstance(check_result.get("check"), dict) else {}
    lock_evidence = _compact_operation_lock_evidence(_operation_lock_evidence(check_result))
    return {
        "kind": "drs_final_precheck_binding",
        "recommendation_id": _as_text(check_result.get("recommendation_id")),
        "checked_at": check_result.get("checked_at") or check.get("checked_at"),
        "observed_at": check.get("observed_at"),
        "status": check.get("status"),
        "would_be_executable": check_result.get("would_be_executable") is True,
        "blockers": list(check_result.get("blockers") or []),
        "check_statuses": _check_statuses(check_result),
        "operation_lock": lock_evidence,
        "proxmox_conflicts": _compact_proxmox_conflicts(check_result),
        "read_only": True,
        "executable": False,
        "allowed_actions": [],
    }


def final_precheck_summary(check_result: dict[str, Any]) -> dict[str, Any]:
    binding = compact_final_precheck_binding(check_result)
    return {
        "recommendation_id": binding["recommendation_id"],
        "status": binding["status"],
        "would_be_executable": binding["would_be_executable"],
        "checked_at": binding["checked_at"],
        "observed_at": binding["observed_at"],
        "blockers": binding["blockers"],
        "check_statuses": binding["check_statuses"],
        "operation_lock": binding["operation_lock"],
        "proxmox_conflicts": binding["proxmox_conflicts"],
    }


def _warning_acknowledged_from_payload(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    return _strict_bool(payload.get("warning_acknowledged")) or _strict_bool(payload.get("warningAcknowledged"))


def _warnings_from_check(check_result: dict[str, Any]) -> list[dict[str, Any]]:
    source = check_result.get("warnings")
    if source is None and isinstance(check_result.get("check"), dict):
        source = check_result["check"].get("warnings")
    warnings: list[dict[str, Any]] = []
    for item in _as_list(source):
        if not isinstance(item, dict):
            continue
        code = _as_text(item.get("code"))
        if not code:
            continue
        warnings.append(
            {
                "code": code,
                "message": _as_text(item.get("message"), code),
                "severity": _as_text(item.get("severity"), "warning"),
            }
        )
    return warnings


def _runnable_blockers(check_result: dict[str, Any]) -> list[str]:
    statuses = _check_statuses(check_result)
    blockers = [
        f"{name}_not_collected"
        for name in PROXMOX_NOT_COLLECTED_CHECKS
        if statuses.get(name, {}).get("status") in {"not_collected", "not_implemented"}
    ]
    blockers.append(LIVE_EXECUTION_BLOCKER)
    return blockers


def _approval_blockers(check_result: dict[str, Any], warnings: list[dict[str, Any]], warning_acknowledged: bool) -> list[str]:
    blockers = list(check_result.get("blockers") or [])
    if check_result.get("would_be_executable") is not True and "drs_final_precheck_failed" not in blockers:
        blockers.append("drs_final_precheck_failed")
    if warnings and not warning_acknowledged:
        blockers.append("warnings_not_acknowledged")
    seen: set[str] = set()
    result: list[str] = []
    for blocker in blockers:
        text = _as_text(blocker)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def build_approval_readiness(
    check_result: dict[str, Any],
    *,
    warning_acknowledged: bool = False,
    approved_actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return compact local approval readiness without writing state."""
    recommendation = _recommendation(check_result)
    identity = _identity_evidence(check_result)
    warnings = _warnings_from_check(check_result)
    warning_codes = [warning["code"] for warning in warnings]
    final_passed = check_result.get("would_be_executable") is True
    warnings_satisfied = not warnings or warning_acknowledged is True
    creatable = final_passed and warnings_satisfied
    recommendation_binding = compact_recommendation_binding(check_result)
    precheck_binding = compact_final_precheck_binding(check_result)
    source_node_id = _as_text(recommendation.get("source_node_id") or recommendation_binding.get("source_node_id"))
    target_node_id = _as_text(recommendation.get("target_node_id") or recommendation_binding.get("target_node_id"))
    vm_identity_id = identity.get("vm_identity_id")
    readiness = {
        "recommendation_id": _as_text(check_result.get("recommendation_id") or recommendation.get("id")),
        "vm_identity_id": vm_identity_id,
        "source_node_id": source_node_id,
        "target_node_id": target_node_id,
        "approved_actor": approved_actor,
        "final_precheck_passed": final_passed,
        "final_precheck_summary": final_precheck_summary(check_result),
        "lock_evidence": precheck_binding["operation_lock"],
        "approval_packet_creatable": creatable,
        "job_intent_creatable": creatable,
        "runnable": False,
        "proxmox_mutation_enabled": False,
        "allowed_actions": [],
        "side_effects": [],
        "warning_acknowledged": warning_acknowledged is True,
        "warning_codes": warning_codes,
        "warnings": warnings,
        "warnings_ack_required": bool(warnings),
        "blockers": [] if creatable else _approval_blockers(check_result, warnings, warning_acknowledged),
        "runnable_blockers": _runnable_blockers(check_result),
        "evidence_binding": {
            "recommendation_checksum": _checksum_payload(recommendation_binding),
            "final_precheck_checksum": _checksum_payload(precheck_binding),
        },
    }
    return readiness


def _target_id(recommendation: dict[str, Any]) -> str:
    source = _as_text(recommendation.get("source_node_id"), "unknown")
    target = _as_text(recommendation.get("target_node_id"), "unknown")
    vmid = _as_text(recommendation.get("vmid"), "unknown")
    return f"{source}->{target}:{vmid}"


def _packet_id() -> str:
    return f"drsap-{uuid.uuid4().hex}"


def _job_id(recommendation_id: str) -> str:
    return f"drs-mig-{_safe_segment(recommendation_id)}-{uuid.uuid4().hex[:12]}"


def _actor_required(actor: dict[str, Any] | None) -> dict[str, str]:
    actor = actor or {}
    trusted = {
        "user_id": _as_text(actor.get("user_id")),
        "username": _as_text(actor.get("username")),
        "role": _as_text(actor.get("role")),
    }
    if not (trusted["user_id"] and trusted["username"] and trusted["role"]):
        raise DrsApprovalBlockedError(
            code="DRS_APPROVAL_ACTOR_REQUIRED",
            message="trusted operator actor evidence is required for DRS approval",
            readiness={
                "approval_packet_creatable": False,
                "job_intent_creatable": False,
                "runnable": False,
                "proxmox_mutation_enabled": False,
                "allowed_actions": [],
                "side_effects": [],
                "blockers": ["approved_actor_required"],
            },
        )
    return trusted


def _row_dict(row: DrsApprovalPacketRecord | DrsMigrationJobRecord) -> dict[str, Any]:
    data = {
        key: value
        for key, value in row.__dict__.items()
        if not key.startswith("_")
    }
    for key, value in list(data.items()):
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    return data


def create_approval_packet_and_job_intent(
    check_result: dict[str, Any],
    *,
    payload: dict[str, Any] | None,
    actor: dict[str, Any] | None,
) -> dict[str, Any]:
    """Create local DRS approval packet and a non-runnable job intent."""
    trusted_actor = _actor_required(actor)
    warning_acknowledged = _warning_acknowledged_from_payload(payload)
    readiness = build_approval_readiness(
        check_result,
        warning_acknowledged=warning_acknowledged,
        approved_actor=trusted_actor,
    )
    if readiness["approval_packet_creatable"] is not True:
        raise DrsApprovalBlockedError(
            code="DRS_APPROVAL_GATE_BLOCKED",
            message="DRS approval packet cannot be created because final pre-check or warning acknowledgement gates are blocked",
            readiness=readiness,
        )

    recommendation = _recommendation(check_result)
    identity = _identity_evidence(check_result)
    packet_id = _packet_id()
    job_id = _job_id(readiness["recommendation_id"])
    cluster_id = _cluster_id(check_result)
    recommendation_binding = compact_recommendation_binding(check_result)
    precheck_binding = compact_final_precheck_binding(check_result)
    summary = final_precheck_summary(check_result)

    recommendation_artifact = write_json_artifact(
        run_dir=run_dir(job_id),
        job_id=job_id,
        artifact_type="drs_recommendation_evidence",
        filename="drs_recommendation_evidence.json",
        payload=recommendation_binding,
    )
    final_precheck_artifact = write_json_artifact(
        run_dir=run_dir(job_id),
        job_id=job_id,
        artifact_type="drs_final_precheck",
        filename="drs_final_precheck.json",
        payload=precheck_binding,
    )
    artifact_refs = {
        "recommendation_artifact": _artifact_dict(recommendation_artifact),
        "final_precheck_artifact": _artifact_dict(final_precheck_artifact),
    }
    approval_payload = {
        "approval_packet_id": packet_id,
        "job_id": job_id,
        "approval_scope": DRS_MIGRATION_JOB_TYPE,
        "recommendation_id": readiness["recommendation_id"],
        "cluster_id": cluster_id,
        "vm_identity_id": identity.get("vm_identity_id"),
        "vmid": _as_int(recommendation.get("vmid"), 0),
        "vm_name": _as_text(recommendation.get("vm_name")),
        "source_node_id": readiness["source_node_id"],
        "target_node_id": readiness["target_node_id"],
        "approved_actor": trusted_actor,
        "warning_acknowledged": readiness["warning_acknowledged"],
        "warning_codes": readiness["warning_codes"],
        "warnings": readiness["warnings"],
        "final_precheck_summary": summary,
        "lock_evidence": readiness["lock_evidence"],
        "evidence_binding": readiness["evidence_binding"],
        "artifacts": artifact_refs,
        "runnable": False,
        "proxmox_mutation_enabled": False,
        "side_effects": [],
        "created_at": _now_iso(),
    }
    approval_artifact = write_json_artifact(
        run_dir=run_dir(job_id),
        job_id=job_id,
        artifact_type="drs_approval_packet",
        filename="drs_approval_packet.json",
        payload=approval_payload,
    )
    approval_payload["artifacts"]["approval_artifact"] = _artifact_dict(approval_artifact)
    job_intent = {
        "job_id": job_id,
        "job_type": DRS_MIGRATION_JOB_TYPE,
        "status": "pending",
        "approval_packet_id": packet_id,
        "recommendation_id": readiness["recommendation_id"],
        "vm_identity_id": identity.get("vm_identity_id"),
        "source_node_id": readiness["source_node_id"],
        "target_node_id": readiness["target_node_id"],
        "approved_actor": trusted_actor,
        "final_precheck_summary": summary,
        "lock_evidence": readiness["lock_evidence"],
        "runnable": False,
        "proxmox_mutation_enabled": False,
        "side_effects": [],
        "runnable_blockers": readiness["runnable_blockers"],
    }
    job_intent_artifact = write_json_artifact(
        run_dir=run_dir(job_id),
        job_id=job_id,
        artifact_type="drs_job_intent",
        filename="drs_job_intent.json",
        payload=job_intent,
    )

    now = _now()
    with session_scope() as session:
        packet_row = DrsApprovalPacketRecord(
            approval_packet_id=packet_id,
            packet_status="approved",
            job_id=job_id,
            recommendation_id=readiness["recommendation_id"],
            cluster_id=cluster_id,
            vm_identity_id=_as_text(identity.get("vm_identity_id")),
            vmid=_as_int(recommendation.get("vmid"), 0),
            vm_name=_as_text(recommendation.get("vm_name")),
            source_node_id=readiness["source_node_id"],
            target_node_id=readiness["target_node_id"],
            actor_user_id=trusted_actor["user_id"],
            actor_username=trusted_actor["username"],
            actor_role=trusted_actor["role"],
            warning_acknowledged=readiness["warning_acknowledged"],
            warning_codes=readiness["warning_codes"],
            warnings=readiness["warnings"],
            recommendation_checksum=readiness["evidence_binding"]["recommendation_checksum"],
            final_precheck_checksum=readiness["evidence_binding"]["final_precheck_checksum"],
            approval_packet_checksum=approval_artifact.checksum,
            recommendation_artifact_id=recommendation_artifact.artifact_id,
            final_precheck_artifact_id=final_precheck_artifact.artifact_id,
            approval_artifact_id=approval_artifact.artifact_id,
            final_precheck_summary=summary,
            lock_evidence=readiness["lock_evidence"],
            created_at=now,
            updated_at=now,
        )
        job_row = DrsMigrationJobRecord(
            job_id=job_id,
            approval_packet_id=packet_id,
            recommendation_id=readiness["recommendation_id"],
            cluster_id=cluster_id,
            vm_identity_id=_as_text(identity.get("vm_identity_id")),
            vmid=_as_int(recommendation.get("vmid"), 0),
            source_node_id=readiness["source_node_id"],
            target_node_id=readiness["target_node_id"],
            status="pending",
            runnable=False,
            proxmox_mutation_enabled=False,
            side_effects=[],
            runnable_blockers=readiness["runnable_blockers"],
            final_precheck_summary=summary,
            lock_evidence=readiness["lock_evidence"],
            approved_actor=trusted_actor,
            job_intent_artifact_id=job_intent_artifact.artifact_id,
            created_at=now,
            updated_at=now,
        )
        session.add(packet_row)
        session.add(job_row)
        session.flush()
        packet_record = _row_dict(packet_row)
        job_record = _row_dict(job_row)

    job_run = record_job_run(
        job_id=job_id,
        job_type=DRS_MIGRATION_JOB_TYPE,
        status="pending",
        target_id=_target_id(recommendation),
        risk_level=_as_text(recommendation.get("risk_level"), "unknown"),
        stage="job_intent",
        step_status="pending",
        message="Local DRS migration intent recorded; live migration remains disabled.",
        artifacts=[
            _artifact_dict(recommendation_artifact),
            _artifact_dict(final_precheck_artifact),
            _artifact_dict(approval_artifact),
            _artifact_dict(job_intent_artifact),
        ],
        risks=[],
        details={
            "approval_packet_id": packet_id,
            "recommendation_id": readiness["recommendation_id"],
            "vm_identity_id": identity.get("vm_identity_id"),
            "source_node_id": readiness["source_node_id"],
            "target_node_id": readiness["target_node_id"],
            "final_precheck_summary": summary,
            "lock_evidence": readiness["lock_evidence"],
            "approved_actor": trusted_actor,
            "runnable": False,
            "proxmox_mutation_enabled": False,
            "side_effects": [],
            **actor_detail_fields(trusted_actor),
        },
    )

    return {
        "approval_packet": packet_record,
        "job_intent": job_record,
        "job_run": job_run,
        "approval_readiness": readiness,
        "artifacts": [
            _artifact_dict(recommendation_artifact),
            _artifact_dict(final_precheck_artifact),
            _artifact_dict(approval_artifact),
            _artifact_dict(job_intent_artifact),
        ],
        "read_only": False,
        "executable": False,
        "allowed_actions": [],
        "runnable": False,
        "proxmox_mutation_enabled": False,
        "side_effects": [],
    }
