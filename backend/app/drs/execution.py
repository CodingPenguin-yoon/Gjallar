"""Approval-gated DRS live migration execution."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from app.auth.roles import actor_detail_fields, actor_evidence, role_at_least
from app.db.models import DrsApprovalPacketRecord, DrsMigrationJobRecord, DrsReconciliationEventRecord
from app.db.session import session_scope
from app.drs.advisor import build_drs_check_result
from app.drs.approval import build_drs_run_evidence, final_precheck_summary
from app.drs.identity import fingerprint_components_for_vm, stable_fingerprint_for_components
from app.drs.operation_locks import acquire_drs_operation_locks, mark_locks_reconciliation_required, release_drs_operation_locks
from app.jobs.artifacts import get_artifact_record, read_artifact_text, write_json_artifact
from app.jobs.runs import record_job_run, run_dir
from app.proxmox.drs_migration import DrsProxmoxMigrationError, get_default_drs_proxmox_migration_client

DRS_MIGRATION_JOB_TYPE = "drs_migration"
DRS_LIVE_MIGRATION_ACK_FIELD = "drs_live_migration_acknowledged"
DRS_RECONCILIATION_ACK_FIELD = "drs_reconciliation_acknowledged"
LIVE_SUPERSEDED_ADVISOR_CHECKS = {
    "proxmox_active_task",
    "proxmox_ha_state",
    "proxmox_cluster_quorum",
    "proxmox_conflicts",
}
BAD_EVIDENCE_STATUSES = {
    "failed",
    "unknown",
    "stale",
    "missing",
    "conflict",
    "conflicting",
    "ambiguous",
    "not_collected",
    "not_implemented",
    "unavailable",
}
_DISK_CONFIG_PREFIX = re.compile(r"^(?:scsi|virtio|sata|ide)\d+$")
_MAC_IN_NET_CONFIG = re.compile(r"(?:^|[,;\s])(?:virtio|e1000|rtl8139|vmxnet3|model)[:=]([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})")
_COMPACT_TASK_KEYS = ("upid", "id", "node", "type", "user", "status", "pid", "starttime", "endtime")


class DrsMigrationExecutionError(Exception):
    """Raised when DRS migration execution gates block before a safe mutation result exists."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int = 409,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = dict(detail or {})

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            **self.detail,
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


def _row_dict(row: DrsApprovalPacketRecord | DrsMigrationJobRecord) -> dict[str, Any]:
    data = {key: value for key, value in row.__dict__.items() if not key.startswith("_")}
    for key, value in list(data.items()):
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    return data


def _artifact_checksum(artifact_id: str) -> str:
    artifact = get_artifact_record(artifact_id)
    return _as_text(artifact.checksum if artifact else "")


def _read_json_artifact_payload(artifact_id: str) -> dict[str, Any]:
    if not _as_text(artifact_id):
        return {}
    try:
        payload = json.loads(read_artifact_text(artifact_id))
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _target_id(job: DrsMigrationJobRecord | dict[str, Any]) -> str:
    source = _as_text(job.source_node_id if hasattr(job, "source_node_id") else job.get("source_node_id"), "unknown")
    target = _as_text(job.target_node_id if hasattr(job, "target_node_id") else job.get("target_node_id"), "unknown")
    vmid = _as_text(job.vmid if hasattr(job, "vmid") else job.get("vmid"), "unknown")
    return f"{source}->{target}:{vmid}"


def _job_reference(job: DrsMigrationJobRecord | dict[str, Any], packet: DrsApprovalPacketRecord | dict[str, Any]) -> dict[str, Any]:
    return {
        "recommendation_id": _as_text(job.recommendation_id if hasattr(job, "recommendation_id") else job.get("recommendation_id")),
        "vmid": _as_int(job.vmid if hasattr(job, "vmid") else job.get("vmid")),
        "vm_name": _as_text(packet.vm_name if hasattr(packet, "vm_name") else packet.get("vm_name")),
        "source_node_id": _as_text(job.source_node_id if hasattr(job, "source_node_id") else job.get("source_node_id")),
        "target_node_id": _as_text(job.target_node_id if hasattr(job, "target_node_id") else job.get("target_node_id")),
    }


def _trusted_operator(actor: Any) -> dict[str, str]:
    trusted = actor_evidence(actor)
    try:
        allowed = bool(trusted and role_at_least(trusted.get("role", ""), "operator"))
    except ValueError:
        allowed = False
    if not allowed:
        raise DrsMigrationExecutionError(
            code="DRS_EXECUTION_OPERATOR_REQUIRED",
            message="trusted operator actor evidence is required for DRS migration execution",
            status_code=403,
            detail={"side_effects": [], "proxmox_mutation_enabled": False},
        )
    return trusted


def require_drs_live_migration_ack(job_id: str, payload: dict[str, Any] | None) -> None:
    """Validate the execute request's only honored payload field before DRS work."""
    request_payload = payload if isinstance(payload, dict) else {}
    if request_payload.get(DRS_LIVE_MIGRATION_ACK_FIELD) is not True:
        raise DrsMigrationExecutionError(
            code="DRS_EXECUTION_ACK_REQUIRED",
            message=f"{DRS_LIVE_MIGRATION_ACK_FIELD}=true is required before DRS live migration execution",
            status_code=409,
            detail={
                "job_id": job_id,
                "required_acknowledgement": DRS_LIVE_MIGRATION_ACK_FIELD,
                "proxmox_mutation_enabled": False,
                "side_effects": [],
            },
        )


def require_drs_reconciliation_ack(job_id: str, payload: dict[str, Any] | None) -> None:
    """Validate the local reconciliation request before DB/client work."""
    request_payload = payload if isinstance(payload, dict) else {}
    if request_payload.get(DRS_RECONCILIATION_ACK_FIELD) is not True:
        raise DrsMigrationExecutionError(
            code="DRS_RECONCILIATION_ACK_REQUIRED",
            message=f"{DRS_RECONCILIATION_ACK_FIELD}=true is required before local DRS reconciliation",
            status_code=409,
            detail={
                "job_id": job_id,
                "required_acknowledgement": DRS_RECONCILIATION_ACK_FIELD,
                "proxmox_mutation_enabled": False,
                "corrective_mutation_enabled": False,
                "side_effects": [],
            },
        )


def _load_job_and_packet(job_id: str) -> tuple[DrsMigrationJobRecord, DrsApprovalPacketRecord]:
    with session_scope() as session:
        job = session.get(DrsMigrationJobRecord, job_id)
        if job is None:
            raise DrsMigrationExecutionError(
                code="DRS_JOB_NOT_FOUND",
                message="DRS migration job was not found",
                status_code=404,
                detail={"job_id": job_id, "side_effects": [], "proxmox_mutation_enabled": False},
            )
        packet = session.get(DrsApprovalPacketRecord, job.approval_packet_id)
        if packet is None:
            raise DrsMigrationExecutionError(
                code="DRS_APPROVAL_PACKET_NOT_FOUND",
                message="DRS approval packet for this migration job was not found",
                detail={"job_id": job_id, "approval_packet_id": job.approval_packet_id, "side_effects": []},
            )
        return job, packet


def _approval_binding_blockers(job: DrsMigrationJobRecord, packet: DrsApprovalPacketRecord) -> list[str]:
    blockers: list[str] = []
    if packet.packet_status != "approved":
        blockers.append("approval_packet_not_approved")
    if job.status == "cancelled":
        blockers.append("job_cancelled")
    elif job.status != "pending":
        blockers.append("job_not_pending")
    if job.proxmox_upid:
        blockers.append("job_already_has_upid")

    bindings = {
        "job_id": (packet.job_id, job.job_id),
        "approval_packet_id": (job.approval_packet_id, packet.approval_packet_id),
        "recommendation_id": (packet.recommendation_id, job.recommendation_id),
        "cluster_id": (packet.cluster_id, job.cluster_id),
        "vm_identity_id": (packet.vm_identity_id, job.vm_identity_id),
        "vmid": (packet.vmid, job.vmid),
        "source_node_id": (packet.source_node_id, job.source_node_id),
        "target_node_id": (packet.target_node_id, job.target_node_id),
    }
    for key, (packet_value, job_value) in bindings.items():
        if packet_value != job_value:
            blockers.append(f"{key}_binding_mismatch")

    checksum_bindings = {
        "recommendation_checksum": (packet.recommendation_checksum, packet.recommendation_artifact_id),
        "final_precheck_checksum": (packet.final_precheck_checksum, packet.final_precheck_artifact_id),
        "approval_packet_checksum": (packet.approval_packet_checksum, packet.approval_artifact_id),
    }
    for key, (stored_checksum, artifact_id) in checksum_bindings.items():
        if not _as_text(stored_checksum):
            blockers.append(f"{key}_missing")
            continue
        artifact_checksum = _artifact_checksum(_as_text(artifact_id))
        if not artifact_checksum:
            blockers.append(f"{key}_artifact_missing")
        elif artifact_checksum != stored_checksum:
            blockers.append(f"{key}_artifact_mismatch")
    return _dedupe(blockers)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = _as_text(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _identity_locator(identity: dict[str, Any]) -> dict[str, Any]:
    components = identity.get("fingerprint_components")
    if not isinstance(components, dict):
        return {}
    locator = components.get("locator")
    return dict(locator) if isinstance(locator, dict) else {}


def _fresh_check_blockers(
    final_check: dict[str, Any] | None,
    *,
    job: DrsMigrationJobRecord,
) -> list[str]:
    if final_check is None:
        return ["fresh_final_precheck_missing"]
    blockers: list[str] = []
    if final_check.get("would_be_executable") is not True:
        blockers.extend(list(final_check.get("blockers") or []))
        blockers.append("drs_final_precheck_failed")

    identity = final_check.get("identity_evidence") if isinstance(final_check.get("identity_evidence"), dict) else {}
    policy = final_check.get("policy_evidence") if isinstance(final_check.get("policy_evidence"), dict) else {}
    locator = _identity_locator(identity)
    if identity.get("match_confidence") != "high":
        blockers.append("vm_identity_unknown" if identity.get("match_confidence") == "unknown" else "vm_identity_uncertain")
    if identity.get("conflict_signal") is True:
        blockers.append("identity_conflict")
    if _as_text(identity.get("identity_status"), "active") != "active":
        blockers.append("vm_identity_not_active")
    if _as_text(identity.get("vm_identity_id")) != job.vm_identity_id:
        blockers.append("vm_identity_mismatch")
    if _as_text(locator.get("cluster_id"), job.cluster_id) != job.cluster_id:
        blockers.append("cluster_identity_mismatch")
    if _as_int(locator.get("vmid"), job.vmid) != job.vmid:
        blockers.append("vmid_identity_mismatch")
    if _as_text(locator.get("node_id"), job.source_node_id) != job.source_node_id:
        blockers.append("source_identity_mismatch")
    if policy.get("policy") != "allowed":
        blockers.append(f"migration_policy_{_as_text(policy.get('policy'), 'unknown')}")

    recommendation = final_check.get("recommendation") if isinstance(final_check.get("recommendation"), dict) else {}
    if _as_int(recommendation.get("vmid"), job.vmid) != job.vmid:
        blockers.append("recommendation_vmid_mismatch")
    if _as_text(recommendation.get("source_node_id"), job.source_node_id) != job.source_node_id:
        blockers.append("recommendation_source_mismatch")
    if _as_text(recommendation.get("target_node_id"), job.target_node_id) != job.target_node_id:
        blockers.append("recommendation_target_mismatch")

    checks = ((final_check.get("check") or {}).get("checks") or {}) if isinstance(final_check.get("check"), dict) else {}
    for name, item in checks.items():
        if not isinstance(item, dict):
            blockers.append(f"{name}_missing")
            continue
        status = _as_text(item.get("status"))
        if name in LIVE_SUPERSEDED_ADVISOR_CHECKS and status in {"not_collected", "not_implemented"}:
            continue
        if status in BAD_EVIDENCE_STATUSES:
            blockers.append(_as_text(item.get("blocker"), f"{name}_{status}"))
    return _dedupe(blockers)


def _live_precheck_blockers(live_precheck: dict[str, Any] | None) -> list[str]:
    if not isinstance(live_precheck, dict):
        return ["live_precheck_missing"]
    blockers = list(live_precheck.get("blockers") or [])
    checks = live_precheck.get("checks") if isinstance(live_precheck.get("checks"), dict) else {}
    required = {
        "proxmox_active_task",
        "proxmox_cluster_quorum",
        "proxmox_ha_state",
        "proxmox_migration_preconditions",
    }
    for name in sorted(required):
        item = checks.get(name) if isinstance(checks.get(name), dict) else None
        if item is None:
            blockers.append(f"{name}_missing")
            continue
        status = _as_text(item.get("status"))
        if status != "pass":
            blockers.append(_as_text(item.get("blocker"), f"{name}_{status or 'unknown'}"))
    return _dedupe(blockers)


def _compact_dict(value: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in keys if key in value}


def _compact_tasks(tasks: list[Any]) -> list[dict[str, Any]]:
    return [_compact_dict(task, _COMPACT_TASK_KEYS) for task in tasks if isinstance(task, dict)][:10]


def _compact_error_details(value: Any) -> dict[str, Any]:
    keys = ("method", "path", "status_code", "reason", "node", "vmid", "source_node", "target_node", "response_type")
    return _compact_dict(value, keys)


def _task_result_from_status(status: dict[str, Any]) -> str:
    normalized = _as_text(status.get("status")).lower()
    if normalized == "stopped":
        return "ok" if _as_text(status.get("exitstatus")) == "OK" else "failed"
    if normalized == "running":
        return "running"
    if normalized:
        return "ambiguous"
    return "unknown"


def _disk_volume_ids_from_config(config: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for key, value in sorted(config.items()):
        if not _DISK_CONFIG_PREFIX.match(_as_text(key)):
            continue
        volume = _identity_disk_volume_from_config_value(value)
        if not volume:
            continue
        result.append(volume.lower())
    return _dedupe(result)


def _identity_disk_volume_from_config_value(value: Any) -> str:
    parts = [part.strip() for part in _as_text(value).split(",") if part.strip()]
    if not parts:
        return ""
    params: dict[str, str] = {}
    for part in parts[1:]:
        key, separator, param_value = part.partition("=")
        params[key.strip().lower()] = param_value.strip() if separator else "true"
    if _as_text(params.get("media")).lower() == "cdrom":
        return ""
    volume = parts[0]
    lowered = volume.lower()
    if not volume or lowered == "none" or ":" not in volume:
        return ""
    normalized = lowered.replace("-", "")
    if "cloudinit" in normalized:
        return ""
    return volume


def _mac_addresses_from_config(config: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for key, value in sorted(config.items()):
        if not _as_text(key).startswith("net"):
            continue
        match = _MAC_IN_NET_CONFIG.search(_as_text(value))
        if match is not None:
            result.append(match.group(1).lower())
    return _dedupe(result)


def _observed_vm_like(
    *,
    node_id: str,
    vmid: int,
    status: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    return {
        "vmid": int(vmid),
        "name": _as_text(config.get("name") or status.get("name"), f"vm-{vmid}"),
        "node_id": _as_text(status.get("node") or config.get("node"), node_id),
        "status": _as_text(status.get("status") or status.get("qmpstatus"), "unknown").lower(),
        "template": str(config.get("template", "0")).lower() in {"1", "true", "yes"},
        "smbios1": _as_text(config.get("smbios1")),
        "vmgenid": _as_text(config.get("vmgenid")),
        "mac_addresses": _mac_addresses_from_config(config),
        "disk_volume_ids": _disk_volume_ids_from_config(config),
    }


def _identity_from_final_check(final_check: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(final_check, dict):
        return {}
    identity = final_check.get("identity_evidence")
    if isinstance(identity, dict):
        return dict(identity)
    recommendation = final_check.get("recommendation")
    identity = recommendation.get("identity_evidence") if isinstance(recommendation, dict) else {}
    return dict(identity) if isinstance(identity, dict) else {}


def _identity_from_recommendation_artifact(packet: DrsApprovalPacketRecord) -> dict[str, Any]:
    payload = _read_json_artifact_payload(packet.recommendation_artifact_id)
    identity = payload.get("identity") if isinstance(payload.get("identity"), dict) else {}
    locator = identity.get("locator") if isinstance(identity.get("locator"), dict) else {}
    return {
        "vm_identity_id": identity.get("vm_identity_id"),
        "stable_fingerprint": _as_text(identity.get("stable_fingerprint")),
        "match_confidence": _as_text(identity.get("match_confidence"), "unknown"),
        "identity_status": _as_text(identity.get("identity_status"), "unknown"),
        "conflict_signal": identity.get("conflict_signal") is True,
        "fingerprint_components": {"locator": dict(locator)},
    }


def _expected_post_check(
    *,
    job: DrsMigrationJobRecord,
    packet: DrsApprovalPacketRecord,
    final_check: dict[str, Any] | None,
) -> dict[str, Any]:
    identity = _identity_from_final_check(final_check) or _identity_from_recommendation_artifact(packet)
    components = identity.get("fingerprint_components") if isinstance(identity.get("fingerprint_components"), dict) else {}
    locator = components.get("locator") if isinstance(components.get("locator"), dict) else {}
    return {
        "cluster_id": job.cluster_id,
        "vm_identity_id": job.vm_identity_id,
        "stable_fingerprint": _as_text(identity.get("stable_fingerprint")),
        "target_node_id": job.target_node_id,
        "vmid": job.vmid,
        "vm_name": _as_text(packet.vm_name or locator.get("name")),
        "power_state": "running",
    }


def _first_post_check_reason(blockers: list[str]) -> str:
    priority = [
        "fingerprint_mismatch",
        "post_check_target_mismatch",
        "post_check_vm_missing",
        "post_check_power_mismatch",
        "post_check_active_task_conflict",
        "post_check_active_task_evidence_unavailable",
        "post_check_config_unavailable",
        "post_check_evidence_unavailable",
        "expected_fingerprint_missing",
        "observed_fingerprint_missing",
    ]
    for code in priority:
        if code in blockers:
            return code
    return blockers[0] if blockers else ""


def _collect_active_task_post_check(client: Any, *, nodes: list[str], vmid: int) -> tuple[list[str], dict[str, Any]]:
    blockers: list[str] = []
    by_node: dict[str, Any] = {}
    total = 0
    for node in _dedupe(nodes):
        try:
            tasks = client.list_active_tasks(node=node, vmid=vmid)
            task_list = _as_list(tasks)
            total += len(task_list)
            by_node[node] = {"status": "pass" if not task_list else "conflict", "count": len(task_list), "tasks": _compact_tasks(task_list)}
            if task_list:
                blockers.append("post_check_active_task_conflict")
        except Exception as exc:
            blockers.append("post_check_active_task_evidence_unavailable")
            details = getattr(exc, "details", {})
            by_node[node] = {
                "status": "unavailable",
                "count": None,
                "tasks": [],
                "error": _as_text(exc),
                "details": _compact_error_details(details),
            }
    return blockers, {"source": "proxmox_drs_direct", "count": total, "by_node": by_node}


def _collect_direct_drs_post_check(
    *,
    client: Any,
    job: DrsMigrationJobRecord,
    packet: DrsApprovalPacketRecord,
    final_check: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checked_at = _now().isoformat()
    expected = _expected_post_check(job=job, packet=packet, final_check=final_check)
    blockers: list[str] = []
    checks: dict[str, Any] = {}
    status_payload: dict[str, Any] = {}
    config_payload: dict[str, Any] = {}

    try:
        status_payload = client.get_vm_status(node=job.target_node_id, vmid=job.vmid)
        if not isinstance(status_payload, dict) or not status_payload:
            blockers.append("post_check_vm_missing")
            checks["vm_exists"] = {"status": "missing", "endpoint_node": job.target_node_id}
        else:
            checks["vm_exists"] = {"status": "pass", "endpoint_node": job.target_node_id}
    except Exception as exc:
        blockers.append("post_check_vm_missing")
        details = getattr(exc, "details", {})
        checks["vm_exists"] = {
            "status": "missing",
            "endpoint_node": job.target_node_id,
            "error": _as_text(exc),
            "details": _compact_error_details(details),
        }

    try:
        config_payload = client.get_vm_config(node=job.target_node_id, vmid=job.vmid)
        if not isinstance(config_payload, dict) or not config_payload:
            blockers.append("post_check_config_unavailable")
            checks["vm_config"] = {"status": "unavailable", "endpoint_node": job.target_node_id}
        else:
            checks["vm_config"] = {
                "status": "pass",
                "endpoint_node": job.target_node_id,
                "curated_fields": {
                    "name_present": bool(_as_text(config_payload.get("name"))),
                    "smbios1_present": bool(_as_text(config_payload.get("smbios1"))),
                    "vmgenid_present": bool(_as_text(config_payload.get("vmgenid"))),
                    "disk_volume_id_count": len(_disk_volume_ids_from_config(config_payload)),
                    "mac_address_count": len(_mac_addresses_from_config(config_payload)),
                },
            }
    except Exception as exc:
        blockers.append("post_check_config_unavailable")
        details = getattr(exc, "details", {})
        checks["vm_config"] = {
            "status": "unavailable",
            "endpoint_node": job.target_node_id,
            "error": _as_text(exc),
            "details": _compact_error_details(details),
        }

    observed: dict[str, Any] = {
        "cluster_id": job.cluster_id,
        "target_node_endpoint": job.target_node_id,
        "vmid": job.vmid,
        "exists_on_target": bool(status_payload),
        "power_state": _as_text(status_payload.get("status") or status_payload.get("qmpstatus"), "unknown").lower(),
    }
    if status_payload and config_payload:
        observed_vm = _observed_vm_like(node_id=job.target_node_id, vmid=job.vmid, status=status_payload, config=config_payload)
        components = fingerprint_components_for_vm(observed_vm, cluster_id=job.cluster_id)
        observed_fingerprint = stable_fingerprint_for_components(components)
        locator = components.get("locator") if isinstance(components.get("locator"), dict) else {}
        observed.update(
            {
                "node_id": _as_text(locator.get("node_id"), job.target_node_id),
                "name": _as_text(locator.get("name")),
                "stable_fingerprint": observed_fingerprint,
                "fingerprint_components": components,
            }
        )
        if _as_text(observed.get("node_id")) != job.target_node_id:
            blockers.append("post_check_target_mismatch")
        if observed["power_state"] != expected["power_state"]:
            blockers.append("post_check_power_mismatch")
        if not expected["stable_fingerprint"]:
            blockers.append("expected_fingerprint_missing")
        elif not observed_fingerprint:
            blockers.append("observed_fingerprint_missing")
        elif observed_fingerprint != expected["stable_fingerprint"]:
            blockers.append("fingerprint_mismatch")
    elif not status_payload:
        blockers.append("post_check_evidence_unavailable")
    else:
        blockers.append("post_check_config_unavailable")

    task_blockers, task_evidence = _collect_active_task_post_check(
        client,
        nodes=[job.source_node_id, job.target_node_id],
        vmid=job.vmid,
    )
    blockers.extend(task_blockers)
    checks["active_tasks"] = task_evidence
    blockers = _dedupe(blockers)
    status = "pass" if not blockers else "needs_reconciliation"
    reason = _first_post_check_reason(blockers)
    return {
        "status": status,
        "checked_at": checked_at,
        "source": "proxmox_drs_direct",
        "read_only": True,
        "expected": expected,
        "observed": observed,
        "checks": checks,
        "blockers": blockers,
        "reconciliation_required": bool(blockers),
        "reconciliation_reason": reason or None,
    }


def _reconciliation_event_type(reason: str | None) -> str:
    reason = _as_text(reason, "unknown")
    if reason == "fingerprint_mismatch":
        return "fingerprint_mismatch"
    if reason.startswith("post_check_") or reason == "observed_fingerprint_missing":
        return "drift"
    return "ambiguous_evidence"


def _record_reconciliation_event(
    session: Any,
    *,
    job_id: str,
    reason: str | None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = _now()
    event = DrsReconciliationEventRecord(
        event_id=f"drsrec-{uuid.uuid4().hex}",
        job_id=job_id,
        event_type=_reconciliation_event_type(reason),
        status="open",
        reason=_as_text(reason, "unknown"),
        evidence=evidence or {},
        created_at=now,
        updated_at=now,
    )
    session.add(event)
    session.flush()
    return {
        "event_id": event.event_id,
        "job_id": event.job_id,
        "event_type": event.event_type,
        "status": event.status,
        "reason": event.reason,
        "evidence": event.evidence,
        "created_at": event.created_at.isoformat(),
    }


def _list_reconciliation_events(job_id: str) -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = (
            session.query(DrsReconciliationEventRecord)
            .filter(DrsReconciliationEventRecord.job_id == job_id)
            .order_by(DrsReconciliationEventRecord.created_at.asc(), DrsReconciliationEventRecord.event_id.asc())
            .all()
        )
        return [
            {
                "event_id": row.event_id,
                "job_id": row.job_id,
                "event_type": row.event_type,
                "status": row.status,
                "reason": row.reason,
                "evidence": dict(row.evidence or {}),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]


def _resolve_open_reconciliation_events(
    session: Any,
    *,
    job_id: str,
    reason: str,
    evidence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rows = (
        session.query(DrsReconciliationEventRecord)
        .filter(DrsReconciliationEventRecord.job_id == job_id, DrsReconciliationEventRecord.status == "open")
        .order_by(DrsReconciliationEventRecord.created_at.asc(), DrsReconciliationEventRecord.event_id.asc())
        .all()
    )
    now = _now()
    for row in rows:
        row.status = "resolved"
        row.reason = _as_text(reason, row.reason)
        row.evidence = {**dict(row.evidence or {}), **dict(evidence or {})}
        row.updated_at = now
    session.flush()
    return [
        {
            "event_id": row.event_id,
            "job_id": row.job_id,
            "event_type": row.event_type,
            "status": row.status,
            "reason": row.reason,
            "evidence": dict(row.evidence or {}),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


def _stored_lock_result(job: DrsMigrationJobRecord) -> dict[str, Any]:
    lock_result = dict(job.lock_evidence or {})
    lock_ids = list(job.operation_lock_ids or lock_result.get("lock_ids") or [])
    lock_result["lock_ids"] = lock_ids
    lock_result.setdefault("locks", [])
    lock_result.setdefault("checked_scopes", [])
    return lock_result


def _dispatch_attempt_evidence(
    *,
    job: DrsMigrationJobRecord,
    actor: dict[str, str],
    prepared_at: datetime,
) -> dict[str, Any]:
    return {
        "state": "prepared",
        "prepared_at": prepared_at.isoformat(),
        "target": {
            "source_node_id": job.source_node_id,
            "target_node_id": job.target_node_id,
            "vmid": job.vmid,
        },
        "task_node": job.source_node_id,
        "actor": {
            "user_id": actor["user_id"],
            "username": actor["username"],
            "role": actor["role"],
        },
    }


def _prepared_dispatch_without_upid(job: DrsMigrationJobRecord) -> bool:
    evidence = job.execution_evidence if isinstance(job.execution_evidence, dict) else {}
    dispatch_attempt = evidence.get("dispatch_attempt") if isinstance(evidence.get("dispatch_attempt"), dict) else {}
    return (
        not _as_text(job.proxmox_upid)
        and dispatch_attempt.get("state") == "prepared"
        and (
            job.status == "running"
            or (job.status == "needs_reconciliation" and job.reconciliation_reason == "dispatch_prepared_without_upid")
        )
    )


def _raise_prepared_dispatch_reentry(
    job: DrsMigrationJobRecord,
    packet: DrsApprovalPacketRecord,
    *,
    actor: dict[str, str],
) -> None:
    result = _project_prepared_dispatch_reconciliation(
        job=job,
        packet=packet,
        actor=actor,
        evidence_source="drs_execution_reentry",
    )
    job_record = result["job"]
    evidence = job_record.get("execution_evidence") if isinstance(job_record.get("execution_evidence"), dict) else {}
    dispatch_attempt = evidence.get("dispatch_attempt") if isinstance(evidence.get("dispatch_attempt"), dict) else {}
    raise DrsMigrationExecutionError(
        code="DRS_EXECUTION_DISPATCH_RECONCILIATION_REQUIRED",
        message="DRS migration dispatch was prepared but no Proxmox UPID was durably stored; reconcile before retrying execution",
        detail={
            "job_id": job.job_id,
            "approval_packet_id": packet.approval_packet_id,
            "status": result["status"],
            "actual_status": result["status"],
            "blockers": ["drs_dispatch_prepared_without_upid"],
            "dispatch_attempt": dict(dispatch_attempt),
            "operation_lock": result["operation_lock"],
            "proxmox_mutation_enabled": False,
            "proxmox_mutation_may_have_run_previously": True,
            "corrective_mutation_enabled": False,
            "side_effects": result["side_effects"],
            "needs_reconciliation": True,
            "reconciliation_reason": "dispatch_prepared_without_upid",
            "job": job_record,
            "job_run": result["job_run"],
            "artifact": result["artifact"],
            "reconciliation_events": result["reconciliation_events"],
        },
    )


def _record_blocked_attempt(
    *,
    job: DrsMigrationJobRecord,
    packet: DrsApprovalPacketRecord,
    actor: dict[str, str],
    stage: str,
    blockers: list[str],
    final_check: dict[str, Any] | None = None,
    live_precheck: dict[str, Any] | None = None,
    lock_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = {
        "blockers": blockers,
        "final_precheck_summary": final_precheck_summary(final_check) if final_check else {},
        "live_precheck": live_precheck or {},
        "operation_lock": lock_result or {},
    }
    now = _now()
    with session_scope() as session:
        row = session.get(DrsMigrationJobRecord, job.job_id)
        if row is not None and row.status == "pending":
            row.status = "blocked"
            row.runnable = False
            row.proxmox_mutation_enabled = False
            row.runnable_blockers = blockers
            row.execution_evidence = evidence
            row.updated_at = now
    job_for_evidence = {
        **_row_dict(job),
        "status": "blocked",
        "runnable": False,
        "proxmox_mutation_enabled": False,
        "side_effects": [],
        "runnable_blockers": blockers,
        "execution_evidence": evidence,
        "lock_evidence": lock_result or dict(job.lock_evidence or {}),
    }
    drs_evidence = build_drs_run_evidence(
        job=job_for_evidence,
        packet=packet,
        approved_actor=dict(job.approved_actor or {}),
        executed_actor=actor,
        final_precheck_summary=evidence["final_precheck_summary"],
        live_precheck=live_precheck,
        operation_lock=lock_result or dict(job.lock_evidence or {}),
        blockers=blockers,
        acknowledgement_field=DRS_LIVE_MIGRATION_ACK_FIELD,
        acknowledgement_value=True,
    )
    job_run = record_job_run(
        job_id=job.job_id,
        job_type=DRS_MIGRATION_JOB_TYPE,
        status="blocked",
        target_id=_target_id(job),
        risk_level="yellow",
        stage=stage,
        step_status="blocked",
        message=f"DRS migration execution blocked: {', '.join(blockers[:3])}",
        details={
            "approval_packet_id": packet.approval_packet_id,
            "recommendation_id": job.recommendation_id,
            "vm_identity_id": job.vm_identity_id,
            "source_node_id": job.source_node_id,
            "target_node_id": job.target_node_id,
            "vmid": job.vmid,
            "blockers": blockers,
            "proxmox_mutation_enabled": False,
            "side_effects": [],
            "drs_evidence": drs_evidence,
            **actor_detail_fields(actor),
        },
    )
    return {
        "job_id": job.job_id,
        "status": "blocked",
        "blockers": blockers,
        "approval_packet_id": packet.approval_packet_id,
        "final_precheck_summary": evidence["final_precheck_summary"],
        "live_precheck": live_precheck or {},
        "operation_lock": lock_result or {},
        "job_run": job_run,
        "proxmox_mutation_enabled": False,
        "side_effects": [],
    }


def _write_execution_artifact(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    artifact = write_json_artifact(
        run_dir=run_dir(job_id),
        job_id=job_id,
        artifact_type="drs_migration_execution",
        filename="drs_migration_execution.json",
        payload=payload,
    )
    return artifact.to_dict()


def _mark_dispatch_prepared(
    *,
    job: DrsMigrationJobRecord,
    actor: dict[str, str],
    final_check: dict[str, Any],
    live_precheck: dict[str, Any],
    lock_result: dict[str, Any],
) -> dict[str, Any]:
    prepared_at = _now()
    dispatch_attempt = _dispatch_attempt_evidence(job=job, actor=actor, prepared_at=prepared_at)
    side_effects = ["drs_operation_locks_acquired"]
    with session_scope() as session:
        row = session.get(DrsMigrationJobRecord, job.job_id)
        if row is None:
            raise DrsMigrationExecutionError(
                code="DRS_JOB_NOT_FOUND_AFTER_LOCK",
                message="DRS migration job disappeared after operation locks were acquired",
                status_code=500,
                detail={"job_id": job.job_id, "side_effects": side_effects},
            )
        row.status = "running"
        row.runnable = False
        row.proxmox_mutation_enabled = False
        row.side_effects = side_effects
        row.proxmox_task_node = job.source_node_id
        row.migration_started_at = prepared_at
        row.execution_evidence = {
            **dict(row.execution_evidence or {}),
            "final_precheck_summary": final_precheck_summary(final_check),
            "live_precheck": live_precheck,
            "operation_lock": lock_result,
            "dispatch_attempt": dispatch_attempt,
        }
        row.operation_lock_ids = list(lock_result.get("lock_ids") or [])
        row.lock_evidence = lock_result
        row.updated_at = prepared_at
        session.flush()
        return _row_dict(row)


def _mark_dispatch_accepted(
    *,
    job: DrsMigrationJobRecord,
    upid: str,
    final_check: dict[str, Any],
    live_precheck: dict[str, Any],
    lock_result: dict[str, Any],
    side_effects: list[str],
) -> dict[str, Any]:
    accepted_at = _now()
    with session_scope() as session:
        row = session.get(DrsMigrationJobRecord, job.job_id)
        if row is None:
            raise DrsMigrationExecutionError(
                code="DRS_JOB_NOT_FOUND_AFTER_MUTATION",
                message="DRS migration job disappeared while storing execution evidence",
                status_code=500,
                detail={"job_id": job.job_id, "proxmox_upid": upid, "side_effects": side_effects},
            )
        execution_evidence = dict(row.execution_evidence or {})
        dispatch_attempt = dict(execution_evidence.get("dispatch_attempt") or {})
        dispatch_attempt.update(
            {
                "state": "accepted",
                "accepted_at": accepted_at.isoformat(),
                "upid_stored_at": accepted_at.isoformat(),
                "proxmox_upid": upid,
                "task_node": job.source_node_id,
            }
        )
        row.status = "accepted"
        row.runnable = False
        row.proxmox_mutation_enabled = True
        row.side_effects = side_effects
        row.proxmox_upid = upid
        row.proxmox_task_node = job.source_node_id
        row.migration_started_at = row.migration_started_at or accepted_at
        row.execution_evidence = {
            **execution_evidence,
            "final_precheck_summary": final_precheck_summary(final_check),
            "live_precheck": live_precheck,
            "operation_lock": lock_result,
            "dispatch_attempt": dispatch_attempt,
            "upid_stored_at": accepted_at.isoformat(),
        }
        row.operation_lock_ids = list(lock_result.get("lock_ids") or [])
        row.lock_evidence = lock_result
        row.updated_at = accepted_at
        session.flush()
        return _row_dict(row)


def _update_after_upid(
    *,
    job_id: str,
    upid: str | None,
    status: str,
    task_node: str,
    task_result: str,
    task_payload: dict[str, Any],
    live_precheck: dict[str, Any],
    final_check: dict[str, Any] | None,
    lock_result: dict[str, Any],
    side_effects: list[str],
    reconciliation_reason: str | None = None,
    post_check_evidence: dict[str, Any] | None = None,
    post_check_status: str | None = None,
) -> dict[str, Any]:
    now = _now()
    status_payload = task_payload.get("status") if isinstance(task_payload.get("status"), dict) else {}
    log_excerpt = _as_list(task_payload.get("log"))
    with session_scope() as session:
        row = session.get(DrsMigrationJobRecord, job_id)
        if row is None:
            raise DrsMigrationExecutionError(
                code="DRS_JOB_NOT_FOUND_AFTER_MUTATION",
                message="DRS migration job disappeared while storing execution evidence",
                status_code=500,
                detail={"job_id": job_id, "proxmox_upid": upid, "side_effects": side_effects},
            )
        precheck_summary = final_precheck_summary(final_check) if final_check is not None else dict(row.final_precheck_summary or {})
        execution_evidence = {
            **dict(row.execution_evidence or {}),
            "final_precheck_summary": precheck_summary,
            "live_precheck": live_precheck,
            "operation_lock": lock_result,
            "task": {
                "result": task_result,
                "status": status_payload,
                "polls": _as_list(task_payload.get("polls"))[:5],
                "log_excerpt_count": len(log_excerpt),
            },
            "post_check": post_check_evidence or {},
            "reconciliation_reason": reconciliation_reason,
        }
        row.status = status
        row.runnable = False
        row.proxmox_mutation_enabled = True
        row.side_effects = side_effects
        row.proxmox_upid = upid
        row.proxmox_task_node = task_node
        row.migration_started_at = row.migration_started_at or now
        row.migration_finished_at = now if status in {"completed", "needs_reconciliation", "failed", "timed_out", "ambiguous"} else None
        row.task_status = _as_text(status_payload.get("status")) or None
        row.task_exitstatus = _as_text(status_payload.get("exitstatus")) or None
        row.task_result = task_result
        row.task_metadata = {
            "result": task_result,
            "status": status_payload,
            "poll_count": len(_as_list(task_payload.get("polls"))),
        }
        row.task_log_excerpt = log_excerpt[:50]
        row.post_check_status = post_check_status
        row.post_check_evidence = post_check_evidence or {}
        row.post_check_completed_at = now if post_check_status == "completed" else None
        row.execution_evidence = execution_evidence
        row.operation_lock_ids = list(lock_result.get("lock_ids") or [])
        row.reconciliation_reason = reconciliation_reason
        row.runnable_blockers = [reconciliation_reason] if reconciliation_reason else []
        row.lock_evidence = lock_result
        row.updated_at = now
        session.flush()
        return _row_dict(row)


def _mark_after_lock_uncertainty(
    *,
    job_id: str,
    task_node: str,
    task_result: str,
    reason: str,
    error: DrsProxmoxMigrationError,
    live_precheck: dict[str, Any],
    final_check: dict[str, Any],
    lock_result: dict[str, Any],
    side_effects: list[str],
) -> dict[str, Any]:
    task_payload = {
        "result": task_result,
        "status": {},
        "polls": [],
        "log": [],
        "error": str(error),
        "details": error.details,
    }
    job_record = _update_after_upid(
        job_id=job_id,
        upid=None,
        status="needs_reconciliation",
        task_node=task_node,
        task_result=task_result,
        task_payload=task_payload,
        live_precheck=live_precheck,
        final_check=final_check,
        lock_result=lock_result,
        side_effects=side_effects,
        reconciliation_reason=reason,
    )
    with session_scope() as session:
        locks = mark_locks_reconciliation_required(
            session,
            lock_ids=list(lock_result.get("lock_ids") or []),
            reason=reason,
            evidence={
                "source": "drs_execution",
                "job_id": job_id,
                "task_result": task_result,
                "reconciliation_reason": reason,
            },
        )
        reconciliation_event = _record_reconciliation_event(
            session,
            job_id=job_id,
            reason=reason,
            evidence={
                "source": "drs_execution",
                "task_result": task_result,
                "reconciliation_reason": reason,
                "error": str(error),
                "details": _compact_error_details(error.details),
            },
        )
        row = session.get(DrsMigrationJobRecord, job_id)
        if row is not None:
            row.lock_evidence = {**lock_result, "locks": locks, "lock_ids": [lock["operation_lock_id"] for lock in locks]}
            row.operation_lock_ids = [lock["operation_lock_id"] for lock in locks]
            row.updated_at = _now()
    job_record["lock_evidence"] = {**lock_result, "locks": locks, "lock_ids": [lock["operation_lock_id"] for lock in locks]}
    job_record["reconciliation_event"] = reconciliation_event
    return job_record


def _status_from_task_result(task_result: str) -> tuple[str, str | None, str]:
    if task_result == "running":
        return "running", None, "running"
    if task_result == "ok":
        return "needs_reconciliation", "task_ok_requires_post_check", "blocked"
    if task_result == "failed":
        return "needs_reconciliation", "task_failed", "blocked"
    if task_result == "timeout":
        return "needs_reconciliation", "task_timeout", "blocked"
    return "needs_reconciliation", "task_ambiguous", "blocked"


def _record_execution_run(
    *,
    job_record: dict[str, Any],
    packet: DrsApprovalPacketRecord,
    actor: dict[str, str],
    artifact: dict[str, Any],
    step_status: str,
    response_proxmox_mutation_enabled: bool = True,
    proxmox_mutation_may_have_run_previously: bool = False,
) -> dict[str, Any]:
    status = _as_text(job_record.get("status"))
    post_check = job_record.get("post_check_evidence") if isinstance(job_record.get("post_check_evidence"), dict) else {}
    execution_evidence = job_record.get("execution_evidence") if isinstance(job_record.get("execution_evidence"), dict) else {}
    final_summary = execution_evidence.get("final_precheck_summary") if isinstance(execution_evidence.get("final_precheck_summary"), dict) else {}
    if not final_summary:
        final_summary = job_record.get("final_precheck_summary") if isinstance(job_record.get("final_precheck_summary"), dict) else {}
    reconciliation_events = _list_reconciliation_events(job_record["job_id"])
    drs_evidence = build_drs_run_evidence(
        job=job_record,
        packet=packet,
        approved_actor=job_record.get("approved_actor") if isinstance(job_record.get("approved_actor"), dict) else {},
        executed_actor=actor,
        final_precheck_summary=final_summary,
        live_precheck=execution_evidence.get("live_precheck") if isinstance(execution_evidence.get("live_precheck"), dict) else {},
        operation_lock=job_record.get("lock_evidence") if isinstance(job_record.get("lock_evidence"), dict) else execution_evidence.get("operation_lock"),
        task=execution_evidence.get("task") if isinstance(execution_evidence.get("task"), dict) else {},
        post_check=post_check,
        blockers=list(job_record.get("runnable_blockers") or []),
        acknowledgement_field=DRS_LIVE_MIGRATION_ACK_FIELD,
        acknowledgement_value=True,
        reconciliation_events=reconciliation_events,
        resolved_reconciliation_events=list(job_record.get("resolved_reconciliation_events") or []),
    )
    if status == "completed":
        stage = "post_check"
        message = "DRS migration completed after Proxmox task OK and verified direct post-check."
        risk_level = "green"
        step_status = "completed"
    elif status == "running":
        stage = "task_poll"
        message = "DRS live migration task is still running; operation locks remain active."
        risk_level = "yellow"
    elif post_check:
        stage = "post_check"
        message = f"DRS migration needs reconciliation after post-check: {_as_text(job_record.get('reconciliation_reason'), 'unknown')}"
        risk_level = "yellow"
    else:
        stage = "reconciliation"
        message = f"DRS migration needs reconciliation: {_as_text(job_record.get('reconciliation_reason'), 'unknown')}"
        risk_level = "yellow"
    return record_job_run(
        job_id=job_record["job_id"],
        job_type=DRS_MIGRATION_JOB_TYPE,
        status=status,
        target_id=_target_id(job_record),
        risk_level=risk_level,
        stage=stage,
        step_status=step_status,
        message=message,
        artifacts=[artifact],
        details={
            "approval_packet_id": packet.approval_packet_id,
            "recommendation_id": job_record.get("recommendation_id"),
            "vm_identity_id": job_record.get("vm_identity_id"),
            "source_node_id": job_record.get("source_node_id"),
            "target_node_id": job_record.get("target_node_id"),
            "vmid": job_record.get("vmid"),
            "proxmox_upid": job_record.get("proxmox_upid"),
            "task_result": job_record.get("task_result"),
            "task_status": job_record.get("task_status"),
            "task_exitstatus": job_record.get("task_exitstatus"),
            "post_check_status": job_record.get("post_check_status"),
            "post_check": post_check,
            "reconciliation_reason": job_record.get("reconciliation_reason"),
            "reconciliation_required": status == "needs_reconciliation",
            "reconciliation_events": reconciliation_events,
            "operation_lock_ids": list(job_record.get("operation_lock_ids") or []),
            "proxmox_mutation_enabled": response_proxmox_mutation_enabled,
            "proxmox_mutation_may_have_run_previously": proxmox_mutation_may_have_run_previously,
            "side_effects": list(job_record.get("side_effects") or []),
            "drs_evidence": drs_evidence,
            **actor_detail_fields(actor),
        },
    )


def _project_prepared_dispatch_reconciliation(
    *,
    job: DrsMigrationJobRecord,
    packet: DrsApprovalPacketRecord,
    actor: dict[str, str],
    evidence_source: str,
    post_check: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist an unknown dispatch outcome without issuing another Proxmox mutation."""
    now = _now()
    reason = "dispatch_prepared_without_upid"
    task_result = "dispatch_outcome_unknown"
    observed_post_check = dict(post_check or {})
    stored_lock_result = _stored_lock_result(job)
    historical_side_effects = [
        effect
        for effect in list(job.side_effects or [])
        if effect != "proxmox_migrate_invoked"
    ]
    side_effects = _dedupe(
        [
            *historical_side_effects,
            "proxmox_migrate_invocation_outcome_unknown",
            *(["proxmox_drs_post_check_observed"] if observed_post_check else []),
        ]
    )
    with session_scope() as session:
        row = session.get(DrsMigrationJobRecord, job.job_id)
        if row is None:
            raise DrsMigrationExecutionError(
                code="DRS_JOB_NOT_FOUND_DURING_RECONCILIATION",
                message="DRS migration job disappeared while recording dispatch reconciliation",
                status_code=500,
                detail={"job_id": job.job_id, "proxmox_mutation_enabled": False, "side_effects": []},
            )
        execution_evidence = dict(row.execution_evidence or {})
        dispatch_attempt = dict(execution_evidence.get("dispatch_attempt") or {})
        dispatch_attempt.update(
            {
                "outcome": "unknown",
                "reconciliation_required_at": now.isoformat(),
                "proxmox_upid_stored": False,
            }
        )
        locks = mark_locks_reconciliation_required(
            session,
            lock_ids=list(row.operation_lock_ids or stored_lock_result.get("lock_ids") or []),
            reason=reason,
            evidence={
                "source": evidence_source,
                "job_id": row.job_id,
                "task_result": task_result,
                "proxmox_upid_stored": False,
                "proxmox_mutation_may_have_run_previously": True,
            },
        )
        lock_result = {
            **stored_lock_result,
            "locks": locks,
            "lock_ids": [lock["operation_lock_id"] for lock in locks],
        }
        reconciliation_event = _record_reconciliation_event(
            session,
            job_id=row.job_id,
            reason=reason,
            evidence={
                "source": evidence_source,
                "task_result": task_result,
                "dispatch_attempt": dispatch_attempt,
                "post_check": observed_post_check,
                "proxmox_upid_stored": False,
                "proxmox_mutation_may_have_run_previously": True,
                **actor_detail_fields(actor),
            },
        )
        row.status = "needs_reconciliation"
        row.runnable = False
        row.proxmox_mutation_enabled = False
        row.side_effects = side_effects
        row.task_status = None
        row.task_exitstatus = None
        row.task_result = task_result
        row.task_metadata = {
            "result": task_result,
            "proxmox_upid_stored": False,
            "proxmox_mutation_may_have_run_previously": True,
        }
        row.task_log_excerpt = []
        row.post_check_status = "needs_reconciliation" if observed_post_check else None
        row.post_check_evidence = observed_post_check
        row.post_check_completed_at = None
        row.execution_evidence = {
            **execution_evidence,
            "operation_lock": lock_result,
            "dispatch_attempt": dispatch_attempt,
            "task": dict(row.task_metadata),
            "post_check": observed_post_check,
            "reconciliation_reason": reason,
            "proxmox_mutation_may_have_run_previously": True,
            "last_reconciliation_source": evidence_source,
            "last_reconciled_at": now.isoformat(),
        }
        row.operation_lock_ids = list(lock_result["lock_ids"])
        row.lock_evidence = lock_result
        row.reconciliation_reason = reason
        row.runnable_blockers = [reason]
        row.updated_at = now
        session.flush()
        job_record = _row_dict(row)

    reconciliation_events = _list_reconciliation_events(job.job_id)
    artifact = _write_execution_artifact(
        job.job_id,
        {
            "job": job_record,
            "approval_packet": {
                "approval_packet_id": packet.approval_packet_id,
                "recommendation_id": packet.recommendation_id,
                "vm_identity_id": packet.vm_identity_id,
            },
            "dispatch_attempt": dict((job_record.get("execution_evidence") or {}).get("dispatch_attempt") or {}),
            "post_check": observed_post_check,
            "reconciliation_reason": reason,
            "reconciliation_event": reconciliation_event,
            "reconciliation_events": reconciliation_events,
            "proxmox_mutation_enabled": False,
            "proxmox_mutation_may_have_run_previously": True,
            "source": evidence_source,
        },
    )
    job_run = _record_execution_run(
        job_record=job_record,
        packet=packet,
        actor=actor,
        artifact=artifact,
        step_status="blocked",
        response_proxmox_mutation_enabled=False,
        proxmox_mutation_may_have_run_previously=True,
    )
    return {
        "job": job_record,
        "job_run": job_run,
        "artifact": artifact,
        "status": "needs_reconciliation",
        "post_check_status": job_record.get("post_check_status"),
        "post_check": observed_post_check,
        "reconciliation_reason": reason,
        "operation_lock": job_record.get("lock_evidence") or lock_result,
        "proxmox_mutation_enabled": False,
        "proxmox_mutation_may_have_run_previously": True,
        "corrective_mutation_enabled": False,
        "side_effects": side_effects,
        "needs_reconciliation": True,
        "reconciliation_events": reconciliation_events,
        "read_only_proxmox_observation": bool(observed_post_check),
    }


def _finish_drs_task_follow_up(
    *,
    job: DrsMigrationJobRecord,
    packet: DrsApprovalPacketRecord,
    actor: dict[str, str],
    client: Any,
    upid: str,
    task_node: str,
    task_payload: dict[str, Any],
    final_check: dict[str, Any] | None,
    live_precheck: dict[str, Any],
    lock_result: dict[str, Any],
    base_side_effects: list[str],
    response_proxmox_mutation_enabled: bool,
    evidence_source: str,
) -> dict[str, Any]:
    task_result = _as_text(task_payload.get("result"), "ambiguous")
    side_effects = _dedupe([*base_side_effects, "proxmox_task_polled"])
    post_check_evidence: dict[str, Any] | None = None
    post_check_status: str | None = None
    if task_result == "ok":
        post_check_evidence = _collect_direct_drs_post_check(
            client=client,
            job=job,
            packet=packet,
            final_check=final_check,
        )
        side_effects = _dedupe([*side_effects, "proxmox_drs_post_check_observed"])
        if post_check_evidence.get("status") == "pass":
            status, reconciliation_reason, step_status = "completed", None, "completed"
            post_check_status = "completed"
        else:
            status = "needs_reconciliation"
            reconciliation_reason = _as_text(post_check_evidence.get("reconciliation_reason"), "post_check_mismatch")
            step_status = "blocked"
            post_check_status = "needs_reconciliation"
    else:
        status, reconciliation_reason, step_status = _status_from_task_result(task_result)

    job_record = _update_after_upid(
        job_id=job.job_id,
        upid=upid,
        status=status,
        task_node=task_node,
        task_result=task_result,
        task_payload=task_payload,
        live_precheck=live_precheck,
        final_check=final_check,
        lock_result=lock_result,
        side_effects=side_effects,
        reconciliation_reason=reconciliation_reason,
        post_check_evidence=post_check_evidence,
        post_check_status=post_check_status,
    )
    resolved_events: list[dict[str, Any]] = []
    reconciliation_event: dict[str, Any] | None = None
    if status == "completed":
        with session_scope() as session:
            locks = release_drs_operation_locks(
                session,
                lock_ids=list(lock_result.get("lock_ids") or []),
                reason="drs_migration_post_check_verified",
                evidence={
                    "source": evidence_source,
                    "job_id": job.job_id,
                    "upid": upid,
                    "task_result": task_result,
                    "post_check_status": "completed",
                },
            )
            resolved_events = _resolve_open_reconciliation_events(
                session,
                job_id=job.job_id,
                reason="resolved_after_verified_post_check",
                evidence={
                    "source": evidence_source,
                    "upid": upid,
                    "task_result": task_result,
                    "post_check_status": "completed",
                },
            )
            row = session.get(DrsMigrationJobRecord, job.job_id)
            if row is not None:
                row.lock_evidence = {**lock_result, "locks": locks, "lock_ids": [lock["operation_lock_id"] for lock in locks]}
                row.operation_lock_ids = [lock["operation_lock_id"] for lock in locks]
                row.updated_at = _now()
        job_record["lock_evidence"] = {**lock_result, "locks": locks, "lock_ids": [lock["operation_lock_id"] for lock in locks]}
        job_record["operation_lock_ids"] = [lock["operation_lock_id"] for lock in locks]
        job_record["resolved_reconciliation_events"] = resolved_events
    elif status == "needs_reconciliation":
        with session_scope() as session:
            locks = mark_locks_reconciliation_required(
                session,
                lock_ids=list(lock_result.get("lock_ids") or []),
                reason=_as_text(reconciliation_reason, "drs_migration_needs_reconciliation"),
                evidence={
                    "source": evidence_source,
                    "job_id": job.job_id,
                    "upid": upid,
                    "task_result": task_result,
                    "reconciliation_reason": reconciliation_reason,
                    "post_check_status": post_check_status,
                    "post_check_reason": reconciliation_reason,
                },
            )
            reconciliation_event = _record_reconciliation_event(
                session,
                job_id=job.job_id,
                reason=reconciliation_reason,
                evidence={
                    "source": evidence_source,
                    "upid": upid,
                    "task_result": task_result,
                    "task_status": task_payload.get("status") if isinstance(task_payload, dict) else {},
                    "post_check": post_check_evidence or {},
                },
            )
            row = session.get(DrsMigrationJobRecord, job.job_id)
            if row is not None:
                row.lock_evidence = {**lock_result, "locks": locks, "lock_ids": [lock["operation_lock_id"] for lock in locks]}
                row.operation_lock_ids = [lock["operation_lock_id"] for lock in locks]
                row.updated_at = _now()
        job_record["lock_evidence"] = {**lock_result, "locks": locks, "lock_ids": [lock["operation_lock_id"] for lock in locks]}
        job_record["operation_lock_ids"] = [lock["operation_lock_id"] for lock in locks]
        job_record["reconciliation_event"] = reconciliation_event

    precheck_summary = final_precheck_summary(final_check) if final_check is not None else dict(job_record.get("final_precheck_summary") or {})
    execution_payload = {
        "job": job_record,
        "approval_packet": {
            "approval_packet_id": packet.approval_packet_id,
            "recommendation_id": packet.recommendation_id,
            "vm_identity_id": packet.vm_identity_id,
        },
        "final_precheck_summary": precheck_summary,
        "live_precheck": live_precheck,
        "operation_lock": job_record.get("lock_evidence") or lock_result,
        "task": {
            "result": task_result,
            "status": task_payload.get("status") if isinstance(task_payload, dict) else {},
            "log_excerpt": _as_list(task_payload.get("log"))[:50] if isinstance(task_payload, dict) else [],
        },
        "post_check": post_check_evidence or {},
        "reconciliation_events": _list_reconciliation_events(job.job_id),
        "resolved_reconciliation_events": resolved_events,
        "source": evidence_source,
    }
    artifact = _write_execution_artifact(job.job_id, execution_payload)
    job_run = _record_execution_run(
        job_record=job_record,
        packet=packet,
        actor=actor,
        artifact=artifact,
        step_status=step_status,
        response_proxmox_mutation_enabled=response_proxmox_mutation_enabled,
        proxmox_mutation_may_have_run_previously=not response_proxmox_mutation_enabled and bool(side_effects),
    )
    return {
        "job": job_record,
        "job_run": job_run,
        "artifact": artifact,
        "status": status,
        "proxmox_upid": upid,
        "task_result": task_result,
        "task_status": job_record.get("task_status"),
        "task_exitstatus": job_record.get("task_exitstatus"),
        "post_check_status": post_check_status,
        "post_check": post_check_evidence or {},
        "reconciliation_reason": reconciliation_reason,
        "final_precheck_summary": precheck_summary,
        "live_precheck": live_precheck,
        "operation_lock": job_record.get("lock_evidence") or lock_result,
        "proxmox_mutation_enabled": response_proxmox_mutation_enabled,
        "proxmox_mutation_may_have_run_previously": not response_proxmox_mutation_enabled and bool(side_effects),
        "corrective_mutation_enabled": False,
        "side_effects": side_effects,
        "needs_reconciliation": status == "needs_reconciliation",
        "reconciliation_events": _list_reconciliation_events(job.job_id),
        "resolved_reconciliation_events": resolved_events,
    }


def execute_drs_migration_job(
    job_id: str,
    *,
    actor: Any,
    inventory_adapter: Any,
    payload: dict[str, Any] | None = None,
    risks: list[Any] | None = None,
    client_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Execute one approved DRS migration job through the narrow live migration path."""
    trusted_actor = _trusted_operator(actor)
    require_drs_live_migration_ack(job_id, payload)
    job, packet = _load_job_and_packet(job_id)
    if _prepared_dispatch_without_upid(job):
        _raise_prepared_dispatch_reentry(job, packet, actor=trusted_actor)

    approval_blockers = _approval_binding_blockers(job, packet)
    if approval_blockers:
        blocked = _record_blocked_attempt(
            job=job,
            packet=packet,
            actor=trusted_actor,
            stage="approval",
            blockers=approval_blockers,
        )
        raise DrsMigrationExecutionError(
            code="DRS_EXECUTION_APPROVAL_BLOCKED",
            message="DRS migration approval packet or job intent is not executable",
            detail=blocked,
        )

    reference = _job_reference(job, packet)
    final_check = build_drs_check_result(
        inventory_adapter,
        job.recommendation_id,
        risks=risks or [],
        payload={"recommendation": reference},
    )
    fresh_blockers = _fresh_check_blockers(final_check, job=job)
    if fresh_blockers:
        blocked = _record_blocked_attempt(
            job=job,
            packet=packet,
            actor=trusted_actor,
            stage="final_precheck",
            blockers=fresh_blockers,
            final_check=final_check,
        )
        raise DrsMigrationExecutionError(
            code="DRS_EXECUTION_FINAL_PRECHECK_BLOCKED",
            message="fresh DRS final pre-check blocked live migration execution",
            detail=blocked,
        )

    client = client_factory() if client_factory is not None else get_default_drs_proxmox_migration_client()
    try:
        live_precheck = client.collect_live_precheck(
            source_node=job.source_node_id,
            target_node=job.target_node_id,
            vmid=job.vmid,
        )
    except DrsProxmoxMigrationError as exc:
        live_precheck = {
            "status": "blocked",
            "blockers": ["proxmox_live_precheck_unavailable"],
            "checks": {
                "proxmox_live_precheck": {
                    "status": "unavailable",
                    "blocker": "proxmox_live_precheck_unavailable",
                    "evidence": {"error": str(exc), "details": exc.details},
                }
            },
        }
    live_blockers = _live_precheck_blockers(live_precheck)
    if live_blockers:
        blocked = _record_blocked_attempt(
            job=job,
            packet=packet,
            actor=trusted_actor,
            stage="final_precheck",
            blockers=live_blockers,
            final_check=final_check,
            live_precheck=live_precheck,
        )
        raise DrsMigrationExecutionError(
            code="DRS_EXECUTION_LIVE_PRECHECK_BLOCKED",
            message="live Proxmox migration evidence blocked execution",
            detail=blocked,
        )

    lock_evidence = {
        "source": "drs_execution",
        "job_id": job.job_id,
        "approval_packet_id": packet.approval_packet_id,
        "recommendation_id": job.recommendation_id,
        "operation": "drs_migration",
        "owner": trusted_actor["username"],
        "vmid": job.vmid,
        "source_node_id": job.source_node_id,
        "target_node_id": job.target_node_id,
    }
    with session_scope() as session:
        lock_result = acquire_drs_operation_locks(
            session,
            cluster_id=job.cluster_id,
            vm_identity_id=job.vm_identity_id,
            vmid=job.vmid,
            source_node_id=job.source_node_id,
            target_node_id=job.target_node_id,
            owner_id=trusted_actor["user_id"],
            reason="drs_migration_execution",
            evidence=lock_evidence,
        )
        if lock_result.get("acquired") is not True:
            session.flush()
    if lock_result.get("acquired") is not True:
        blockers = _dedupe(list(lock_result.get("blockers") or []) or ["operation_lock_active"])
        blocked = _record_blocked_attempt(
            job=job,
            packet=packet,
            actor=trusted_actor,
            stage="operation_lock",
            blockers=blockers,
            final_check=final_check,
            live_precheck=live_precheck,
            lock_result=lock_result,
        )
        raise DrsMigrationExecutionError(
            code="DRS_EXECUTION_LOCK_BLOCKED",
            message="DRS operation lock acquisition blocked execution",
            detail=blocked,
        )

    _mark_dispatch_prepared(
        job=job,
        actor=trusted_actor,
        final_check=final_check,
        live_precheck=live_precheck,
        lock_result=lock_result,
    )
    accepted_side_effects = ["drs_operation_locks_acquired", "proxmox_migrate_invoked"]
    try:
        upid = client.migrate_vm(source_node=job.source_node_id, target_node=job.target_node_id, vmid=job.vmid)
        if not _as_text(upid):
            raise DrsProxmoxMigrationError(
                "Proxmox DRS migrate did not return a UPID",
                details={"source_node": job.source_node_id, "target_node": job.target_node_id, "vmid": job.vmid},
            )
        upid = _as_text(upid)
    except DrsProxmoxMigrationError as exc:
        missing_upid = "UPID" in str(exc).upper()
        task_result = "missing_upid" if missing_upid else "mutation_failed"
        reason = "missing_upid" if missing_upid else "migration_request_failed"
        job_record = _mark_after_lock_uncertainty(
            job_id=job.job_id,
            task_node=job.source_node_id,
            task_result=task_result,
            reason=reason,
            error=exc,
            live_precheck=live_precheck,
            final_check=final_check,
            lock_result=lock_result,
            side_effects=[*accepted_side_effects, "proxmox_upid_missing" if missing_upid else "proxmox_migrate_request_failed"],
        )
        artifact = _write_execution_artifact(job.job_id, {"job": job_record, "error": _compact_error_details(exc.details)})
        job_run = _record_execution_run(job_record=job_record, packet=packet, actor=trusted_actor, artifact=artifact, step_status="blocked")
        return {
            "job": job_record,
            "job_run": job_run,
            "artifact": artifact,
            "status": "needs_reconciliation",
            "reconciliation_reason": reason,
            "proxmox_mutation_enabled": True,
            "side_effects": job_record["side_effects"],
        }

    _mark_dispatch_accepted(
        job=job,
        upid=upid,
        final_check=final_check,
        live_precheck=live_precheck,
        lock_result=lock_result,
        side_effects=accepted_side_effects,
    )

    task_payload: dict[str, Any]
    try:
        task_payload = client.poll_task_status(node=job.source_node_id, upid=upid)
    except DrsProxmoxMigrationError as exc:
        task_payload = {
            "result": "ambiguous",
            "status": {},
            "polls": [],
            "log": [],
            "error": str(exc),
            "details": exc.details,
        }
    return _finish_drs_task_follow_up(
        job=job,
        packet=packet,
        actor=trusted_actor,
        client=client,
        upid=upid,
        task_node=job.source_node_id,
        task_payload=task_payload,
        final_check=final_check,
        live_precheck=live_precheck,
        lock_result=lock_result,
        base_side_effects=[*accepted_side_effects, "proxmox_upid_stored"],
        response_proxmox_mutation_enabled=True,
        evidence_source="drs_execution",
    )


def reconcile_drs_migration_job(
    job_id: str,
    *,
    actor: Any,
    payload: dict[str, Any] | None = None,
    client_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Collect read-only Proxmox evidence and update local DRS reconciliation state."""
    require_drs_reconciliation_ack(job_id, payload)
    trusted_actor = _trusted_operator(actor)
    job, packet = _load_job_and_packet(job_id)
    upid = _as_text(job.proxmox_upid)
    task_node = _as_text(job.proxmox_task_node)
    if _prepared_dispatch_without_upid(job):
        client = client_factory() if client_factory is not None else get_default_drs_proxmox_migration_client()
        post_check = _collect_direct_drs_post_check(
            client=client,
            job=job,
            packet=packet,
            final_check=None,
        )
        return _project_prepared_dispatch_reconciliation(
            job=job,
            packet=packet,
            actor=trusted_actor,
            evidence_source="drs_reconciliation_prepared_without_upid",
            post_check=post_check,
        )
    if not upid or not task_node:
        raise DrsMigrationExecutionError(
            code="DRS_RECONCILIATION_UPID_REQUIRED",
            message="stored Proxmox UPID and task node are required for local DRS reconciliation",
            status_code=409,
            detail={
                "job_id": job_id,
                "proxmox_mutation_enabled": False,
                "proxmox_mutation_may_have_run_previously": False,
                "corrective_mutation_enabled": False,
                "side_effects": [],
            },
        )
    client = client_factory() if client_factory is not None else get_default_drs_proxmox_migration_client()
    try:
        task_payload = client.poll_task_status(node=task_node, upid=upid)
    except DrsProxmoxMigrationError as exc:
        task_payload = {
            "result": "ambiguous",
            "status": {},
            "polls": [],
            "log": [],
            "error": str(exc),
            "details": exc.details,
        }
    return _finish_drs_task_follow_up(
        job=job,
        packet=packet,
        actor=trusted_actor,
        client=client,
        upid=upid,
        task_node=task_node,
        task_payload=task_payload,
        final_check=None,
        live_precheck=dict((job.execution_evidence or {}).get("live_precheck") or {}),
        lock_result=_stored_lock_result(job),
        base_side_effects=list(job.side_effects or []),
        response_proxmox_mutation_enabled=False,
        evidence_source="drs_reconciliation_follow_up",
    )


def build_drs_migration_reconciliation_preview(
    job_id: str,
    *,
    actor: Any,
    client_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Build a read-only reconciliation preview without corrective mutation."""
    trusted_actor = _trusted_operator(actor)
    job, packet = _load_job_and_packet(job_id)
    client = client_factory() if client_factory is not None else get_default_drs_proxmox_migration_client()
    task_status: dict[str, Any] = {}
    task_result = "missing_upid"
    task_error: dict[str, Any] = {}
    if _as_text(job.proxmox_upid) and _as_text(job.proxmox_task_node):
        try:
            raw_status = client.get_task_status(node=_as_text(job.proxmox_task_node), upid=_as_text(job.proxmox_upid))
            task_status = _compact_dict(
                raw_status,
                ("upid", "node", "status", "exitstatus", "type", "id", "user", "starttime", "endtime"),
            )
            task_result = _task_result_from_status(raw_status)
        except Exception as exc:
            task_result = "unknown"
            details = getattr(exc, "details", {})
            task_error = {"error": _as_text(exc), "details": _compact_error_details(details)}

    post_check = _collect_direct_drs_post_check(
        client=client,
        job=job,
        packet=packet,
        final_check=None,
    )
    reconciliation_reason = _as_text(post_check.get("reconciliation_reason"))
    if task_result != "ok":
        reconciliation_reason = {
            "running": "task_running",
            "failed": "task_failed",
            "unknown": "task_unknown",
            "ambiguous": "task_ambiguous",
            "missing_upid": "missing_upid",
        }.get(task_result, "task_ambiguous")
    would_mark_completed = task_result == "ok" and post_check.get("status") == "pass"
    preview_state = "verified_completion_candidate" if would_mark_completed else "needs_reconciliation"
    return {
        "job_id": job.job_id,
        "job_status": job.status,
        "preview_state": preview_state,
        "would_mark_completed": would_mark_completed,
        "read_only": True,
        "proxmox_mutation_enabled": False,
        "corrective_mutation_enabled": False,
        "side_effects": [],
        "allowed_actions": [],
        "proxmox_upid": job.proxmox_upid,
        "task": {
            "result": task_result,
            "status": task_status,
            **task_error,
        },
        "post_check": post_check,
        "reconciliation": {
            "required": not would_mark_completed,
            "reason": None if would_mark_completed else reconciliation_reason,
            "events": _list_reconciliation_events(job.job_id),
        },
        **actor_detail_fields(trusted_actor),
    }
