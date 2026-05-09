"""Operational risk calculation helpers for the Proxmox operations console.

This module is intentionally pure/read-only: it receives inventory, monitoring,
snapshot, and task evidence and returns deterministic risk items. Proxmox API
calls stay in the service layer.
"""

from __future__ import annotations

import math
import re
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

SECONDS_PER_DAY = 86_400
RESTORE_DRILL_STALE_DAYS = 90.0
DEFAULT_RPO_RTO_PROFILE_ID = "default"
RPO_RTO_PROFILE_PRESETS: Dict[str, Dict[str, float]] = {
    "critical": {"rpo_hours": 24.0, "restore_drill_max_age_days": 30.0},
    "standard": {"rpo_hours": 168.0, "restore_drill_max_age_days": 90.0},
    "relaxed": {"rpo_hours": 720.0, "restore_drill_max_age_days": 180.0},
}
RPO_RTO_PROFILE_TAG_KEYS = {
    "backup-profile",
    "recovery-profile",
    "rpo-profile",
    "rpo-rto-profile",
}

DEFAULT_THRESHOLDS: Dict[str, float] = {
    "storage_warning_percent": 80.0,
    "storage_critical_percent": 90.0,
    "snapshot_warning_days": 14.0,
    "snapshot_critical_days": 30.0,
    "backup_warning_days": 7.0,
    "stopped_warning_days": 30.0,
    "stopped_critical_days": 90.0,
}

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2, "healthy": 3}

OWNER_TAXONOMY_TAG_KEYS = {
    "owner",
    "owned-by",
    "team",
    "app-owner",
    "service-owner",
}
ENVIRONMENT_TAXONOMY_TAG_KEYS = {"env", "environment", "stage"}
ENVIRONMENT_TAXONOMY_VALUES = {
    "prod",
    "production",
    "stage",
    "staging",
    "dev",
    "development",
    "test",
    "testing",
    "qa",
    "lab",
    "homelab",
    "infra",
    "ops",
    "sandbox",
}
TAG_TAXONOMY_SEPARATORS = (":", "=", "/")
COMPLIANCE_POLICY_ID = "default"
COMPLIANCE_POLICY_SOURCE = "default"
COMPLIANCE_PROD_PROFILE_RULE_ID = "prod-explicit-backup-profile"
COMPLIANCE_PROD_ENVIRONMENT_VALUES = {"prod", "production"}


def _safe_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_rpo_rto_profile_id(value: Any) -> str:
    profile_id = _normalize_taxonomy_token(value).replace("-", "_")
    return profile_id if profile_id in RPO_RTO_PROFILE_PRESETS else ""


def _find_rpo_rto_profile_tag(vm: Mapping[str, Any]) -> Dict[str, Any]:
    """Return explicit backup/RPO profile tag evidence for a VM.

    Prefer the first accepted profile so one stale/invalid candidate tag does not
    mask a later valid explicit profile. If no candidate is valid, retain the
    first invalid candidate for compliance evidence and operator guidance.
    """

    first_invalid_candidate: Dict[str, Any] = {}
    for tag in _split_tags(vm.get("tags")):
        key, value = _split_taxonomy_tag(tag)
        if key not in RPO_RTO_PROFILE_TAG_KEYS:
            continue
        profile_id = _normalize_rpo_rto_profile_id(value)
        candidate = {
            "tag": tag,
            "key": key,
            "value": value.strip(),
            "profile_id": profile_id,
            "valid": bool(profile_id),
        }
        if profile_id:
            return candidate
        if not first_invalid_candidate:
            first_invalid_candidate = candidate
    return first_invalid_candidate


def _vm_rpo_rto_profile_override_id(vm: Mapping[str, Any]) -> str:
    profile_tag = _find_rpo_rto_profile_tag(vm)
    return str(profile_tag.get("profile_id") or "")


def _resolve_rpo_rto_profile(
    vm: Mapping[str, Any],
    *,
    effective_thresholds: Mapping[str, float],
) -> Dict[str, Any]:
    """Return the read-only RPO/RTO profile for one VM.

    Set 2 starts with a backward-compatible default profile. Its RPO mirrors
    the existing backup readiness threshold so existing operators do not see a
    policy change until a VM-specific override is present. VM-specific overrides
    are read-only metadata tags such as ``rpo-profile:critical``.
    """

    profile_id = _vm_rpo_rto_profile_override_id(vm)
    if profile_id:
        preset = RPO_RTO_PROFILE_PRESETS[profile_id]
        return {
            "profile_id": profile_id,
            "source": "vm_override",
            "rpo_hours": preset["rpo_hours"],
            "restore_drill_max_age_days": preset["restore_drill_max_age_days"],
        }

    backup_warning_days = _safe_float(
        effective_thresholds.get("backup_warning_days"),
        DEFAULT_THRESHOLDS["backup_warning_days"],
    )
    return {
        "profile_id": DEFAULT_RPO_RTO_PROFILE_ID,
        "source": "default",
        "rpo_hours": round(backup_warning_days * 24.0, 3),
        "restore_drill_max_age_days": RESTORE_DRILL_STALE_DAYS,
    }


def _rpo_rto_profile_evidence(profile: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "rpo_rto_profile_id": profile.get("profile_id") or DEFAULT_RPO_RTO_PROFILE_ID,
        "rpo_rto_profile_source": profile.get("source") or "default",
        "rpo_hours": _safe_float(profile.get("rpo_hours"), DEFAULT_THRESHOLDS["backup_warning_days"] * 24.0),
        "restore_drill_max_age_days": _safe_float(profile.get("restore_drill_max_age_days"), RESTORE_DRILL_STALE_DAYS),
    }


def _now_epoch(now: Optional[Any] = None) -> float:
    if now is None:
        return time.time()
    if hasattr(now, "timestamp"):
        return float(now.timestamp())
    return _safe_float(now, time.time())


def _vm_key(vm: Mapping[str, Any]) -> str:
    return f"{vm.get('node')}/{vm.get('vmid')}"


def _split_tags(tags: Any) -> List[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        return [part.strip() for part in re.split(r"[;,\s]+", tags) if part.strip()]
    if isinstance(tags, Iterable):
        return [str(part).strip() for part in tags if str(part).strip()]
    return []


def _normalize_taxonomy_token(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    return normalized.strip("-")


def _split_taxonomy_tag(tag: str) -> tuple[str, str]:
    raw = str(tag or "").strip()
    for separator in TAG_TAXONOMY_SEPARATORS:
        if separator in raw:
            key, value = raw.split(separator, 1)
            return _normalize_taxonomy_token(key), value.strip()
    return "", raw


def _environment_signal_policy_value(signal: Any) -> str:
    key, value = _split_taxonomy_tag(str(signal or ""))
    return _normalize_taxonomy_token(value if key else signal)


def _description_has_owner_signal(vm: Mapping[str, Any]) -> bool:
    markers = ["owner:", "owner=", "owned by", "team:", "team="]
    text_fields = [str(vm.get("description") or ""), str(vm.get("notes") or "")]
    return any(marker in field.lower() for field in text_fields for marker in markers)


def _is_environment_taxonomy_value(value: Any) -> bool:
    return _normalize_taxonomy_token(value) in ENVIRONMENT_TAXONOMY_VALUES


def _evaluate_governance_metadata(vm: Mapping[str, Any]) -> Dict[str, Any]:
    tags = _split_tags(vm.get("tags"))
    owner_signal: Optional[str] = None
    environment_signal: Optional[str] = None
    incidental_tags: List[str] = []

    for tag in tags:
        key, value = _split_taxonomy_tag(tag)
        if key in OWNER_TAXONOMY_TAG_KEYS and value.strip():
            owner_signal = owner_signal or tag
            continue
        if key in ENVIRONMENT_TAXONOMY_TAG_KEYS and _is_environment_taxonomy_value(value):
            environment_signal = environment_signal or tag
            continue
        if not key and _is_environment_taxonomy_value(value):
            environment_signal = environment_signal or tag
            continue
        incidental_tags.append(tag)

    if owner_signal is None and _description_has_owner_signal(vm):
        owner_signal = "description"

    missing_metadata: List[str] = []
    if owner_signal is None:
        missing_metadata.append("owner_or_team")
    if environment_signal is None:
        missing_metadata.append("environment")

    return {
        "complete": not missing_metadata,
        "missing_metadata": missing_metadata,
        "owner_signal": owner_signal,
        "environment_signal": environment_signal,
        "tags": tags,
        "incidental_tags": incidental_tags,
        "description_present": bool(vm.get("description") or vm.get("notes")),
        "accepted_owner_keys": sorted(OWNER_TAXONOMY_TAG_KEYS),
        "accepted_environment_keys": sorted(ENVIRONMENT_TAXONOMY_TAG_KEYS),
        "accepted_environment_values": sorted(ENVIRONMENT_TAXONOMY_VALUES),
    }


def _governance_missing_detail(missing_metadata: Sequence[str], incidental_tags: Sequence[str]) -> str:
    labels = {
        "owner_or_team": "owner/team",
        "environment": "environment",
    }
    missing = ", ".join(labels.get(item, item) for item in missing_metadata)
    detail = f"Missing required governance metadata: {missing}."
    if incidental_tags:
        detail += " Incidental/free-form tags do not satisfy the taxonomy: " + ", ".join(incidental_tags) + "."
    return detail


def _evaluate_compliance_policy(
    vm: Mapping[str, Any],
    governance_metadata: Mapping[str, Any],
    rpo_rto_profile: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Evaluate default read-only compliance policy findings for one VM."""

    environment_value = _environment_signal_policy_value(governance_metadata.get("environment_signal"))
    profile_tag = _find_rpo_rto_profile_tag(vm)
    findings: List[Dict[str, Any]] = []

    if environment_value in COMPLIANCE_PROD_ENVIRONMENT_VALUES and not profile_tag.get("valid"):
        candidate_tag = profile_tag.get("tag") or "missing"
        if profile_tag:
            detail = (
                "Production VM has no accepted explicit backup/RPO profile metadata. "
                f"Candidate tag {candidate_tag!r} is not one of the accepted profile values."
            )
        else:
            detail = "Production VM has no explicit backup/RPO profile metadata."
        findings.append(
            {
                "rule_id": COMPLIANCE_PROD_PROFILE_RULE_ID,
                "title": "Production VM is missing explicit backup/RPO policy profile",
                "detail": detail,
                "recommendation": (
                    "Add an accepted backup/RPO profile tag such as "
                    "backup-profile:critical, rpo-profile:standard, or rpo-rto-profile:relaxed. "
                    "This is metadata guidance only; Gjallar will not mutate Proxmox automatically."
                ),
                "evidence": {
                    "policy_id": COMPLIANCE_POLICY_ID,
                    "policy_source": COMPLIANCE_POLICY_SOURCE,
                    "rule_id": COMPLIANCE_PROD_PROFILE_RULE_ID,
                    "environment_signal": governance_metadata.get("environment_signal") or "missing",
                    "environment_value": environment_value,
                    "required_environment_values": sorted(COMPLIANCE_PROD_ENVIRONMENT_VALUES),
                    "candidate_backup_profile_tag": candidate_tag,
                    "accepted_backup_profile_keys": sorted(RPO_RTO_PROFILE_TAG_KEYS),
                    "accepted_backup_profile_values": sorted(RPO_RTO_PROFILE_PRESETS),
                    "rpo_rto_profile_id": rpo_rto_profile.get("profile_id") or DEFAULT_RPO_RTO_PROFILE_ID,
                    "rpo_rto_profile_source": rpo_rto_profile.get("source") or "default",
                },
            }
        )
    return findings


SAFE_ACTION_SUGGESTION_TEMPLATES: Dict[str, List[Dict[str, str]]] = {
    "node_status": [
        {
            "action_id": "review-node-health",
            "label": "Review node health",
            "description": "Open the node operations view and confirm quorum, networking, and API reachability before planning any change.",
            "link": "/risks?category=node_status",
        }
    ],
    "storage_capacity": [
        {
            "action_id": "review-storage-headroom",
            "label": "Review storage headroom",
            "description": "Inspect storage usage, retention, and migration options; any cleanup or move still needs explicit approval.",
            "link": "/risks?category=storage_capacity",
        }
    ],
    "guest_agent": [
        {
            "action_id": "review-guest-agent-signal",
            "label": "Review guest agent signal",
            "description": "Check guest agent installation and reachability evidence before deciding on a manual fix.",
            "link": "/risks?category=guest_agent",
        }
    ],
    "guest_ssh_evidence": [
        {
            "action_id": "review-ssh-collector-evidence",
            "label": "Review optional SSH evidence",
            "description": "Inspect the disabled-by-default read-only collector configuration and error evidence without running guest commands.",
            "link": "/risks?category=guest_ssh_evidence",
        }
    ],
    "governance": [
        {
            "action_id": "review-governance-metadata",
            "label": "Review governance metadata",
            "description": "Identify the missing owner/team or environment metadata and plan a documented metadata update.",
            "link": "/risks?category=governance",
        }
    ],
    "compliance": [
        {
            "action_id": "review-compliance-policy",
            "label": "Review compliance policy",
            "description": "Check which local policy rule was missed and plan a documented metadata update; no Proxmox mutation is executed automatically.",
            "link": "/risks?category=compliance",
        }
    ],
    "snapshot_age": [
        {
            "action_id": "review-snapshot-retention",
            "label": "Review snapshot retention",
            "description": "Confirm snapshot age and owner intent; any consolidation or cleanup remains a separate approved action.",
            "link": "/risks?category=snapshot_age",
        }
    ],
    "backup_coverage": [
        {
            "action_id": "review-backup-coverage",
            "label": "Review backup coverage",
            "description": "Check backup policy coverage and decide whether the VM should be added to a scheduled backup job.",
            "link": "/risks?category=backup_coverage",
        }
    ],
    "backup_recency": [
        {
            "action_id": "review-backup-recency",
            "label": "Review backup recency",
            "description": "Confirm the latest backup evidence and decide whether a fresh backup should be requested.",
            "link": "/risks?category=backup_recency",
        }
    ],
    "rpo_violation": [
        {
            "action_id": "review-rpo-profile",
            "label": "Review RPO profile",
            "description": "Compare the VM profile with backup evidence before requesting backup policy changes.",
            "link": "/risks?category=rpo_violation",
        }
    ],
    "restore_readiness": [
        {
            "action_id": "review-restore-readiness",
            "label": "Review restore readiness",
            "description": "Inspect PBS restore point evidence and decide whether backup or drill work should be approved.",
            "link": "/risks?category=restore_readiness",
        }
    ],
    "pbs_datastore_capacity": [
        {
            "action_id": "review-pbs-datastore-capacity",
            "label": "Review PBS datastore capacity",
            "description": "Check PBS datastore capacity evidence and retention policy before planning storage changes.",
            "link": "/risks?category=pbs_datastore_capacity",
        }
    ],
    "pbs_datastore_health": [
        {
            "action_id": "review-pbs-datastore-health",
            "label": "Review PBS datastore health",
            "description": "Inspect read-only PBS health evidence and storage backend status before any operator action.",
            "link": "/risks?category=pbs_datastore_health",
        }
    ],
    "restore_drill": [
        {
            "action_id": "review-restore-drill-plan",
            "label": "Review restore drill plan",
            "description": "Plan or verify a manual restore drill; recording or executing drill work needs separate approval.",
            "link": "/risks?category=restore_drill",
        }
    ],
    "long_stopped": [
        {
            "action_id": "review-long-stopped-vm",
            "label": "Review stopped VM intent",
            "description": "Confirm retention intent and ownership before proposing any resource reclamation work.",
            "link": "/risks?category=long_stopped",
        }
    ],
}


def build_safe_suggested_actions(
    category: str,
    *,
    scope: Optional[str] = None,
    node: Optional[str] = None,
    vmid: Optional[int] = None,
    evidence: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Return proposal-only next-check suggestions for one risk item.

    Suggestions are metadata only. They are intentionally approval-required and
    do not execute remediation, guest commands, or infrastructure changes.
    """

    normalized_category = str(category or "unknown").strip() or "unknown"
    templates = SAFE_ACTION_SUGGESTION_TEMPLATES.get(
        normalized_category,
        [
            {
                "action_id": "review-operational-risk",
                "label": "Review operational risk",
                "description": "Inspect the evidence and choose a separately approved follow-up if needed.",
                "link": "/risks",
            }
        ],
    )
    target: Dict[str, Any] = {"scope": scope or "unknown"}
    if node:
        target["node"] = str(node)
    if vmid:
        target["vmid"] = int(vmid)
    if isinstance(evidence, Mapping) and evidence.get("datastore"):
        target["datastore"] = str(evidence["datastore"])

    actions: List[Dict[str, Any]] = []
    for template in templates:
        actions.append(
            {
                "action_id": template["action_id"],
                "label": template["label"],
                "description": template["description"],
                "link": template["link"],
                "requires_approval": True,
                "execution_mode": "proposal_only",
                "mutation_allowed": False,
                "target": dict(target),
            }
        )
    return actions


def _risk_item(
    *,
    item_id: str,
    severity: str,
    category: str,
    scope: str,
    title: str,
    detail: str,
    recommendation: str,
    node: Optional[str] = None,
    vmid: Optional[int] = None,
    vm_name: Optional[str] = None,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized_evidence = evidence or {}
    return {
        "id": item_id,
        "severity": severity,
        "category": category,
        "scope": scope,
        "node": node,
        "vmid": vmid,
        "vm_name": vm_name,
        "title": title,
        "detail": detail,
        "recommendation": recommendation,
        "suggested_actions": build_safe_suggested_actions(
            category,
            scope=scope,
            node=node,
            vmid=vmid,
            evidence=normalized_evidence,
        ),
        "evidence": normalized_evidence,
    }


def _is_successful_backup_task(task: Mapping[str, Any]) -> bool:
    text = " ".join(
        str(task.get(field, ""))
        for field in ["type", "upid", "worker_type", "id", "user", "status", "exitstatus"]
    ).lower()
    if "vzdump" not in text and "backup" not in text:
        return False

    exit_status = str(task.get("exitstatus") or task.get("status") or "").strip().upper()
    return exit_status in {"OK", "SUCCESS", "SUCCESSFUL"}


def _task_epoch(task: Mapping[str, Any]) -> float:
    for field in ["endtime", "starttime"]:
        value = _safe_float(task.get(field), 0.0)
        if value > 0:
            return value
    return 0.0


def _has_recent_successful_backup(tasks: Sequence[Mapping[str, Any]], *, now_epoch: float, warning_days: float) -> bool:
    min_epoch = now_epoch - (warning_days * SECONDS_PER_DAY)
    for task in tasks or []:
        if not isinstance(task, Mapping):
            continue
        if not _is_successful_backup_task(task):
            continue
        task_time = _task_epoch(task)
        if task_time >= min_epoch:
            return True
    return False


def _normalize_backup_not_backed_up_by_vmid(
    evidence: Optional[Mapping[Any, Mapping[str, Any]]],
) -> Dict[int, Dict[str, Any]]:
    normalized: Dict[int, Dict[str, Any]] = {}
    if evidence is None:
        return normalized
    for key, record in evidence.items():
        if isinstance(record, Mapping):
            vmid = _safe_int(record.get("vmid", key), 0)
            item = dict(record)
        else:
            vmid = _safe_int(key, 0)
            item = {"vmid": vmid}
        if vmid <= 0:
            continue
        item["vmid"] = vmid
        normalized[vmid] = item
    return normalized



def _normalize_pbs_restore_evidence_by_vmid(
    evidence: Optional[Mapping[Any, Mapping[str, Any]]],
    *,
    now_epoch: float,
) -> Dict[int, Dict[str, Any]]:
    normalized: Dict[int, Dict[str, Any]] = {}
    if evidence is None:
        return normalized
    for key, record in evidence.items():
        if not isinstance(record, Mapping):
            continue
        vmid = _safe_int(record.get("vmid", key), 0)
        if vmid <= 0:
            continue
        latest_backup_time = _safe_float(record.get("latest_backup_time"), 0.0)
        if latest_backup_time > 0:
            latest_backup_age_days = _safe_float(
                record.get("latest_backup_age_days"),
                max(0.0, (now_epoch - latest_backup_time) / SECONDS_PER_DAY),
            )
        else:
            latest_backup_age_days = None
        datastores: List[str] = []
        for datastore in record.get("datastores") or []:
            datastore_name = str(datastore or "").strip()
            if datastore_name and datastore_name not in datastores:
                datastores.append(datastore_name)
        normalized[vmid] = {
            "source": str(record.get("source") or "pbs"),
            "vmid": vmid,
            "snapshot_count": max(0, _safe_int(record.get("snapshot_count"), 0)),
            "latest_backup_time": latest_backup_time or None,
            "latest_backup_age_days": round(latest_backup_age_days, 3) if latest_backup_age_days is not None else None,
            "latest_snapshot": record.get("latest_snapshot"),
            "datastores": sorted(datastores),
        }
    return normalized




def _normalize_restore_drill_evidence_by_vm(
    evidence: Optional[Mapping[Any, Mapping[str, Any]]],
    *,
    now_epoch: float,
) -> Dict[str, Dict[str, Any]]:
    normalized: Dict[str, Dict[str, Any]] = {}
    if evidence is None:
        return normalized
    for key, record in evidence.items():
        if not isinstance(record, Mapping):
            continue
        node = str(record.get("node") or "").strip()
        vmid = _safe_int(record.get("vmid"), 0)
        if (not node or vmid <= 0) and isinstance(key, str) and "/" in key:
            key_node, key_vmid = key.rsplit("/", 1)
            node = node or key_node.strip()
            vmid = vmid or _safe_int(key_vmid, 0)
        if not node or vmid <= 0:
            continue
        drilled_at = _safe_float(record.get("drilled_at"), 0.0)
        outcome = str(record.get("outcome") or "unknown").strip().lower()
        if drilled_at > now_epoch:
            outcome = "future_invalid"
            latest_drill_age_days = None
        elif drilled_at > 0:
            latest_drill_age_days = _safe_float(
                record.get("latest_drill_age_days"),
                max(0.0, (now_epoch - drilled_at) / SECONDS_PER_DAY),
            )
        else:
            latest_drill_age_days = None
        normalized[f"{node}/{vmid}"] = {
            "source": str(record.get("source") or "gjallar_db"),
            "node": node,
            "vmid": vmid,
            "outcome": outcome,
            "drilled_at": drilled_at or None,
            "recorded_at": record.get("recorded_at"),
            "recorded_by": record.get("recorded_by"),
            "datastore": record.get("datastore"),
            "snapshot": record.get("snapshot"),
            "latest_drill_age_days": round(latest_drill_age_days, 3) if latest_drill_age_days is not None else None,
        }
    return normalized


def _normalize_ssh_guest_evidence_by_vm(
    evidence: Optional[Mapping[Any, Mapping[str, Any]]],
) -> Dict[str, Dict[str, Any]]:
    normalized: Dict[str, Dict[str, Any]] = {}
    if evidence is None:
        return normalized
    for key, record in evidence.items():
        if not isinstance(record, Mapping):
            continue
        node = str(record.get("node") or "").strip()
        vmid = _safe_int(record.get("vmid"), 0)
        if (not node or vmid <= 0) and isinstance(key, str) and "/" in key:
            key_node, key_vmid = key.rsplit("/", 1)
            node = node or key_node.strip()
            vmid = vmid or _safe_int(key_vmid, 0)
        if not node or vmid <= 0:
            continue
        command_ids = [str(command_id) for command_id in (record.get("command_ids") or [])]
        blocked_commands = [str(command_id) for command_id in (record.get("blocked_commands") or [])]
        normalized[f"{node}/{vmid}"] = {
            "source": str(record.get("source") or "optional_readonly_ssh"),
            "node": node,
            "vmid": vmid,
            "collected": bool(record.get("collected")),
            "status": str(record.get("status") or "unknown").strip().lower(),
            "reason": str(record.get("reason") or "unknown").strip().lower(),
            "command_ids": command_ids,
            "blocked_commands": blocked_commands,
            "error": str(record.get("error") or ""),
            "collected_at": record.get("collected_at"),
            "command_results": record.get("command_results") if isinstance(record.get("command_results"), Mapping) else {},
        }
    return normalized


def _normalize_pbs_datastore_evidence_by_name(
    evidence: Optional[Mapping[Any, Mapping[str, Any]]],
) -> Dict[str, Dict[str, Any]]:
    normalized: Dict[str, Dict[str, Any]] = {}
    if evidence is None:
        return normalized
    for key, record in evidence.items():
        if not isinstance(record, Mapping):
            continue
        datastore = str(record.get("datastore") or key or "").strip()
        if not datastore:
            continue
        total = _safe_float(record.get("total"), 0.0)
        used = _safe_float(record.get("used"), 0.0)
        avail = _safe_float(record.get("avail"), 0.0)
        usage_percent = _safe_float(record.get("usage_percent"), -1.0)
        if usage_percent < 0 and total > 0:
            usage_percent = (used / total) * 100
        health = str(record.get("health") or record.get("status") or "unknown").strip().lower()
        normalized[datastore] = {
            "source": str(record.get("source") or "pbs"),
            "datastore": datastore,
            "total": total,
            "used": used,
            "avail": avail,
            "usage_percent": round(usage_percent, 3) if usage_percent >= 0 else None,
            "health": health or "unknown",
            "error": record.get("error"),
        }
    return normalized


def _snapshot_age_days(snapshot: Mapping[str, Any], *, now_epoch: float) -> Optional[float]:
    snaptime = _safe_float(snapshot.get("snaptime") or snapshot.get("time"), 0.0)
    if snaptime <= 0:
        return None
    return max(0.0, (now_epoch - snaptime) / SECONDS_PER_DAY)



def _active_risk_override(override: Mapping[str, Any], *, now_epoch: float) -> Optional[Dict[str, Any]]:
    status = str(override.get("status") or "").strip().lower()
    if status not in {"acknowledged", "suppressed"}:
        return None
    expires_at = override.get("expires_at")
    if expires_at is not None and _safe_float(expires_at, now_epoch + 1) <= now_epoch:
        return None
    return {
        "risk_id": str(override.get("risk_id") or ""),
        "status": status,
        "reason": str(override.get("reason") or ""),
        "updated_at": override.get("updated_at"),
        "updated_by": override.get("updated_by") or "local",
        "expires_at": expires_at,
    }


def _dashboard_status_from_counts(counts: Mapping[str, int]) -> str:
    if counts.get("critical", 0) > 0:
        return "critical"
    if counts.get("warning", 0) > 0:
        return "warning"
    if counts.get("info", 0) > 0:
        return "info"
    return "healthy"


def _recompute_summary_for_visible_risks(
    original_summary: Mapping[str, Any],
    risk_items: Sequence[Mapping[str, Any]],
    *,
    acknowledged_count: int,
    suppressed_count: int,
) -> Dict[str, Any]:
    counts = {"critical": 0, "warning": 0, "info": 0}
    category_counts: Dict[str, int] = {}
    affected_nodes = set()
    affected_vms = set()

    for risk in risk_items:
        severity = str(risk.get("severity") or "info")
        counts[severity] = counts.get(severity, 0) + 1
        category = str(risk.get("category") or "unknown")
        category_counts[category] = category_counts.get(category, 0) + 1
        if risk.get("node"):
            affected_nodes.add(str(risk["node"]))
        if risk.get("scope") == "vm" and risk.get("node") and risk.get("vmid"):
            affected_vms.add(f"{risk['node']}/{risk['vmid']}")

    summary = dict(original_summary or {})
    summary.update(
        {
            "total_risks": len(risk_items),
            "critical": counts.get("critical", 0),
            "warning": counts.get("warning", 0),
            "info": counts.get("info", 0),
            "affected_nodes": len(affected_nodes),
            "affected_vms": len(affected_vms),
            "categories": dict(sorted(category_counts.items())),
            "acknowledged": acknowledged_count,
            "suppressed": suppressed_count,
        }
    )
    return summary


def apply_risk_overrides(
    dashboard: Mapping[str, Any],
    overrides_by_risk_id: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    now: Optional[Any] = None,
    include_suppressed: bool = False,
) -> Dict[str, Any]:
    """Apply local acknowledge/suppress state to a risk dashboard response.

    Suppressed risks are hidden from the visible ``risk_items`` list by default.
    Acknowledged risks remain visible with override metadata attached. This is a
    response-shaping step only; raw risk evidence is not deleted.
    """

    now_epoch = _now_epoch(now)
    active_overrides: Dict[str, Dict[str, Any]] = {}
    for risk_id, override in dict(overrides_by_risk_id or {}).items():
        if not isinstance(override, Mapping):
            continue
        normalized = _active_risk_override({**dict(override), "risk_id": override.get("risk_id") or risk_id}, now_epoch=now_epoch)
        if normalized is not None:
            active_overrides[str(risk_id)] = normalized

    visible_items: List[Dict[str, Any]] = []
    suppressed_items: List[Dict[str, Any]] = []
    acknowledged_count = 0
    suppressed_count = 0

    for item in list(dashboard.get("risk_items") or []):
        if not isinstance(item, Mapping):
            continue
        risk_item = dict(item)
        risk_id = str(risk_item.get("id") or "")
        override = active_overrides.get(risk_id)
        if override is None:
            visible_items.append(risk_item)
            continue
        risk_item["override"] = override
        if override["status"] == "suppressed":
            suppressed_count += 1
            if include_suppressed:
                suppressed_items.append(risk_item)
            continue
        if override["status"] == "acknowledged":
            acknowledged_count += 1
        visible_items.append(risk_item)

    result = dict(dashboard)
    result["risk_items"] = visible_items
    if include_suppressed:
        result["suppressed_risk_items"] = suppressed_items
    else:
        result.pop("suppressed_risk_items", None)
    result["summary"] = _recompute_summary_for_visible_risks(
        dict(dashboard.get("summary") or {}),
        visible_items,
        acknowledged_count=acknowledged_count,
        suppressed_count=suppressed_count,
    )
    result["status"] = _dashboard_status_from_counts(result["summary"])
    return result

def build_operational_risk_dashboard(
    vms: Sequence[Mapping[str, Any]],
    nodes_monitoring: Sequence[Mapping[str, Any]],
    *,
    snapshots_by_vm: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
    backup_tasks_by_vm: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
    backup_not_backed_up_by_vmid: Optional[Mapping[Any, Mapping[str, Any]]] = None,
    backup_jobs: Optional[Sequence[Mapping[str, Any]]] = None,
    pbs_restore_evidence_by_vmid: Optional[Mapping[Any, Mapping[str, Any]]] = None,
    pbs_datastore_evidence_by_name: Optional[Mapping[Any, Mapping[str, Any]]] = None,
    restore_drill_evidence_by_vm: Optional[Mapping[Any, Mapping[str, Any]]] = None,
    ssh_guest_evidence_by_vm: Optional[Mapping[Any, Mapping[str, Any]]] = None,
    vm_state_history: Optional[Mapping[str, Mapping[str, Any]]] = None,
    now: Optional[Any] = None,
    thresholds: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    """Build a read-only operational risk dashboard from collected evidence."""

    effective_thresholds = {**DEFAULT_THRESHOLDS, **dict(thresholds or {})}
    now_epoch = _now_epoch(now)
    vm_items = [dict(vm) for vm in (vms or [])]
    node_items = [dict(node) for node in (nodes_monitoring or [])]
    snapshots_by_vm = snapshots_by_vm or {}
    vm_state_history_collected = vm_state_history is not None
    vm_state_history = vm_state_history or {}
    backup_schedule_evidence_enabled = backup_not_backed_up_by_vmid is not None
    backup_not_backed_up = _normalize_backup_not_backed_up_by_vmid(backup_not_backed_up_by_vmid)
    backup_jobs_count = len([job for job in (backup_jobs or []) if isinstance(job, Mapping)])
    pbs_restore_evidence_collected = pbs_restore_evidence_by_vmid is not None
    pbs_restore_evidence = _normalize_pbs_restore_evidence_by_vmid(
        pbs_restore_evidence_by_vmid,
        now_epoch=now_epoch,
    )
    pbs_datastores = sorted(
        {
            str(datastore)
            for record in pbs_restore_evidence.values()
            for datastore in record.get("datastores", [])
            if str(datastore or "").strip()
        }
    )
    pbs_datastore_health_collected = pbs_datastore_evidence_by_name is not None
    pbs_datastore_evidence = _normalize_pbs_datastore_evidence_by_name(pbs_datastore_evidence_by_name)
    restore_drill_evidence_collected = restore_drill_evidence_by_vm is not None
    restore_drill_evidence = _normalize_restore_drill_evidence_by_vm(
        restore_drill_evidence_by_vm,
        now_epoch=now_epoch,
    )
    ssh_guest_evidence_collected = ssh_guest_evidence_by_vm is not None
    ssh_guest_evidence = _normalize_ssh_guest_evidence_by_vm(ssh_guest_evidence_by_vm)

    risks: List[Dict[str, Any]] = []
    rpo_rto_profile_sources: Dict[str, int] = {}

    # Node and storage capacity risks.
    for node in node_items:
        node_name = node.get("node") or node.get("name") or "unknown-node"
        status = str(node.get("status") or "unknown").strip().lower()
        if status != "online":
            risks.append(
                _risk_item(
                    item_id=f"node:{node_name}:status",
                    severity="critical",
                    category="node_status",
                    scope="node",
                    node=str(node_name),
                    title=f"{node_name} node status is {status or 'unknown'}",
                    detail="Node is not reporting an online status.",
                    recommendation="Check Proxmox node health, quorum, network reachability, and agent/API connectivity.",
                    evidence={"status": status},
                )
            )

        for storage in node.get("storages") or []:
            if not isinstance(storage, Mapping):
                continue
            usage = _safe_float(storage.get("usage_percent"), 0.0)
            if usage < effective_thresholds["storage_warning_percent"]:
                continue
            severity = "critical" if usage >= effective_thresholds["storage_critical_percent"] else "warning"
            storage_name = storage.get("name") or storage.get("storage") or "unknown-storage"
            risks.append(
                _risk_item(
                    item_id=f"storage:{node_name}:{storage_name}:capacity",
                    severity=severity,
                    category="storage_capacity",
                    scope="storage",
                    node=str(node_name),
                    title=f"{node_name}/{storage_name} storage usage is {usage:.1f}%",
                    detail="Storage usage is above the operational risk threshold.",
                    recommendation="Free space, migrate disks, expand storage, or review backup/snapshot retention.",
                    evidence={
                        "usage_percent": round(usage, 2),
                        "available_gb": storage.get("available_gb"),
                        "total_gb": storage.get("total_gb"),
                        "type": storage.get("type"),
                    },
                )
            )


    # PBS datastore capacity/health risks. PBS evidence is optional/read-only; None means uncollected.
    for datastore, record in sorted(pbs_datastore_evidence.items()):
        usage = record.get("usage_percent")
        if usage is not None and usage >= effective_thresholds["storage_warning_percent"]:
            severity = "critical" if usage >= effective_thresholds["storage_critical_percent"] else "warning"
            risks.append(
                _risk_item(
                    item_id=f"pbs-datastore:{datastore}:capacity",
                    severity=severity,
                    category="pbs_datastore_capacity",
                    scope="pbs_datastore",
                    title=f"PBS datastore {datastore} usage is {usage:.1f}%",
                    detail="PBS datastore usage is above the operational risk threshold.",
                    recommendation="Free space, expand PBS storage, or review retention policy before backups lose headroom.",
                    evidence={
                        "source": record.get("source", "pbs"),
                        "datastore": datastore,
                        "usage_percent": usage,
                        "total": record.get("total"),
                        "used": record.get("used"),
                        "avail": record.get("avail"),
                        "health": record.get("health"),
                    },
                )
            )

        health = str(record.get("health") or "unknown").strip().lower()
        if health not in {"ok", "healthy", "available", "online", "good", "active"}:
            risks.append(
                _risk_item(
                    item_id=f"pbs-datastore:{datastore}:health",
                    severity="critical" if health in {"error", "failed", "failure", "critical"} else "warning",
                    category="pbs_datastore_health",
                    scope="pbs_datastore",
                    title=f"PBS datastore {datastore} health is {health or 'unknown'}",
                    detail="PBS datastore health evidence is not reporting a healthy state.",
                    recommendation="Review PBS datastore verify/status output and storage backend health. Do not run mutation tasks without explicit approval.",
                    evidence={
                        "source": record.get("source", "pbs"),
                        "datastore": datastore,
                        "health": health or "unknown",
                        "error": record.get("error"),
                    },
                )
            )

    # VM-specific risks.
    backup_evidence_enabled = backup_tasks_by_vm is not None
    backup_tasks_by_vm = backup_tasks_by_vm or {}
    for vm in vm_items:
        node = str(vm.get("node") or "unknown-node")
        vmid = _safe_int(vm.get("vmid"), 0)
        vm_name = str(vm.get("name") or vm.get("server_name") or f"vm-{vmid}")
        key = _vm_key(vm)
        status = str(vm.get("status") or "unknown").strip().lower()
        rpo_rto_profile = _resolve_rpo_rto_profile(vm, effective_thresholds=effective_thresholds)
        rpo_rto_profile_sources[str(rpo_rto_profile.get("source") or "default")] = (
            rpo_rto_profile_sources.get(str(rpo_rto_profile.get("source") or "default"), 0) + 1
        )
        profile_evidence = _rpo_rto_profile_evidence(rpo_rto_profile)

        if status == "running" and "guest_agent_ipv4_addresses" in vm and not vm.get("guest_agent_ipv4_addresses"):
            risks.append(
                _risk_item(
                    item_id=f"vm:{key}:guest-agent",
                    severity="warning",
                    category="guest_agent",
                    scope="vm",
                    node=node,
                    vmid=vmid,
                    vm_name=vm_name,
                    title=f"{vm_name} has no guest agent IP signal",
                    detail="The VM is running but qemu guest agent network evidence is empty or unreachable.",
                    recommendation="Verify qemu-guest-agent is installed, enabled, and responsive inside the VM.",
                    evidence={
                        "status": status,
                        "configured_ipv4_addresses": vm.get("configured_ipv4_addresses", []),
                        "guest_agent_ipv4_addresses": vm.get("guest_agent_ipv4_addresses", []),
                    },
                )
            )

        if ssh_guest_evidence_collected:
            ssh_record = ssh_guest_evidence.get(key)
            if ssh_record and not ssh_record.get("collected"):
                risks.append(
                    _risk_item(
                        item_id=f"vm:{key}:ssh-guest-evidence",
                        severity="info",
                        category="guest_ssh_evidence",
                        scope="vm",
                        node=node,
                        vmid=vmid,
                        vm_name=vm_name,
                        title=f"{vm_name} optional SSH guest evidence was not collected",
                        detail="The optional read-only SSH collector was configured for this VM but did not return collected evidence.",
                        recommendation="Review the SSH collector target/allowlist/configuration. Do not run guest mutation or remediation without explicit approval.",
                        evidence={
                            "source": ssh_record.get("source", "optional_readonly_ssh"),
                            "status": ssh_record.get("status", "unknown"),
                            "reason": ssh_record.get("reason", "unknown"),
                            "command_ids": ssh_record.get("command_ids", []),
                            "blocked_commands": ssh_record.get("blocked_commands", []),
                            "error": ssh_record.get("error", ""),
                        },
                    )
                )

        governance_metadata = _evaluate_governance_metadata(vm)
        if not governance_metadata["complete"]:
            risks.append(
                _risk_item(
                    item_id=f"vm:{key}:owner-tag",
                    severity="info",
                    category="governance",
                    scope="vm",
                    node=node,
                    vmid=vmid,
                    vm_name=vm_name,
                    title=f"{vm_name} is missing owner/environment taxonomy metadata",
                    detail=_governance_missing_detail(
                        governance_metadata["missing_metadata"],
                        governance_metadata["incidental_tags"],
                    ),
                    recommendation=(
                        "Add accepted owner/team and environment metadata, for example "
                        "owner:yoon + env:prod or team:infra + env:lab."
                    ),
                    evidence={
                        "missing_metadata": governance_metadata["missing_metadata"],
                        "tags": governance_metadata["tags"],
                        "incidental_tags": governance_metadata["incidental_tags"],
                        "owner_signal": governance_metadata["owner_signal"] or "missing",
                        "environment_signal": governance_metadata["environment_signal"] or "missing",
                        "description_present": governance_metadata["description_present"],
                        "accepted_owner_keys": governance_metadata["accepted_owner_keys"],
                        "accepted_environment_keys": governance_metadata["accepted_environment_keys"],
                        "accepted_environment_values": governance_metadata["accepted_environment_values"],
                    },
                )
            )

        for finding in _evaluate_compliance_policy(vm, governance_metadata, rpo_rto_profile):
            risks.append(
                _risk_item(
                    item_id=f"vm:{key}:compliance:{finding['rule_id']}",
                    severity="info",
                    category="compliance",
                    scope="vm",
                    node=node,
                    vmid=vmid,
                    vm_name=vm_name,
                    title=f"{vm_name} {finding['title']}",
                    detail=finding["detail"],
                    recommendation=finding["recommendation"],
                    evidence=finding["evidence"],
                )
            )


        if vm_state_history_collected and status == "stopped":
            state_record = vm_state_history.get(key)
            if isinstance(state_record, Mapping):
                stopped_days = _safe_float(state_record.get("stopped_days"), 0.0)
                if stopped_days >= effective_thresholds["stopped_warning_days"]:
                    severity = (
                        "critical"
                        if stopped_days >= effective_thresholds["stopped_critical_days"]
                        else "warning"
                    )
                    risks.append(
                        _risk_item(
                            item_id=f"vm:{key}:long-stopped",
                            severity=severity,
                            category="long_stopped",
                            scope="vm",
                            node=node,
                            vmid=vmid,
                            vm_name=vm_name,
                            title=f"{vm_name} has been stopped for {stopped_days:.0f} days",
                            detail="Gjallar has observed this VM in a stopped state beyond the configured threshold.",
                            recommendation="Confirm whether the VM is intentionally retained; reclaim resources or document the exception if it is still needed.",
                            evidence={
                                "source": state_record.get("source", "gjallar_db"),
                                "stopped_days": stopped_days,
                                "stopped_since": state_record.get("stopped_since"),
                                "status_since": state_record.get("status_since"),
                                "first_seen_at": state_record.get("first_seen_at"),
                                "last_seen_at": state_record.get("last_seen_at"),
                                "warning_days": effective_thresholds["stopped_warning_days"],
                                "critical_days": effective_thresholds["stopped_critical_days"],
                            },
                        )
                    )

        for snapshot in snapshots_by_vm.get(key, []) or []:
            if not isinstance(snapshot, Mapping):
                continue
            snap_name = str(snapshot.get("name") or "").strip()
            if not snap_name or snap_name.lower() == "current":
                continue
            age_days = _snapshot_age_days(snapshot, now_epoch=now_epoch)
            if age_days is None or age_days < effective_thresholds["snapshot_warning_days"]:
                continue
            severity = "critical" if age_days >= effective_thresholds["snapshot_critical_days"] else "warning"
            risks.append(
                _risk_item(
                    item_id=f"vm:{key}:snapshot:{snap_name}",
                    severity=severity,
                    category="snapshot_age",
                    scope="vm",
                    node=node,
                    vmid=vmid,
                    vm_name=vm_name,
                    title=f"{vm_name} snapshot {snap_name} is {age_days:.0f} days old",
                    detail="Old snapshots increase storage pressure and make rollback intent unclear.",
                    recommendation="Review whether the snapshot is still needed; consolidate or delete it manually if safe.",
                    evidence={"snapshot": snap_name, "age_days": round(age_days, 1), "snaptime": snapshot.get("snaptime")},
                )
            )

        skip_backup_recency = False
        if backup_schedule_evidence_enabled:
            uncovered_backup_record = backup_not_backed_up.get(vmid)
            if uncovered_backup_record:
                skip_backup_recency = True
                risks.append(
                    _risk_item(
                        item_id=f"vm:{key}:backup-coverage",
                        severity="warning",
                        category="backup_coverage",
                        scope="vm",
                        node=node,
                        vmid=vmid,
                        vm_name=vm_name,
                        title=f"{vm_name} is not covered by a Proxmox backup job",
                        detail="Proxmox reports this VM in the read-only not-backed-up list for configured backup jobs.",
                        recommendation="Add the VM to a scheduled backup job or document why it is intentionally excluded.",
                        evidence={
                            "source": "/cluster/backup-info/not-backed-up",
                            "reported_name": uncovered_backup_record.get("name"),
                            "reported_type": uncovered_backup_record.get("type"),
                            "backup_jobs_count": backup_jobs_count,
                        },
                    )
                )

        if pbs_restore_evidence_collected:
            skip_backup_recency = True
            pbs_record = pbs_restore_evidence.get(vmid)
            warning_days = profile_evidence["rpo_hours"] / 24.0
            if not pbs_record or _safe_int(pbs_record.get("snapshot_count"), 0) <= 0:
                risks.append(
                    _risk_item(
                        item_id=f"vm:{key}:restore-readiness",
                        severity="warning",
                        category="restore_readiness",
                        scope="vm",
                        node=node,
                        vmid=vmid,
                        vm_name=vm_name,
                        title=f"{vm_name} has no PBS restore point evidence",
                        detail="PBS direct API evidence was collected, but no VM restore point was found for this VM.",
                        recommendation="Confirm that the VM is backed up to PBS or document why restore readiness is intentionally unavailable.",
                        evidence={
                            **profile_evidence,
                            "source": "pbs",
                            "reason": "no_pbs_restore_point",
                            "warning_days": warning_days,
                        },
                    )
                )
            else:
                latest_age_days = _safe_float(pbs_record.get("latest_backup_age_days"), float("inf"))
                if latest_age_days > warning_days:
                    risks.append(
                        _risk_item(
                            item_id=f"vm:{key}:restore-readiness",
                            severity="warning",
                            category="restore_readiness",
                            scope="vm",
                            node=node,
                            vmid=vmid,
                            vm_name=vm_name,
                            title=f"{vm_name} PBS restore point is {latest_age_days:.0f} days old",
                            detail=f"Latest PBS restore point is older than the configured {warning_days:.0f}-day backup/restore readiness threshold.",
                            recommendation="Run or schedule a fresh backup and consider a restore drill for important workloads.",
                            evidence={
                                **profile_evidence,
                                "source": pbs_record.get("source", "pbs"),
                                "reason": "stale_pbs_restore_point",
                                "latest_backup_time": pbs_record.get("latest_backup_time"),
                                "latest_backup_age_days": latest_age_days,
                                "latest_snapshot": pbs_record.get("latest_snapshot"),
                                "snapshot_count": pbs_record.get("snapshot_count"),
                                "datastores": pbs_record.get("datastores", []),
                                "warning_days": warning_days,
                            },
                        )
                    )


        if restore_drill_evidence_collected:
            drill_record = restore_drill_evidence.get(key)
            stale_after_days = profile_evidence["restore_drill_max_age_days"]
            if not drill_record:
                risks.append(
                    _risk_item(
                        item_id=f"vm:{key}:restore-drill",
                        severity="warning",
                        category="restore_drill",
                        scope="vm",
                        node=node,
                        vmid=vmid,
                        vm_name=vm_name,
                        title=f"{vm_name} has no restore drill record",
                        detail="Gjallar local evidence has no recorded restore drill for this VM.",
                        recommendation="Record the latest manual/external restore drill result in Gjallar after validation. Do not run restore actions without explicit approval.",
                        evidence={
                            **profile_evidence,
                            "source": "gjallar_db",
                            "reason": "no_restore_drill_record",
                            "stale_after_days": stale_after_days,
                        },
                    )
                )
            else:
                outcome = str(drill_record.get("outcome") or "unknown").strip().lower()
                latest_drill_age_days = _safe_float(drill_record.get("latest_drill_age_days"), float("inf"))
                if outcome != "passed":
                    if outcome == "failed":
                        reason = "last_restore_drill_failed"
                    elif outcome == "future_invalid":
                        reason = "future_restore_drill_record"
                    else:
                        reason = "last_restore_drill_incomplete"
                    risks.append(
                        _risk_item(
                            item_id=f"vm:{key}:restore-drill",
                            severity="warning",
                            category="restore_drill",
                            scope="vm",
                            node=node,
                            vmid=vmid,
                            vm_name=vm_name,
                            title=f"{vm_name} latest restore drill outcome is {outcome or 'unknown'}",
                            detail="The latest Gjallar restore drill record did not pass.",
                            recommendation="Investigate the failed/partial/blocked drill and record a successful drill after manual validation.",
                            evidence={
                                **profile_evidence,
                                "source": drill_record.get("source", "gjallar_db"),
                                "reason": reason,
                                "outcome": outcome or "unknown",
                                "drilled_at": drill_record.get("drilled_at"),
                                "latest_drill_age_days": latest_drill_age_days if math.isfinite(latest_drill_age_days) else None,
                                "stale_after_days": stale_after_days,
                            },
                        )
                    )
                elif latest_drill_age_days > stale_after_days:
                    risks.append(
                        _risk_item(
                            item_id=f"vm:{key}:restore-drill",
                            severity="warning",
                            category="restore_drill",
                            scope="vm",
                            node=node,
                            vmid=vmid,
                            vm_name=vm_name,
                            title=f"{vm_name} restore drill is {latest_drill_age_days:.0f} days old",
                            detail=f"Latest passed restore drill is older than the profile {stale_after_days:.0f}-day restore drill evidence threshold.",
                            recommendation="Run a manual/external restore drill when approved and record the outcome in Gjallar local evidence.",
                            evidence={
                                **profile_evidence,
                                "source": drill_record.get("source", "gjallar_db"),
                                "reason": "stale_restore_drill",
                                "outcome": outcome,
                                "drilled_at": drill_record.get("drilled_at"),
                                "latest_drill_age_days": latest_drill_age_days,
                                "stale_after_days": stale_after_days,
                            },
                        )
                    )

        backup_recency_warning_days = profile_evidence["rpo_hours"] / 24.0
        if backup_evidence_enabled and not skip_backup_recency and not _has_recent_successful_backup(
            backup_tasks_by_vm.get(key, []) or [],
            now_epoch=now_epoch,
            warning_days=backup_recency_warning_days,
        ):
            risks.append(
                _risk_item(
                    item_id=f"vm:{key}:backup-recency",
                    severity="warning",
                    category="backup_recency",
                    scope="vm",
                    node=node,
                    vmid=vmid,
                    vm_name=vm_name,
                    title=f"{vm_name} has no recent successful backup evidence",
                    detail=f"No successful backup/vzdump task was found within the profile {backup_recency_warning_days:.0f}-day RPO window.",
                    recommendation="Confirm backup job coverage and run or schedule a backup if this VM is important.",
                    evidence={**profile_evidence, "lookback_days": backup_recency_warning_days},
                )
            )

    risks.sort(
        key=lambda item: (
            SEVERITY_ORDER.get(str(item.get("severity")), 99),
            str(item.get("category") or ""),
            str(item.get("node") or ""),
            _safe_int(item.get("vmid"), 10**9),
            str(item.get("id") or ""),
        )
    )

    counts = {"critical": 0, "warning": 0, "info": 0}
    category_counts: Dict[str, int] = {}
    affected_nodes = set()
    affected_vms = set()
    for risk in risks:
        severity = str(risk.get("severity") or "info")
        counts[severity] = counts.get(severity, 0) + 1
        category = str(risk.get("category") or "unknown")
        category_counts[category] = category_counts.get(category, 0) + 1
        if risk.get("node"):
            affected_nodes.add(str(risk["node"]))
        if risk.get("scope") == "vm" and risk.get("node") and risk.get("vmid"):
            affected_vms.add(f"{risk['node']}/{risk['vmid']}")

    overall_status = "healthy"
    if counts.get("critical", 0) > 0:
        overall_status = "critical"
    elif counts.get("warning", 0) > 0:
        overall_status = "warning"
    elif counts.get("info", 0) > 0:
        overall_status = "info"

    return {
        "status": overall_status,
        "generated_at": int(now_epoch),
        "summary": {
            "total_risks": len(risks),
            "critical": counts.get("critical", 0),
            "warning": counts.get("warning", 0),
            "info": counts.get("info", 0),
            "affected_nodes": len(affected_nodes),
            "affected_vms": len(affected_vms),
            "total_nodes": len(node_items),
            "total_vms": len(vm_items),
            "categories": dict(sorted(category_counts.items())),
        },
        "risk_items": risks,
        "thresholds": effective_thresholds,
        "evidence": {
            "backup_task_history_collected": backup_evidence_enabled,
            "backup_schedule_collected": backup_schedule_evidence_enabled,
            "backup_jobs_count": backup_jobs_count if backup_schedule_evidence_enabled else None,
            "pbs_restore_readiness_collected": pbs_restore_evidence_collected,
            "pbs_restore_readiness_vms": len(pbs_restore_evidence) if pbs_restore_evidence_collected else None,
            "pbs_datastores_count": len(pbs_datastores) if pbs_restore_evidence_collected else None,
            "pbs_datastore_health_collected": pbs_datastore_health_collected,
            "pbs_datastore_health_datastores": len(pbs_datastore_evidence) if pbs_datastore_health_collected else None,
            "rpo_rto_profile_collected": True,
            "rpo_rto_profile_vms": len(vm_items),
            "rpo_rto_profile_sources": dict(sorted(rpo_rto_profile_sources.items())),
            "compliance_policy_collected": True,
            "compliance_policy_id": COMPLIANCE_POLICY_ID,
            "compliance_policy_source": COMPLIANCE_POLICY_SOURCE,
            "compliance_policy_rules": [COMPLIANCE_PROD_PROFILE_RULE_ID],
            "compliance_policy_vms": len(vm_items),
            "restore_drill_records_collected": restore_drill_evidence_collected,
            "restore_drill_vms": len(restore_drill_evidence) if restore_drill_evidence_collected else None,
            "ssh_guest_collected": ssh_guest_evidence_collected,
            "ssh_guest_vms": len(ssh_guest_evidence) if ssh_guest_evidence_collected else None,
            "ssh_guest_failed_vms": (
                sum(1 for record in ssh_guest_evidence.values() if not record.get("collected"))
                if ssh_guest_evidence_collected
                else None
            ),
            "vm_state_history_collected": vm_state_history_collected,
            "vm_state_history_vms": len(vm_state_history) if vm_state_history_collected else None,
            "backup_uncovered_vms": len(backup_not_backed_up) if backup_schedule_evidence_enabled else None,
        },
    }
