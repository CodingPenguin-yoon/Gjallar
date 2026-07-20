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
        "operation_type": lock.get("operation_type"),
        "status": lock.get("status"),
        "scope_type": lock.get("scope_type"),
        "scope_key": lock.get("scope_key"),
        "cluster_id": lock.get("cluster_id"),
        "vm_identity_id": lock.get("vm_identity_id"),
        "vmid": lock.get("vmid"),
        "source_node_id": lock.get("source_node_id"),
        "target_node_id": lock.get("target_node_id"),
        "owner_id": lock.get("owner_id"),
        "reason": lock.get("reason"),
        "created_at": lock.get("created_at"),
        "updated_at": lock.get("updated_at"),
        "released_at": lock.get("released_at"),
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
    summary = {
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
    if isinstance(check_result.get("criteria_details"), list):
        summary["criteria_details"] = list(check_result["criteria_details"])
    if isinstance(check_result.get("advisory_signals"), list):
        summary["advisory_signals"] = list(check_result["advisory_signals"])
    if isinstance(check_result.get("technical_gate_status"), dict):
        summary["technical_gate_status"] = dict(check_result["technical_gate_status"])
    return summary


def _field(source: Any, key: str, default: Any = None) -> Any:
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _compact_actor(actor: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(actor, dict):
        return {}
    return {
        "user_id": actor.get("user_id"),
        "username": actor.get("username"),
        "role": actor.get("role"),
    }


def _compact_check_statuses(checks: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(checks, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for key, item in sorted(checks.items()):
        if not isinstance(item, dict):
            continue
        result[key] = {
            "status": item.get("status"),
            "blocker": item.get("blocker"),
        }
    return result


def _compact_live_precheck(live_precheck: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(live_precheck, dict):
        return {}
    return {
        "status": live_precheck.get("status"),
        "blockers": list(live_precheck.get("blockers") or []),
        "check_statuses": _compact_check_statuses(live_precheck.get("checks")),
    }


def _compact_operation_lock(lock_evidence: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(lock_evidence, dict):
        return {}
    locks = [_compact_lock(lock) for lock in _as_list(lock_evidence.get("locks")) if isinstance(lock, dict)]
    matching_locks = [
        _compact_lock(lock)
        for lock in _as_list(lock_evidence.get("matching_locks"))
        if isinstance(lock, dict)
    ]
    lock_ids = list(lock_evidence.get("lock_ids") or [])
    matching_lock_ids = list(lock_evidence.get("matching_lock_ids") or [])
    if not lock_ids:
        lock_ids = [lock["operation_lock_id"] for lock in locks if lock.get("operation_lock_id")]
    if not matching_lock_ids:
        matching_lock_ids = [lock["operation_lock_id"] for lock in matching_locks if lock.get("operation_lock_id")]
    return {
        "operation_type": lock_evidence.get("operation_type") or lock_evidence.get("operation"),
        "cluster_id": lock_evidence.get("cluster_id"),
        "acquired": lock_evidence.get("acquired"),
        "blocking": lock_evidence.get("blocking"),
        "blockers": list(lock_evidence.get("blockers") or []),
        "checked_scopes": [
            {"scope_type": scope.get("scope_type"), "scope_key": scope.get("scope_key")}
            for scope in _as_list(lock_evidence.get("checked_scopes"))
            if isinstance(scope, dict)
        ],
        "lock_ids": lock_ids,
        "matching_lock_ids": matching_lock_ids,
        "matching_statuses": list(lock_evidence.get("matching_statuses") or []),
        "locks": locks,
        "matching_locks": matching_locks,
    }


def _compact_task_log(log_excerpt: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in _as_list(log_excerpt):
        if isinstance(item, dict):
            result.append({key: item.get(key) for key in ("n", "t", "type", "status") if key in item})
        else:
            text = _as_text(item)
            if text:
                result.append({"t": text})
    return result[:20]


def _compact_task(job: Any, task: dict[str, Any] | None = None) -> dict[str, Any]:
    task = task if isinstance(task, dict) else {}
    task_status = task.get("status") if isinstance(task.get("status"), dict) else {}
    task_metadata = _field(job, "task_metadata", {})
    task_metadata = task_metadata if isinstance(task_metadata, dict) else {}
    metadata_status = task_metadata.get("status") if isinstance(task_metadata.get("status"), dict) else {}
    status = _field(job, "task_status") or task_status.get("status") or metadata_status.get("status")
    return {
        "upid": _field(job, "proxmox_upid") or task.get("upid"),
        "node": _field(job, "proxmox_task_node") or task.get("node"),
        "result": _field(job, "task_result") or task.get("result"),
        "status": status,
        "exitstatus": _field(job, "task_exitstatus") or task_status.get("exitstatus"),
        "poll_count": task_metadata.get("poll_count") or len(_as_list(task.get("polls"))),
        "log_excerpt": _compact_task_log(_field(job, "task_log_excerpt") or task.get("log_excerpt") or task.get("log")),
    }


def _compact_expected_observed(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        key: value.get(key)
        for key in (
            "cluster_id",
            "vm_identity_id",
            "target_node_id",
            "target_node_endpoint",
            "node_id",
            "vmid",
            "vm_name",
            "name",
            "power_state",
            "exists_on_target",
            "stable_fingerprint",
        )
        if key in value
    }


def _compact_post_check(post_check: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(post_check, dict):
        return {}
    expected = _compact_expected_observed(post_check.get("expected"))
    observed = _compact_expected_observed(post_check.get("observed"))
    expected_fingerprint = expected.get("stable_fingerprint")
    observed_fingerprint = observed.get("stable_fingerprint")
    return {
        "status": post_check.get("status"),
        "checked_at": post_check.get("checked_at"),
        "source": post_check.get("source"),
        "read_only": post_check.get("read_only") is True,
        "blockers": list(post_check.get("blockers") or []),
        "expected": expected,
        "observed": observed,
        "fingerprint": {
            "expected": expected_fingerprint,
            "observed": observed_fingerprint,
            "matches": bool(expected_fingerprint and observed_fingerprint and expected_fingerprint == observed_fingerprint),
        },
        "reconciliation_required": post_check.get("reconciliation_required") is True,
        "reconciliation_reason": post_check.get("reconciliation_reason"),
        "check_statuses": _compact_check_statuses(post_check.get("checks")),
    }


def _compact_reconciliation_event(event: dict[str, Any]) -> dict[str, Any]:
    evidence = event.get("evidence") if isinstance(event.get("evidence"), dict) else {}
    return {
        "event_id": event.get("event_id"),
        "event_type": event.get("event_type"),
        "status": event.get("status"),
        "reason": event.get("reason"),
        "created_at": event.get("created_at"),
        "evidence_summary": {
            key: evidence.get(key)
            for key in (
                "source",
                "upid",
                "task_result",
                "reconciliation_reason",
                "post_check_status",
                "post_check_reason",
            )
            if key in evidence
        },
    }


def build_drs_run_evidence(
    *,
    job: Any,
    packet: Any | None = None,
    approved_actor: dict[str, Any] | None = None,
    executed_actor: dict[str, Any] | None = None,
    final_precheck_summary: dict[str, Any] | None = None,
    live_precheck: dict[str, Any] | None = None,
    operation_lock: dict[str, Any] | None = None,
    task: dict[str, Any] | None = None,
    post_check: dict[str, Any] | None = None,
    blockers: list[str] | None = None,
    acknowledgement_field: str | None = None,
    acknowledgement_value: bool | None = None,
    reconciliation_events: list[dict[str, Any]] | None = None,
    resolved_reconciliation_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build compact read-only DRS job evidence for job_runs.details."""
    packet_actor = {
        "user_id": _field(packet, "actor_user_id"),
        "username": _field(packet, "actor_username"),
        "role": _field(packet, "actor_role"),
    }
    approved = _compact_actor(approved_actor) or _compact_actor(_field(job, "approved_actor")) or _compact_actor(packet_actor)
    executed = _compact_actor(executed_actor)
    final_summary = dict(final_precheck_summary or _field(job, "final_precheck_summary", {}) or {})
    execution_evidence = _field(job, "execution_evidence", {})
    execution_evidence = execution_evidence if isinstance(execution_evidence, dict) else {}
    if not live_precheck:
        live_precheck = execution_evidence.get("live_precheck") if isinstance(execution_evidence.get("live_precheck"), dict) else None
    if not operation_lock:
        operation_lock = _field(job, "lock_evidence", None) or execution_evidence.get("operation_lock")
    if not post_check:
        post_check = _field(job, "post_check_evidence", None) or execution_evidence.get("post_check")
    if not task:
        task = execution_evidence.get("task") if isinstance(execution_evidence.get("task"), dict) else {}
    side_effects = list(_field(job, "side_effects", []) or [])
    mutation_outcome_unknown = "proxmox_migrate_invocation_outcome_unknown" in side_effects
    known_mutation_evidence = _field(job, "proxmox_mutation_enabled") is True or any(
        effect in {"proxmox_migrate_invoked", "proxmox_upid_stored"}
        for effect in side_effects
    )
    historical_mutation = known_mutation_evidence or (bool(side_effects) and not mutation_outcome_unknown)
    acknowledgement = None
    if acknowledgement_field:
        acknowledgement = {"field": acknowledgement_field, "value": acknowledgement_value is True}
    reconciliation_reason = _field(job, "reconciliation_reason")
    if not reconciliation_reason and isinstance(post_check, dict):
        reconciliation_reason = post_check.get("reconciliation_reason")
    return {
        "read_only": True,
        "allowed_actions": [],
        "current_mutation_controls": [],
        "runnable": _field(job, "runnable") is True,
        "status": _field(job, "status"),
        "approval_packet": {
            "id": _field(packet, "approval_packet_id") or _field(job, "approval_packet_id"),
            "status": _field(packet, "packet_status"),
            "warning_acknowledged": _field(packet, "warning_acknowledged"),
            "warning_codes": list(_field(packet, "warning_codes", []) or []),
        },
        "recommendation_id": _field(job, "recommendation_id") or _field(packet, "recommendation_id"),
        "vm": {
            "identity_id": _field(job, "vm_identity_id") or _field(packet, "vm_identity_id"),
            "vmid": _field(job, "vmid") or _field(packet, "vmid"),
        },
        "route": {
            "source_node_id": _field(job, "source_node_id") or _field(packet, "source_node_id"),
            "target_node_id": _field(job, "target_node_id") or _field(packet, "target_node_id"),
        },
        "actors": {
            "approved": approved,
            "executed": executed,
        },
        "execution_acknowledgement": acknowledgement,
        "blockers": list(blockers or _field(job, "runnable_blockers", []) or []),
        "final_precheck_summary": final_summary,
        "live_precheck": _compact_live_precheck(live_precheck),
        "operation_lock": _compact_operation_lock(operation_lock),
        "task": _compact_task(job, task),
        "post_check": _compact_post_check(post_check),
        "reconciliation": {
            "required": _as_text(_field(job, "status")) == "needs_reconciliation"
            or bool(_field(job, "reconciliation_reason"))
            or (isinstance(post_check, dict) and post_check.get("reconciliation_required") is True),
            "reason": reconciliation_reason,
            "events": [
                _compact_reconciliation_event(event)
                for event in _as_list(reconciliation_events)
                if isinstance(event, dict)
            ],
            "resolved_events": [
                _compact_reconciliation_event(event)
                for event in _as_list(resolved_reconciliation_events)
                if isinstance(event, dict)
            ],
        },
        "historical_execution": {
            "proxmox_mutation_recorded": historical_mutation,
            "proxmox_mutation_may_have_run_previously": mutation_outcome_unknown and not known_mutation_evidence,
            "side_effects": side_effects,
        },
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
    return [
        f"{name}_not_collected"
        for name in PROXMOX_NOT_COLLECTED_CHECKS
        if statuses.get(name, {}).get("status") in {"not_collected", "not_implemented"}
    ]


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
    matching_locks = [
        lock
        for lock in precheck_binding["operation_lock"].get("matching_locks", [])
        if isinstance(lock, dict)
    ]
    reconciliation_locks = [
        lock
        for lock in matching_locks
        if _as_text(lock.get("status")) == "reconciliation_required"
    ]
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
        "reconciliation": {
            "required": bool(reconciliation_locks),
            "matching_lock_ids": [
                lock["operation_lock_id"]
                for lock in reconciliation_locks
                if lock.get("operation_lock_id")
            ],
            "reasons": [
                _as_text(lock.get("reason"), "operation_lock_reconciliation_required")
                for lock in reconciliation_locks
            ],
        },
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

    drs_evidence = build_drs_run_evidence(
        job=job_record,
        packet=packet_record,
        approved_actor=trusted_actor,
        final_precheck_summary=summary,
        operation_lock=readiness["lock_evidence"],
        blockers=readiness["runnable_blockers"],
    )
    job_run = record_job_run(
        job_id=job_id,
        job_type=DRS_MIGRATION_JOB_TYPE,
        status="pending",
        target_id=_target_id(recommendation),
        risk_level=_as_text(recommendation.get("risk_level"), "unknown"),
        stage="job_intent",
        step_status="pending",
        message="Local DRS approval packet/job intent recorded; approval packet creation does not start migration; use the dedicated execute route after fresh gates.",
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
            "drs_evidence": drs_evidence,
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
