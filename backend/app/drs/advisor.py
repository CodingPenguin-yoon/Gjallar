"""Execution-closed DRS Advisor recommendation and check calculations.

Recommendation/check output is Proxmox-read-only and keeps
``executable=false`` with no allowed actions. It may persist compact
Gjallar-local identity observation evidence; narrow live migration execution is
separate and only exists through stored approval/job execution gates.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.drs.identity import DEFAULT_CLUSTER_ID, migration_policy_evidence, resolve_inventory_identities
from app.drs.operation_locks import lock_blockers, recommendation_lock_evidence


THRESHOLDS = {
    "hot": 70,
    "critical": 85,
    "source_target_delta": 25,
    "cpu_hot_percent": 70,
    "memory_hot_percent": 70,
    "cpu_critical_percent": 85,
    "memory_critical_percent": 85,
    "source_target_delta_percent": 25,
}
EXPLICIT_TEST_RECOMMENDATION_PREFIX = "drs-rec-explicit-test-vm-"
READ_ONLY_EXECUTION = {
    "available": False,
    "allowed_actions": [],
    "reason": "Recommendation/check output is execution-closed and Proxmox-read-only; use the stored approval/job execute route after fresh gates for narrow execution.",
}
BASE_BLOCKERS = (
    "final_precheck_not_run",
)
LOCAL_STORAGE_TYPES = {"dir", "lvm", "lvmthin", "zfspool", "zfs"}
LOCAL_STORAGE_IDS = {"local", "local-lvm", "local-zfs"}
PASSTHROUGH_TAG_TERMS = ("passthrough", "pci", "gpu", "usb")
AUTHORITY_GJALLAR = "gjallar_operational_gate"
AUTHORITY_PROXMOX = "proxmox_final_technical_gate"
AUTHORITY_ADVISOR = "advisor_prefilter_signal"
ACTION_NONE = "none"


CRITERIA_TAXONOMY = {
    "identity_unknown": {
        "message": "VM identity is not mapped to a stable DRS identity record.",
        "authority": AUTHORITY_GJALLAR,
        "category": "hard_gate",
        "severity": "blocking",
        "evidence_state": "unknown",
        "action_blocked": "approval",
    },
    "metadata_missing": {
        "message": "Required VM metadata/fingerprint records are not available.",
        "authority": AUTHORITY_GJALLAR,
        "category": "hard_gate",
        "severity": "blocking",
        "evidence_state": "unavailable",
        "action_blocked": "approval",
    },
    "policy_unknown": {
        "message": "Placement policy data is not available.",
        "authority": AUTHORITY_GJALLAR,
        "category": "policy_gate",
        "severity": "blocking",
        "evidence_state": "unknown",
        "action_blocked": "approval",
    },
    "final_precheck_not_run": {
        "message": "Final migration precheck has not run.",
        "authority": AUTHORITY_PROXMOX,
        "category": "technical_gate",
        "severity": "blocking",
        "evidence_state": "not_collected",
        "action_blocked": "approval",
    },
    "vm_identity_unknown": {
        "message": "VM identity has no usable stable fingerprint.",
        "authority": AUTHORITY_GJALLAR,
        "category": "hard_gate",
        "severity": "blocking",
        "evidence_state": "unknown",
        "action_blocked": "approval",
    },
    "vm_identity_uncertain": {
        "message": "VM identity evidence is not high confidence.",
        "authority": AUTHORITY_GJALLAR,
        "category": "hard_gate",
        "severity": "blocking",
        "evidence_state": "ambiguous",
        "action_blocked": "approval",
    },
    "vm_identity_mismatch": {
        "message": "Current VM identity does not match the requested DRS identity.",
        "authority": AUTHORITY_GJALLAR,
        "category": "hard_gate",
        "severity": "blocking",
        "evidence_state": "ambiguous",
        "action_blocked": "approval",
    },
    "vm_identity_high": {
        "message": "VM identity evidence is high confidence.",
        "authority": AUTHORITY_GJALLAR,
        "category": "hard_gate",
        "severity": "info",
        "evidence_state": "observed",
        "action_blocked": ACTION_NONE,
    },
    "migration_policy_unknown": {
        "message": "DRS migration policy defaults to unknown.",
        "authority": AUTHORITY_GJALLAR,
        "category": "policy_gate",
        "severity": "blocking",
        "evidence_state": "unknown",
        "action_blocked": "approval",
    },
    "migration_policy_restricted": {
        "message": "DRS migration policy restricts execution for this VM.",
        "authority": AUTHORITY_GJALLAR,
        "category": "policy_gate",
        "severity": "blocking",
        "evidence_state": "observed",
        "action_blocked": "approval",
    },
    "migration_policy_blocked": {
        "message": "DRS migration policy blocks execution for this VM.",
        "authority": AUTHORITY_GJALLAR,
        "category": "policy_gate",
        "severity": "blocking",
        "evidence_state": "observed",
        "action_blocked": "approval",
    },
    "migration_policy_allowed": {
        "message": "DRS migration policy allows local approval when other gates pass.",
        "authority": AUTHORITY_GJALLAR,
        "category": "policy_gate",
        "severity": "info",
        "evidence_state": "observed",
        "action_blocked": ACTION_NONE,
    },
    "drs_final_precheck_failed": {
        "message": "Read-only DRS final pre-check did not pass.",
        "authority": AUTHORITY_GJALLAR,
        "category": "hard_gate",
        "severity": "blocking",
        "evidence_state": "observed",
        "action_blocked": "approval",
    },
    "stale_recommendation": {
        "message": "Current inventory no longer matches the recommendation.",
        "authority": AUTHORITY_GJALLAR,
        "category": "hard_gate",
        "severity": "blocking",
        "evidence_state": "stale",
        "action_blocked": "approval",
    },
    "source_vm_missing": {
        "message": "Source VM is no longer present in current inventory.",
        "authority": AUTHORITY_GJALLAR,
        "category": "hard_gate",
        "severity": "blocking",
        "evidence_state": "unavailable",
        "action_blocked": "approval",
    },
    "source_node_changed": {
        "message": "Source VM is no longer on the recommended source node.",
        "authority": AUTHORITY_GJALLAR,
        "category": "hard_gate",
        "severity": "blocking",
        "evidence_state": "stale",
        "action_blocked": "approval",
    },
    "source_node_not_applicable": {
        "message": "Source-node match is not applicable because source VM evidence is unavailable.",
        "authority": AUTHORITY_GJALLAR,
        "category": "hard_gate",
        "severity": "info",
        "evidence_state": "unavailable",
        "action_blocked": ACTION_NONE,
    },
    "target_node_unavailable": {
        "message": "Recommended target node is unavailable.",
        "authority": AUTHORITY_PROXMOX,
        "category": "technical_gate",
        "severity": "blocking",
        "evidence_state": "unavailable",
        "action_blocked": "approval",
    },
    "vm_state_ineligible": {
        "message": "VM state is not eligible for the current DRS rule set.",
        "authority": AUTHORITY_GJALLAR,
        "category": "hard_gate",
        "severity": "blocking",
        "evidence_state": "observed",
        "action_blocked": "approval",
    },
    "identity_conflict": {
        "message": "Current identity evidence contains a conflict signal.",
        "authority": AUTHORITY_GJALLAR,
        "category": "hard_gate",
        "severity": "blocking",
        "evidence_state": "ambiguous",
        "action_blocked": "approval",
    },
    "route_unknown": {
        "message": "Route, storage, or network evidence is insufficient.",
        "authority": AUTHORITY_ADVISOR,
        "category": "advisory",
        "severity": "warning",
        "evidence_state": "unknown",
        "action_blocked": ACTION_NONE,
    },
    "local_storage_dependency": {
        "message": "VM depends on local-style storage.",
        "authority": AUTHORITY_ADVISOR,
        "category": "advisory",
        "severity": "warning",
        "evidence_state": "observed",
        "action_blocked": ACTION_NONE,
    },
    "passthrough_device_dependency": {
        "message": "VM has passthrough evidence.",
        "authority": AUTHORITY_ADVISOR,
        "category": "advisory",
        "severity": "warning",
        "evidence_state": "observed",
        "action_blocked": ACTION_NONE,
    },
    "target_over_threshold": {
        "message": "Estimated target pressure would reach or exceed the critical threshold.",
        "authority": AUTHORITY_GJALLAR,
        "category": "hard_gate",
        "severity": "blocking",
        "evidence_state": "observed",
        "action_blocked": "approval",
    },
    "operation_lock_active": {
        "message": "An active DRS operation lock matches this VM or route.",
        "authority": AUTHORITY_GJALLAR,
        "category": "hard_gate",
        "severity": "blocking",
        "evidence_state": "observed",
        "action_blocked": "approval",
    },
    "operation_lock_stale": {
        "message": "A stale DRS operation lock matches this VM or route.",
        "authority": AUTHORITY_GJALLAR,
        "category": "hard_gate",
        "severity": "blocking",
        "evidence_state": "stale",
        "action_blocked": "approval",
    },
    "operation_lock_reconciliation_required": {
        "message": "A DRS operation lock requires reconciliation before execution.",
        "authority": AUTHORITY_GJALLAR,
        "category": "hard_gate",
        "severity": "blocking",
        "evidence_state": "observed",
        "action_blocked": "approval",
    },
    "operation_lock_clear": {
        "message": "No active DRS operation lock matched this VM or route.",
        "authority": AUTHORITY_GJALLAR,
        "category": "hard_gate",
        "severity": "info",
        "evidence_state": "observed",
        "action_blocked": ACTION_NONE,
    },
    "vm_config_lock": {
        "message": "The VM has a Proxmox config lock.",
        "authority": AUTHORITY_PROXMOX,
        "category": "technical_gate",
        "severity": "blocking",
        "evidence_state": "observed",
        "action_blocked": "approval",
    },
    "vm_config_lock_clear": {
        "message": "No Proxmox config lock is present in current VM config evidence.",
        "authority": AUTHORITY_PROXMOX,
        "category": "technical_gate",
        "severity": "info",
        "evidence_state": "observed",
        "action_blocked": ACTION_NONE,
    },
    "proxmox_active_task_not_collected": {
        "message": "Proxmox active-task evidence is not collected in recommendation/check output.",
        "authority": AUTHORITY_PROXMOX,
        "category": "technical_gate",
        "severity": "pending",
        "evidence_state": "not_collected",
        "action_blocked": "execute",
    },
    "proxmox_ha_state_not_collected": {
        "message": "Proxmox HA-state evidence is not collected in recommendation/check output.",
        "authority": AUTHORITY_PROXMOX,
        "category": "technical_gate",
        "severity": "pending",
        "evidence_state": "not_collected",
        "action_blocked": "execute",
    },
    "proxmox_cluster_quorum_not_collected": {
        "message": "Proxmox cluster-quorum evidence is not collected in recommendation/check output.",
        "authority": AUTHORITY_PROXMOX,
        "category": "technical_gate",
        "severity": "pending",
        "evidence_state": "not_collected",
        "action_blocked": "execute",
    },
}

ADVISOR_PREFILTER_CODES = (
    "route_unknown",
    "local_storage_dependency",
    "passthrough_device_dependency",
)
PROXMOX_PENDING_TECHNICAL_CODES = (
    "proxmox_active_task_not_collected",
    "proxmox_ha_state_not_collected",
    "proxmox_cluster_quorum_not_collected",
)


def _field(source: Any, *names: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        for name in names:
            if name in source:
                return source[name]
        return default
    for name in names:
        if hasattr(source, name):
            return getattr(source, name)
    return default


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _as_text(value: Any, fallback: str = "") -> str:
    text = str(value if value is not None else "").strip()
    return text or fallback


def _as_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _as_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _normalize_status(value: Any) -> str:
    return _as_text(value, "unknown").lower()


def _unique(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _as_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _safe_segment(value: Any) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", _as_text(value, "unknown")).strip("-") or "unknown"


def explicit_test_recommendation_id(*, vmid: Any, source_node_id: Any, target_node_id: Any) -> str:
    return (
        f"{EXPLICIT_TEST_RECOMMENDATION_PREFIX}"
        f"{_safe_segment(vmid)}-{_safe_segment(source_node_id)}-{_safe_segment(target_node_id)}"
    )


def _parse_explicit_test_recommendation_id(recommendation_id: str) -> dict[str, Any] | None:
    text = _as_text(recommendation_id)
    if not text.startswith(EXPLICIT_TEST_RECOMMENDATION_PREFIX):
        return None
    tail = text.removeprefix(EXPLICIT_TEST_RECOMMENDATION_PREFIX)
    match = re.match(r"(?P<vmid>\d+)(?:-|$)", tail)
    if match is None:
        return None
    return {"vmid": _as_int(match.group("vmid"))}


def _source_label(adapter: Any, snapshot: Any | None) -> str:
    return _as_text(_field(snapshot, "source", default=None) or _field(adapter, "source", default="unknown"), "unknown")


def _snapshot(adapter: Any) -> Any | None:
    if hasattr(adapter, "snapshot"):
        return adapter.snapshot()
    return None


def _adapter_items(adapter: Any, snapshot: Any | None, method_name: str, snapshot_name: str) -> list[Any]:
    if hasattr(adapter, method_name):
        return list(getattr(adapter, method_name)())
    return _as_list(_field(snapshot, snapshot_name, default=[]))


def _storage_id(source: Any) -> str:
    return _as_text(_field(source, "storage_id", "storageId", "storage", "id", default="unknown"), "unknown")


def _node_id(source: Any) -> str:
    return _as_text(_field(source, "node_id", "nodeId", "node", "id", "name", default="unknown"), "unknown")


def _normalize_storage(source: Any) -> dict[str, Any]:
    return {
        "id": _storage_id(source),
        "node_id": _node_id(source),
        "type": _normalize_status(_field(source, "type", default="unknown")),
        "total_gb": _as_float(_field(source, "total_gb", "totalGb", default=0)),
        "free_gb": _as_float(_field(source, "free_gb", "freeGb", default=0)),
    }


def _normalize_network(source: Any) -> dict[str, Any]:
    active_value = _field(source, "active", default=True)
    return {
        "bridge_id": _as_text(_field(source, "bridge_id", "bridgeId", "bridge", "id", default="unknown"), "unknown"),
        "node_id": _node_id(source),
        "active": True if active_value is None else bool(active_value),
        "type": _normalize_status(_field(source, "type", default="bridge")),
        "cidr": _as_text(_field(source, "cidr", default="")),
        "gateway": _as_text(_field(source, "gateway", default="")),
    }


def _normalize_node(source: Any, storages: list[dict[str, Any]], networks: list[dict[str, Any]]) -> dict[str, Any]:
    node_id = _node_id(source)
    inline_storages = [_normalize_storage(item) for item in _as_list(_field(source, "storage", default=[]))]
    inline_networks = [_normalize_network(item) for item in _as_list(_field(source, "networks", default=[]))]
    node_storages = inline_storages or [item for item in storages if item["node_id"] == node_id]
    node_networks = inline_networks or [item for item in networks if item["node_id"] == node_id]
    cpu_usage = _as_float(_field(source, "cpu_usage_percent", "cpuUsagePercent", default=0))
    memory_usage = _as_float(_field(source, "memory_usage_percent", "memoryUsagePercent", default=0))
    return {
        "id": node_id,
        "name": _as_text(_field(source, "display_name", "displayName", "name", default=node_id), node_id),
        "status": _normalize_status(_field(source, "status", default="unknown")),
        "online": _normalize_status(_field(source, "status", default="unknown")) == "online",
        "cpu_usage_percent": cpu_usage,
        "memory_usage_percent": memory_usage,
        "pressure": max(cpu_usage, memory_usage),
        "memory_total_mb": _as_int(_field(source, "memory_total_mb", "memoryTotalMb", default=0)),
        "storage": node_storages,
        "networks": node_networks,
    }


def _disk_storage_ids(vm: Any) -> list[str]:
    return _unique(
        [
            _storage_id(disk)
            for disk in _as_list(_field(vm, "disks", default=[]))
            if _storage_id(disk) != "unknown"
        ]
    )


def _disk_volume_ids(vm: Any) -> list[str]:
    return _unique(
        [
            _field(disk, "volume_id", "volumeId", default="")
            for disk in _as_list(_field(vm, "disks", default=[]))
            if _as_text(_field(disk, "volume_id", "volumeId", default="")).lower() != "unknown"
        ]
    )


def _vm_bridge_ids(vm: Any) -> list[str]:
    evidence = _as_list(_field(vm, "nic_bridge_evidence", "nicBridgeEvidence", default=[]))
    return _unique(
        [
            _field(item, "bridge_id", "bridgeId", "bridge", default="")
            for item in evidence
        ]
    )


def _vm_mac_addresses(vm: Any) -> list[str]:
    direct = _as_list(_field(vm, "mac_addresses", "macAddresses", default=[]))
    nic_macs = [
        _field(item, "mac_address", "macAddress", "mac", default="")
        for item in _as_list(_field(vm, "nic_bridge_evidence", "nicBridgeEvidence", default=[]))
    ]
    return _unique([str(item).strip().lower() for item in [*direct, *nic_macs]])


def _normalize_vm(source: Any) -> dict[str, Any]:
    vmid = _field(source, "vmid", "vm_id", "id", default=0)
    storage_ids = _unique(
        [
            _field(source, "storage_id", "storageId", default=""),
            *_disk_storage_ids(source),
        ]
    )
    return {
        "id": _as_text(vmid, "unknown"),
        "vmid": _as_int(vmid),
        "name": _as_text(_field(source, "name", "vm_name", default=f"vm-{vmid}"), f"vm-{vmid}"),
        "node_id": _as_text(_field(source, "node_id", "nodeId", "node", default="unknown"), "unknown"),
        "status": _normalize_status(_field(source, "status", default="unknown")),
        "template": bool(_field(source, "template", default=False)),
        "cpu": _as_int(_field(source, "cpu", "cpus", default=0)),
        "memory_mb": _as_int(_field(source, "memory_mb", "memoryMb", default=0)),
        "disk_gb": _as_float(_field(source, "disk_gb", "diskGb", default=0)),
        "storage_ids": storage_ids,
        "disk_volume_ids": _disk_volume_ids(source),
        "bridge_ids": _vm_bridge_ids(source),
        "smbios1": _as_text(_field(source, "smbios1", default="")),
        "vmgenid": _as_text(_field(source, "vmgenid", default="")),
        "mac_addresses": _vm_mac_addresses(source),
        "config_lock": _as_text(_field(source, "config_lock", "configLock", default="")),
        "tags": _unique(_as_list(_field(source, "tags", default=[]))),
        "raw": source,
    }


def _risk_level(risk: Any) -> str:
    return _normalize_status(_field(risk, "level", "risk_level", "riskLevel", default="unknown"))


def _risk_fields(risk: Any) -> list[str]:
    detail = _field(risk, "detail", "details", default={})
    values = [
        _field(risk, "vmid", "vm_id", "target_vmid", "target_id", "targetId", default=""),
        _field(risk, "resource_id", "resourceId", "vm_name", "target_name", default=""),
        _field(detail, "vmid", "vm_id", "target_vmid", "target_id", "vm_name", "node_id", default=""),
    ]
    return [_as_text(value) for value in values if _as_text(value)]


def _risk_targets_vm(risk: Any, vm: dict[str, Any]) -> bool:
    candidates = {_as_text(vm["vmid"]), vm["id"], vm["name"]}
    for field in _risk_fields(risk):
        if field in candidates or field.endswith(f":{vm['name']}") or field.endswith(f"/{vm['name']}"):
            return True
    return False


def _has_red_risk(vm: dict[str, Any], risks: list[Any]) -> bool:
    return any(_risk_level(risk) == "red" and _risk_targets_vm(risk, vm) for risk in risks)


def _is_local_storage_id(storage_id: str) -> bool:
    normalized = storage_id.strip().lower()
    return normalized in LOCAL_STORAGE_IDS or normalized.startswith("local-")


def _storage_records_for_ids(storage_ids: list[str], nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    wanted = set(storage_ids)
    for node in nodes:
        for storage in node["storage"]:
            if storage["id"] in wanted:
                records.append(storage)
    return records


def _local_storage_evidence(vm: dict[str, Any], nodes: list[dict[str, Any]]) -> dict[str, Any]:
    records = _storage_records_for_ids(vm["storage_ids"], nodes)
    local_ids = [
        storage_id
        for storage_id in vm["storage_ids"]
        if _is_local_storage_id(storage_id)
    ]
    local_types = [
        record["type"]
        for record in records
        if record["type"] in LOCAL_STORAGE_TYPES
    ]
    return {
        "blocked": bool(local_ids or local_types),
        "authority": AUTHORITY_ADVISOR,
        "category": "advisory",
        "severity": "warning" if local_ids or local_types else "info",
        "evidence_state": "observed",
        "action_blocked": ACTION_NONE,
        "storage_ids": vm["storage_ids"],
        "local_storage_ids": _unique(local_ids),
        "local_storage_types": _unique(local_types),
    }


def _passthrough_evidence(vm: dict[str, Any]) -> dict[str, Any]:
    matched = []
    for tag in vm["tags"]:
        normalized = tag.lower()
        if any(term in normalized for term in PASSTHROUGH_TAG_TERMS):
            matched.append(tag)
    return {
        "blocked": bool(matched),
        "authority": AUTHORITY_ADVISOR,
        "category": "advisory",
        "severity": "warning" if matched else "info",
        "evidence_state": "observed",
        "action_blocked": ACTION_NONE,
        "matched_tags": _unique(matched),
        "method": "tags_only",
        "limitation": "Current passthrough detection uses VM tags only; Proxmox device config parsing is not yet included.",
    }


def _route_evidence(vm: dict[str, Any], source_node: dict[str, Any], target_node: dict[str, Any]) -> dict[str, Any]:
    source_bridge_ids = {
        network["bridge_id"]
        for network in source_node["networks"]
        if network["active"] and network["bridge_id"] != "unknown"
    }
    target_bridge_ids = {
        network["bridge_id"]
        for network in target_node["networks"]
        if network["active"] and network["bridge_id"] != "unknown"
    }
    vm_bridge_ids = set(vm["bridge_ids"])
    target_storage_ids = {storage["id"] for storage in target_node["storage"]}
    vm_storage_ids = set(vm["storage_ids"])
    matching_bridges = sorted(vm_bridge_ids & target_bridge_ids)
    source_bridge_present = not vm_bridge_ids or bool(vm_bridge_ids & source_bridge_ids)
    network_sufficient = bool(vm_bridge_ids) and source_bridge_present and vm_bridge_ids.issubset(target_bridge_ids)
    storage_sufficient = bool(vm_storage_ids) and vm_storage_ids.issubset(target_storage_ids)
    if storage_sufficient and vm["disk_gb"] > 0:
        matching_target_storages = [
            storage for storage in target_node["storage"] if storage["id"] in vm_storage_ids
        ]
        storage_sufficient = any(storage["free_gb"] >= vm["disk_gb"] for storage in matching_target_storages)
    return {
        "blocked": not (network_sufficient and storage_sufficient),
        "authority": AUTHORITY_ADVISOR,
        "category": "advisory",
        "severity": "warning" if not (network_sufficient and storage_sufficient) else "info",
        "evidence_state": "observed" if network_sufficient and storage_sufficient else "unknown",
        "action_blocked": ACTION_NONE,
        "network_evidence_sufficient": network_sufficient,
        "storage_evidence_sufficient": storage_sufficient,
        "vm_bridge_ids": sorted(vm_bridge_ids),
        "source_bridge_ids": sorted(source_bridge_ids),
        "target_bridge_ids": sorted(target_bridge_ids),
        "matching_target_bridge_ids": matching_bridges,
        "vm_storage_ids": sorted(vm_storage_ids),
        "target_storage_ids": sorted(target_storage_ids),
    }


def _criterion_detail(
    code: str,
    *,
    status: str | None = None,
    severity: str | None = None,
    evidence_state: str | None = None,
    blocking: bool | None = None,
    action_blocked: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    taxonomy = CRITERIA_TAXONOMY.get(code, {})
    detail = {
        "code": code,
        "message": taxonomy.get("message", code),
        "authority": taxonomy.get("authority", AUTHORITY_GJALLAR),
        "category": taxonomy.get("category", "hard_gate"),
        "severity": severity or taxonomy.get("severity", "blocking"),
        "evidence_state": evidence_state or taxonomy.get("evidence_state", "observed"),
        "action_blocked": action_blocked if action_blocked is not None else taxonomy.get("action_blocked", "approval"),
    }
    detail["blocking"] = blocking if blocking is not None else detail["action_blocked"] != ACTION_NONE and detail["severity"] == "blocking"
    detail["status"] = status or ("blocked" if detail["blocking"] else "advisory")
    if evidence is not None:
        detail["evidence"] = evidence
    return detail


def _blocker_detail(code: str) -> dict[str, Any]:
    detail = _criterion_detail(code, status="blocked")
    if detail["action_blocked"] == ACTION_NONE:
        detail["action_blocked"] = "approval"
    detail["severity"] = "blocking"
    detail["blocking"] = True
    return detail


def _advisory_signal(code: str, *, active: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    taxonomy = CRITERIA_TAXONOMY[code]
    return _criterion_detail(
        code,
        status="warning" if active else "pass",
        severity=taxonomy["severity"] if active else "info",
        evidence_state=taxonomy["evidence_state"] if active else "observed",
        blocking=False,
        action_blocked=ACTION_NONE,
        evidence=evidence,
    )


def _proxmox_pending_technical_criteria() -> list[dict[str, Any]]:
    return [
        _criterion_detail(code, status="not_collected", blocking=False)
        for code in PROXMOX_PENDING_TECHNICAL_CODES
    ]


def _technical_gate_status(criteria: list[dict[str, Any]]) -> dict[str, Any]:
    technical = [
        item
        for item in criteria
        if item.get("authority") == AUTHORITY_PROXMOX and item.get("category") == "technical_gate"
    ]
    observed_blockers = [
        item
        for item in technical
        if item.get("blocking") is True and item.get("evidence_state") != "not_collected"
    ]
    if observed_blockers:
        status = "blocked"
    elif any(item.get("evidence_state") == "not_collected" for item in technical):
        status = "not_collected"
    elif technical:
        status = "pass"
    else:
        status = "unknown"
    evidence_state = "not_collected" if status == "not_collected" else "observed" if status in {"blocked", "pass"} else "unknown"
    return {
        "authority": AUTHORITY_PROXMOX,
        "category": "technical_gate",
        "status": status,
        "evidence_state": evidence_state,
        "action_blocked": "execute" if status in {"blocked", "not_collected", "unknown"} else ACTION_NONE,
        "criteria": [item["code"] for item in technical],
    }


def _criteria_summary(
    *,
    blockers: list[str],
    advisory_signals: list[dict[str, Any]] | None = None,
    extra: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    details = [
        *_blocker_details(blockers),
        *(advisory_signals or []),
        *(extra or []),
    ]
    hard_gate_blockers = [item["code"] for item in details if item.get("blocking") is True]
    advisory_codes = [item["code"] for item in details if item.get("authority") == AUTHORITY_ADVISOR]
    technical_status = _technical_gate_status(details)
    return (
        {
            "hard_gate_blockers": hard_gate_blockers,
            "advisory_signal_codes": advisory_codes,
            "technical_gate_status": technical_status["status"],
            "authorities": sorted({_as_text(item.get("authority")) for item in details if item.get("authority")}),
        },
        details,
        technical_status,
    )


def _blocker_details(blockers: list[str]) -> list[dict[str, Any]]:
    return [_blocker_detail(code) for code in blockers]


def _unsupported_proxmox_evidence(name: str) -> dict[str, Any]:
    return {
        "status": "not_collected",
        "blocking": False,
        "authority": AUTHORITY_PROXMOX,
        "category": "technical_gate",
        "severity": "pending",
        "evidence_state": "not_collected",
        "action_blocked": "execute",
        "source": "inventory_adapter",
        "detail": f"{name} evidence is not collected by the current read-only inventory adapter.",
    }


def _proxmox_conflict_evidence(source_vm: dict[str, Any] | None) -> dict[str, Any]:
    config_lock = _as_text((source_vm or {}).get("config_lock"))
    config_lock_evidence = {
        "status": "conflict" if config_lock else "pass",
        "blocking": bool(config_lock),
        "authority": AUTHORITY_PROXMOX,
        "category": "technical_gate",
        "severity": "blocking" if config_lock else "info",
        "evidence_state": "observed",
        "action_blocked": "approval" if config_lock else ACTION_NONE,
        "source": "vm_config.lock",
        "lock": config_lock,
    }
    return {
        "blocking": config_lock_evidence["blocking"],
        "config_lock": config_lock_evidence,
        "active_task": _unsupported_proxmox_evidence("active task"),
        "ha_state": _unsupported_proxmox_evidence("HA state"),
        "cluster_quorum": _unsupported_proxmox_evidence("cluster health/quorum"),
    }


def _proxmox_conflict_status(conflicts: dict[str, Any]) -> str:
    if conflicts.get("blocking") is True:
        return "failed"
    unsupported = ("active_task", "ha_state", "cluster_quorum")
    if any(_as_text(conflicts.get(name, {}).get("status")) in {"not_collected", "not_implemented"} for name in unsupported):
        return "not_collected"
    return "pass"


def _default_identity_evidence(vm: dict[str, Any], *, cluster_id: str, source: str) -> dict[str, Any]:
    return {
        "vm_identity_id": None,
        "stable_fingerprint": "",
        "match_confidence": "unknown",
        "match_reason": "identity_resolution_not_available",
        "identity_status": "unknown",
        "fingerprint_components": {
            "smbios1_uuid": "",
            "vmgenid": "",
            "mac_addresses": vm.get("mac_addresses", []),
            "disk_volume_ids": vm.get("disk_volume_ids", []),
            "locator": {
                "cluster_id": cluster_id,
                "node_id": vm["node_id"],
                "vmid": vm["vmid"],
                "name": vm["name"],
            },
        },
        "source": source,
        "conflict_signal": False,
        "blocking": True,
    }


def _default_policy_evidence(identity_evidence: dict[str, Any]) -> dict[str, Any]:
    reason = "VM identity must resolve with high confidence before DRS can evaluate migration policy."
    if identity_evidence.get("match_confidence") == "high":
        reason = "No DRS migration policy has been recorded for this VM identity."
    return {
        "policy_id": None,
        "vm_identity_id": identity_evidence.get("vm_identity_id"),
        "policy": "unknown",
        "source": "default",
        "reason": reason,
        "updated_by": None,
    }


def _identity_policy_blockers(
    identity_evidence: dict[str, Any],
    policy_evidence: dict[str, Any],
) -> list[str]:
    confidence = _as_text(identity_evidence.get("match_confidence"), "unknown")
    conflict = identity_evidence.get("conflict_signal") is True
    blockers: list[str] = []
    if confidence == "high" and not conflict:
        policy = _as_text(policy_evidence.get("policy"), "unknown")
        if policy == "unknown":
            blockers.extend(["migration_policy_unknown", "policy_unknown"])
        elif policy == "restricted":
            blockers.append("migration_policy_restricted")
        elif policy == "blocked":
            blockers.append("migration_policy_blocked")
        return blockers
    if confidence == "unknown":
        blockers.extend(["vm_identity_unknown", "identity_unknown", "metadata_missing"])
    else:
        blockers.extend(["vm_identity_uncertain", "metadata_missing"])
    if conflict:
        blockers.append("identity_conflict")
    return blockers


def _cluster_id(adapter: Any, snapshot: Any | None) -> str:
    connection = _field(snapshot, "connection", default={})
    return _as_text(
        _field(connection, "cluster_id", "clusterId", default=None)
        or _field(adapter, "cluster_id", "clusterId", default=None),
        DEFAULT_CLUSTER_ID,
    )


def _estimate_pressure_effect(vm: dict[str, Any], source_node: dict[str, Any]) -> float:
    running_count = max(_as_int(source_node.get("running_vm_count"), 1), 1)
    vm_count_share = source_node["pressure"] / running_count
    memory_share = 0.0
    if source_node["memory_total_mb"] > 0:
        memory_share = (vm["memory_mb"] / source_node["memory_total_mb"]) * 100
    return max(4.0, min(18.0, max(vm_count_share, memory_share)))


def _with_vm_counts(nodes: list[dict[str, Any]], vms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for node in nodes:
        node_vms = [vm for vm in vms if vm["node_id"] == node["id"]]
        result.append(
            {
                **node,
                "running_vm_count": len([vm for vm in node_vms if vm["status"] == "running" and not vm["template"]]),
                "total_vm_count": len(node_vms),
            }
        )
    return result


def _candidate_reason(source_node: dict[str, Any], target_node: dict[str, Any]) -> str:
    source_state = "critical" if source_node["pressure"] >= THRESHOLDS["critical"] else "hot"
    return (
        f"Source node is {source_state} and target pressure is lower by "
        f"{round(source_node['pressure'] - target_node['pressure'])}%."
    )


def _build_recommendation(
    *,
    vm: dict[str, Any],
    source_node: dict[str, Any],
    target_node: dict[str, Any],
    nodes: list[dict[str, Any]],
    identity_evidence: dict[str, Any],
    policy_evidence: dict[str, Any],
) -> dict[str, Any]:
    route = _route_evidence(vm, source_node, target_node)
    local_storage = _local_storage_evidence(vm, nodes)
    passthrough = _passthrough_evidence(vm)
    pressure_effect = _estimate_pressure_effect(vm, source_node)
    target_pressure_after = min(100, target_node["pressure"] + pressure_effect)
    target_over_threshold = target_pressure_after >= THRESHOLDS["critical"]
    blockers = [
        *_identity_policy_blockers(identity_evidence, policy_evidence),
        *BASE_BLOCKERS,
        "target_over_threshold" if target_over_threshold else "",
    ]
    blockers = _unique([code for code in blockers if code])
    advisory_signals = [
        _advisory_signal("route_unknown", active=route["blocked"], evidence=route),
        _advisory_signal("local_storage_dependency", active=local_storage["blocked"], evidence=local_storage),
        _advisory_signal("passthrough_device_dependency", active=passthrough["blocked"], evidence=passthrough),
    ]
    criteria, criteria_details, technical_gate_status = _criteria_summary(
        blockers=blockers,
        advisory_signals=advisory_signals,
        extra=_proxmox_pending_technical_criteria(),
    )
    delta = source_node["pressure"] - target_node["pressure"]
    return {
        "id": f"drs-rec-vm-{_safe_segment(vm['vmid'])}-{_safe_segment(source_node['id'])}-{_safe_segment(target_node['id'])}",
        "type": "vm_migration_advice",
        "status": "blocked",
        "risk_level": "yellow",
        "vmid": vm["vmid"],
        "vm_name": vm["name"],
        "source_node_id": source_node["id"],
        "source_node_name": source_node["name"],
        "target_node_id": target_node["id"],
        "target_node_name": target_node["name"],
        "reason": _candidate_reason(source_node, target_node),
        "thresholds": dict(THRESHOLDS),
        "blockers": blockers,
        "blocker_details": _blocker_details(blockers),
        "criteria": criteria,
        "criteria_details": criteria_details,
        "advisory_signals": advisory_signals,
        "technical_gate_status": technical_gate_status,
        "identity_evidence": identity_evidence,
        "policy_evidence": policy_evidence,
        "estimated_effect": {
            "source_pressure_before": round(source_node["pressure"], 2),
            "target_pressure_before": round(target_node["pressure"], 2),
            "source_pressure_after": round(max(0, source_node["pressure"] - pressure_effect), 2),
            "target_pressure_after": round(target_pressure_after, 2),
            "source_target_delta": round(delta, 2),
        },
        "evidence": {
            "candidate_filter": {
                "running": True,
                "template": False,
                "red_risk_excluded": False,
            },
            "source": {
                "cpu_usage_percent": source_node["cpu_usage_percent"],
                "memory_usage_percent": source_node["memory_usage_percent"],
                "pressure_percent": source_node["pressure"],
            },
            "target": {
                "cpu_usage_percent": target_node["cpu_usage_percent"],
                "memory_usage_percent": target_node["memory_usage_percent"],
                "pressure_percent": target_node["pressure"],
            },
            "route": route,
            "storage": local_storage,
            "passthrough": passthrough,
            "identity": identity_evidence,
            "policy": policy_evidence,
            "target_over_threshold": {
                "blocked": target_over_threshold,
                "critical_threshold": THRESHOLDS["critical"],
                "projected_target_pressure_percent": round(target_pressure_after, 2),
            },
        },
        "read_only": True,
        "executable": False,
        "allowed_actions": [],
        "execution": dict(READ_ONLY_EXECUTION),
    }


def _identity_evidence_for_vm(
    vm: dict[str, Any],
    identity_map: dict[tuple[str, int], Any],
    *,
    cluster_id: str,
    source: str,
) -> dict[str, Any]:
    resolution = identity_map.get((vm["node_id"], vm["vmid"]))
    if resolution is None:
        return _default_identity_evidence(vm, cluster_id=cluster_id, source=source)
    return resolution.to_evidence()


def _policy_evidence_for_identity(identity_evidence: dict[str, Any]) -> dict[str, Any]:
    if identity_evidence.get("match_confidence") != "high" or identity_evidence.get("conflict_signal") is True:
        return _default_policy_evidence(identity_evidence)
    return migration_policy_evidence(identity_evidence)


def _explicit_reference_from_current_nodes(
    *,
    recommendation_id: str,
    vmid: int,
    nodes: list[dict[str, Any]],
) -> dict[str, Any]:
    for source_node in nodes:
        for target_node in nodes:
            if source_node["id"] == target_node["id"]:
                continue
            if explicit_test_recommendation_id(
                vmid=vmid,
                source_node_id=source_node["id"],
                target_node_id=target_node["id"],
            ) == recommendation_id:
                return {
                    "vmid": vmid,
                    "source_node_id": source_node["id"],
                    "target_node_id": target_node["id"],
                }
    return {"vmid": vmid}


def _explicit_test_reference(
    calculated: dict[str, Any],
    recommendation_id: str,
    payload_reference: dict[str, Any],
) -> dict[str, Any]:
    parsed = _parse_explicit_test_recommendation_id(recommendation_id)
    if parsed is None:
        return {}
    reference = dict(parsed)
    for key in ("vm_identity_id", "vmid", "vm_name", "source_node_id", "target_node_id"):
        if key in payload_reference:
            reference[key] = payload_reference[key]
    if reference.get("source_node_id") and reference.get("target_node_id"):
        return reference
    vmid = _as_int(reference.get("vmid"), 0)
    if vmid <= 0:
        return reference
    current = _explicit_reference_from_current_nodes(
        recommendation_id=recommendation_id,
        vmid=vmid,
        nodes=calculated["nodes"],
    )
    return {**current, **{key: value for key, value in reference.items() if value not in {"", 0}}}


def _synthesize_explicit_test_recommendation(
    calculated: dict[str, Any],
    recommendation_id: str,
    reference: dict[str, Any],
) -> dict[str, Any] | None:
    if not _parse_explicit_test_recommendation_id(recommendation_id):
        return None
    vmid = _as_int(reference.get("vmid"), 0)
    source_node_id = _as_text(reference.get("source_node_id"))
    target_node_id = _as_text(reference.get("target_node_id"))
    if vmid <= 0 or not source_node_id or not target_node_id:
        return None
    if explicit_test_recommendation_id(
        vmid=vmid,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
    ) != recommendation_id:
        return None

    source_node = next((node for node in calculated["nodes"] if node["id"] == source_node_id), None)
    target_node = next((node for node in calculated["nodes"] if node["id"] == target_node_id), None)
    vm = next((item for item in calculated["vms"] if item["vmid"] == vmid), None)
    if source_node is None or target_node is None or vm is None:
        return None
    if vm["node_id"] != source_node["id"]:
        return None
    if not (source_node["online"] and source_node["pressure"] >= THRESHOLDS["hot"]):
        return None
    if not (
        target_node["online"]
        and target_node["id"] != source_node["id"]
        and source_node["pressure"] - target_node["pressure"] >= THRESHOLDS["source_target_delta"]
    ):
        return None
    if not (vm["status"] == "running" and not vm["template"] and not _has_red_risk(vm, calculated["risks"])):
        return None

    identity_evidence = _identity_evidence_for_vm(
        vm,
        calculated["identity_map"],
        cluster_id=calculated["cluster_id"],
        source=calculated["source"],
    )
    policy_evidence = _policy_evidence_for_identity(identity_evidence)
    recommendation = _build_recommendation(
        vm=vm,
        source_node=source_node,
        target_node=target_node,
        nodes=calculated["nodes"],
        identity_evidence=identity_evidence,
        policy_evidence=policy_evidence,
    )
    recommendation["id"] = recommendation_id
    recommendation["explicit_test_candidate"] = True
    recommendation["evidence"]["candidate_filter"] = {
        **recommendation["evidence"]["candidate_filter"],
        "explicit_test_candidate": True,
        "normal_top3_shortlist_bypassed": True,
    }
    return recommendation


def _build_recommendations(
    nodes: list[dict[str, Any]],
    vms: list[dict[str, Any]],
    risks: list[Any],
    *,
    identity_map: dict[tuple[str, int], Any],
    cluster_id: str,
    source: str,
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    sources = sorted(
        [node for node in nodes if node["online"] and node["pressure"] >= THRESHOLDS["hot"]],
        key=lambda node: (-node["pressure"], node["name"]),
    )
    for source_node in sources:
        target_candidates = [
            node
            for node in nodes
            if node["online"]
            and node["id"] != source_node["id"]
            and source_node["pressure"] - node["pressure"] >= THRESHOLDS["source_target_delta"]
        ]
        if not target_candidates:
            continue
        target_node = sorted(target_candidates, key=lambda node: (node["pressure"], node["name"]))[0]
        source_vms = [
            vm
            for vm in vms
            if vm["node_id"] == source_node["id"]
            and vm["status"] == "running"
            and not vm["template"]
            and not _has_red_risk(vm, risks)
        ]
        for vm in sorted(source_vms, key=lambda item: (-item["memory_mb"], -item["disk_gb"], item["name"]))[:3]:
            identity_evidence = _identity_evidence_for_vm(
                vm,
                identity_map,
                cluster_id=cluster_id,
                source=source,
            )
            policy_evidence = _policy_evidence_for_identity(identity_evidence)
            recommendations.append(
                _build_recommendation(
                    vm=vm,
                    source_node=source_node,
                    target_node=target_node,
                    nodes=nodes,
                    identity_evidence=identity_evidence,
                    policy_evidence=policy_evidence,
                )
            )
    return sorted(
        recommendations,
        key=lambda item: (-item["estimated_effect"]["source_target_delta"], item["vm_name"]),
    )[:10]


def _cluster_state(nodes: list[dict[str, Any]], recommendations: list[dict[str, Any]]) -> str:
    if any(node["pressure"] >= THRESHOLDS["critical"] for node in nodes):
        return "critical"
    if recommendations or any(node["pressure"] >= THRESHOLDS["hot"] for node in nodes):
        return "hot"
    return "balanced"


def _summary(nodes: list[dict[str, Any]], vms: list[dict[str, Any]], risks: list[Any], recommendations: list[dict[str, Any]]) -> dict[str, Any]:
    running_non_template = [vm for vm in vms if vm["status"] == "running" and not vm["template"]]
    excluded_red = [vm for vm in running_non_template if _has_red_risk(vm, risks)]
    online_nodes = [node for node in nodes if node["online"]]
    pressures = [node["pressure"] for node in online_nodes]
    pressure_delta = max(pressures) - min(pressures) if len(pressures) >= 2 else 0
    return {
        "cluster_state": _cluster_state(nodes, recommendations),
        "total_nodes": len(nodes),
        "online_nodes": len(online_nodes),
        "total_vms": len(vms),
        "running_candidate_vms": len(running_non_template),
        "excluded_red_risk_vms": len(excluded_red),
        "recommendation_count": len(recommendations),
        "hot_node_count": len([node for node in online_nodes if node["pressure"] >= THRESHOLDS["hot"]]),
        "critical_node_count": len([node for node in online_nodes if node["pressure"] >= THRESHOLDS["critical"]]),
        "source_target_delta": round(pressure_delta, 2),
        "thresholds": dict(THRESHOLDS),
        "read_only": True,
        "executable": False,
        "execution": dict(READ_ONLY_EXECUTION),
    }


def _calculate_drs_model(adapter: Any, *, risks: list[Any] | None = None) -> dict[str, Any]:
    snapshot = _snapshot(adapter)
    source = _source_label(adapter, snapshot)
    cluster_id = _cluster_id(adapter, snapshot)
    observed_at = _as_text(_field(snapshot, "observed_at", default=""))
    storages = [_normalize_storage(item) for item in _adapter_items(adapter, snapshot, "list_storage", "storage")]
    networks = [_normalize_network(item) for item in _adapter_items(adapter, snapshot, "list_networks", "networks")]
    nodes = [
        _normalize_node(item, storages, networks)
        for item in _adapter_items(adapter, snapshot, "list_nodes", "nodes")
    ]
    vms = [
        _normalize_vm(item)
        for item in _adapter_items(adapter, snapshot, "list_vms", "vms")
    ]
    nodes = _with_vm_counts(nodes, vms)
    risk_items = list(risks or [])
    identity_map = resolve_inventory_identities(
        vms,
        cluster_id=cluster_id,
        observed_at=_field(snapshot, "observed_at", default=None),
        source=source,
    )
    recommendations = _build_recommendations(
        nodes,
        vms,
        risk_items,
        identity_map=identity_map,
        cluster_id=cluster_id,
        source=source,
    )
    summary = _summary(nodes, vms, risk_items, recommendations)
    model = {
        "summary": summary,
        "recommendations": recommendations,
        "thresholds": dict(THRESHOLDS),
        "read_only": True,
        "executable": False,
        "allowed_actions": [],
        "execution": dict(READ_ONLY_EXECUTION),
        "evidence": {
            "source": source,
            "cluster_id": cluster_id,
            "observed_at": observed_at,
            "candidate_filter": "running_non_template_vms_without_red_risk",
            "passthrough_detection": "tags_only",
        },
    }
    return {
        "model": model,
        "nodes": nodes,
        "vms": vms,
        "risks": risk_items,
        "identity_map": identity_map,
        "cluster_id": cluster_id,
        "source": source,
        "observed_at": observed_at,
    }


def build_drs_advisor_model(adapter: Any, *, risks: list[Any] | None = None) -> dict[str, Any]:
    """Return a read-only DRS Advisor model from current inventory evidence."""
    return _calculate_drs_model(adapter, risks=risks)["model"]


def find_drs_recommendation(
    adapter: Any,
    recommendation_id: str,
    *,
    risks: list[Any] | None = None,
) -> dict[str, Any] | None:
    model = build_drs_advisor_model(adapter, risks=risks)
    for recommendation in model["recommendations"]:
        if recommendation["id"] == recommendation_id:
            return recommendation
    return None


def _payload_reference(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    source = payload.get("recommendation")
    if not isinstance(source, dict):
        source = payload
    source_identity = source.get("identity_evidence") if isinstance(source.get("identity_evidence"), dict) else {}
    fields = {
        "id": _as_text(source.get("id") or payload.get("recommendation_id") or payload.get("recommendationId")),
        "vm_identity_id": _as_text(
            source.get("vm_identity_id")
            or source.get("vmIdentityId")
            or source_identity.get("vm_identity_id")
            or payload.get("vm_identity_id")
            or payload.get("vmIdentityId")
        ),
        "vmid": _as_int(source.get("vmid"), 0),
        "vm_name": _as_text(source.get("vm_name") or source.get("vmName")),
        "source_node_id": _as_text(source.get("source_node_id") or source.get("sourceNodeId")),
        "target_node_id": _as_text(source.get("target_node_id") or source.get("targetNodeId")),
    }
    return {key: value for key, value in fields.items() if value not in {"", 0}}


def _reference_value(reference: dict[str, Any], key: str, fallback: Any = None) -> Any:
    return reference.get(key, fallback)


def _matching_reference(current: dict[str, Any], reference: dict[str, Any]) -> bool:
    current_identity = current.get("identity_evidence") if isinstance(current.get("identity_evidence"), dict) else {}
    for key in ("vmid", "source_node_id", "target_node_id"):
        if key in reference and _reference_value(current, key) != reference[key]:
            return False
    if "vm_identity_id" in reference and _as_text(current_identity.get("vm_identity_id")) != _as_text(reference["vm_identity_id"]):
        return False
    return True


def _check_item(
    status: str,
    *,
    blocker: str | None = None,
    detail: str = "",
    evidence: dict[str, Any] | None = None,
    criterion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": status}
    if blocker:
        payload["blocker"] = blocker
    if detail:
        payload["detail"] = detail
    if evidence is not None:
        payload["evidence"] = evidence
    if criterion is not None:
        payload["criterion"] = criterion
    return payload


def build_drs_check_result(
    adapter: Any,
    recommendation_id: str,
    *,
    risks: list[Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    calculated = _calculate_drs_model(adapter, risks=risks)
    model = calculated["model"]
    payload_reference = _payload_reference(payload)
    explicit_reference = _explicit_test_reference(calculated, recommendation_id, payload_reference)
    recommendation = next(
        (item for item in model["recommendations"] if item["id"] == recommendation_id),
        None,
    )
    if recommendation is None and explicit_reference:
        recommendation = _synthesize_explicit_test_recommendation(
            calculated,
            recommendation_id,
            explicit_reference,
        )
    reference = recommendation or explicit_reference or payload_reference
    checked_at = datetime.now(timezone.utc).isoformat()

    vms = calculated["vms"]
    nodes = calculated["nodes"]
    identity_map = calculated["identity_map"]
    source_vm = None
    if reference.get("vmid") is not None:
        source_vm = next((vm for vm in vms if vm["vmid"] == _as_int(reference.get("vmid"))), None)
    target_node = next(
        (node for node in nodes if node["id"] == _as_text(reference.get("target_node_id"))),
        None,
    )
    identity_evidence = {}
    policy_evidence = {}
    if recommendation is not None:
        identity_evidence = dict(recommendation.get("identity_evidence") or {})
        policy_evidence = dict(recommendation.get("policy_evidence") or {})
    elif source_vm is not None:
        identity_evidence = _identity_evidence_for_vm(
            source_vm,
            identity_map,
            cluster_id=calculated["cluster_id"],
            source=calculated["source"],
        )
        policy_evidence = _policy_evidence_for_identity(identity_evidence)
    else:
        identity_evidence = _default_identity_evidence(
            {
                "node_id": _as_text(reference.get("source_node_id"), "unknown"),
                "vmid": _as_int(reference.get("vmid"), 0),
                "name": _as_text(reference.get("vm_name"), "unknown"),
                "mac_addresses": [],
                "disk_volume_ids": [],
            },
            cluster_id=calculated["cluster_id"],
            source=calculated["source"],
        )
        policy_evidence = _default_policy_evidence(identity_evidence)

    stale = recommendation is None or (bool(payload_reference) and recommendation is not None and not _matching_reference(recommendation, payload_reference))
    source_exists = source_vm is not None
    source_node_matches = bool(
        source_vm is not None
        and reference.get("source_node_id")
        and source_vm["node_id"] == _as_text(reference.get("source_node_id"))
    )
    target_eligible = bool(target_node and target_node["online"])
    vm_state_eligible = bool(
        source_vm is not None
        and source_vm["status"] == "running"
        and not source_vm["template"]
        and not _has_red_risk(source_vm, calculated["risks"])
    )
    route = recommendation.get("evidence", {}).get("route", {}) if recommendation else {}
    storage = recommendation.get("evidence", {}).get("storage", {}) if recommendation else {}
    passthrough = recommendation.get("evidence", {}).get("passthrough", {}) if recommendation else {}
    target_threshold = recommendation.get("evidence", {}).get("target_over_threshold", {}) if recommendation else {}
    route_ok = bool(
        recommendation is not None
        and route.get("blocked") is not True
        and route.get("network_evidence_sufficient") is True
        and route.get("storage_evidence_sufficient") is True
    )
    advisory_signals = [
        _advisory_signal("route_unknown", active=not route_ok, evidence=route),
        _advisory_signal("local_storage_dependency", active=storage.get("blocked") is True, evidence=storage),
        _advisory_signal("passthrough_device_dependency", active=passthrough.get("blocked") is True, evidence=passthrough),
    ]
    current_rule_blockers = [
        blocker
        for blocker in (recommendation or {}).get("blockers", [])
        if blocker
        not in {
            "final_precheck_not_run",
            "migration_policy_unknown",
            "policy_unknown",
            "migration_policy_restricted",
            "migration_policy_blocked",
            "vm_identity_unknown",
            "vm_identity_uncertain",
            "identity_unknown",
            "metadata_missing",
        }
    ]
    no_current_rule_blockers = not current_rule_blockers
    identity_reference_matches = not reference.get("vm_identity_id") or _as_text(identity_evidence.get("vm_identity_id")) == _as_text(reference.get("vm_identity_id"))
    identity_high = (
        identity_evidence.get("match_confidence") == "high"
        and identity_evidence.get("conflict_signal") is not True
        and identity_reference_matches
    )
    policy_allowed = policy_evidence.get("policy") == "allowed"
    operation_lock_evidence = recommendation_lock_evidence(
        cluster_id=calculated["cluster_id"],
        vm_identity_id=identity_evidence.get("vm_identity_id"),
        vmid=reference.get("vmid") if reference.get("vmid") is not None else (source_vm or {}).get("vmid"),
        source_node_id=reference.get("source_node_id") or (source_vm or {}).get("node_id"),
        target_node_id=reference.get("target_node_id"),
    )
    operation_lock_blockers = lock_blockers(operation_lock_evidence)
    proxmox_conflicts = _proxmox_conflict_evidence(source_vm)
    proxmox_conflict_blocker = "vm_config_lock" if proxmox_conflicts["config_lock"]["blocking"] else None

    checks = {
        "recommendation_freshness": _check_item(
            "pass" if not stale else "failed",
            blocker="stale_recommendation" if stale else None,
            criterion=_criterion_detail("stale_recommendation", status="failed" if stale else "pass", blocking=stale),
        ),
        "source_vm": _check_item(
            "pass" if source_exists else "failed",
            blocker="source_vm_missing" if not source_exists else None,
            criterion=_criterion_detail("source_vm_missing", status="failed" if not source_exists else "pass", blocking=not source_exists),
        ),
        "source_node": _check_item(
            "not_applicable" if not source_exists else "pass" if source_node_matches else "failed",
            blocker="source_node_changed" if source_exists and not source_node_matches else None,
            criterion=_criterion_detail(
                "source_node_not_applicable" if not source_exists else "source_node_changed",
                status="not_applicable" if not source_exists else "failed" if not source_node_matches else "pass",
                blocking=source_exists and not source_node_matches,
            ),
        ),
        "target_node": _check_item(
            "pass" if target_eligible else "failed",
            blocker="target_node_unavailable" if not target_eligible else None,
            criterion=_criterion_detail("target_node_unavailable", status="failed" if not target_eligible else "pass", blocking=not target_eligible),
        ),
        "vm_state": _check_item(
            "pass" if vm_state_eligible else "failed",
            blocker="vm_state_ineligible" if not vm_state_eligible else None,
            criterion=_criterion_detail("vm_state_ineligible", status="failed" if not vm_state_eligible else "pass", blocking=not vm_state_eligible),
        ),
        "route": _check_item(
            "pass" if route_ok else "warning",
            evidence=route,
            criterion=advisory_signals[0],
        ),
        "storage": _check_item(
            "pass" if not storage.get("blocked") else "warning",
            evidence=storage,
            criterion=advisory_signals[1],
        ),
        "passthrough": _check_item(
            "pass" if not passthrough.get("blocked") else "warning",
            evidence=passthrough,
            criterion=advisory_signals[2],
        ),
        "target_threshold": _check_item(
            "pass" if not target_threshold.get("blocked") else "failed",
            blocker="target_over_threshold" if target_threshold.get("blocked") else None,
            evidence=target_threshold,
            criterion=_criterion_detail("target_over_threshold", status="failed" if target_threshold.get("blocked") else "pass", blocking=target_threshold.get("blocked") is True),
        ),
        "identity": _check_item(
            "pass" if identity_high else "failed",
            blocker=(
                "vm_identity_mismatch"
                if not identity_reference_matches
                else "vm_identity_uncertain"
                if identity_evidence.get("match_confidence") != "unknown"
                else "vm_identity_unknown"
            ),
            criterion=_criterion_detail(
                "vm_identity_high"
                if identity_high
                else "identity_conflict"
                if identity_evidence.get("conflict_signal") is True
                else "vm_identity_mismatch"
                if not identity_reference_matches
                else "vm_identity_uncertain"
                if identity_evidence.get("match_confidence") != "unknown"
                else "vm_identity_unknown",
                status="pass" if identity_high else "failed",
                blocking=not identity_high,
            ),
        ),
        "policy": _check_item(
            "pass" if policy_allowed else "failed",
            blocker=f"migration_policy_{policy_evidence.get('policy', 'unknown')}",
            criterion=_criterion_detail(
                "migration_policy_allowed" if policy_allowed else f"migration_policy_{policy_evidence.get('policy', 'unknown')}",
                status="pass" if policy_allowed else "failed",
                blocking=not policy_allowed,
            ),
        ),
        "operation_lock": _check_item(
            "pass" if not operation_lock_blockers else "failed",
            blocker=operation_lock_blockers[0] if operation_lock_blockers else None,
            evidence=operation_lock_evidence,
            criterion=_criterion_detail(
                operation_lock_blockers[0] if operation_lock_blockers else "operation_lock_clear",
                status="failed" if operation_lock_blockers else "pass",
                blocking=bool(operation_lock_blockers),
            ),
        ),
        "proxmox_config_lock": _check_item(
            "failed" if proxmox_conflicts["config_lock"]["blocking"] else "pass",
            blocker=proxmox_conflict_blocker,
            evidence=proxmox_conflicts["config_lock"],
            criterion=_criterion_detail(
                "vm_config_lock" if proxmox_conflicts["config_lock"]["blocking"] else "vm_config_lock_clear",
                status="failed" if proxmox_conflicts["config_lock"]["blocking"] else "pass",
                blocking=proxmox_conflicts["config_lock"]["blocking"],
            ),
        ),
        "proxmox_active_task": _check_item(
            "not_collected",
            evidence=proxmox_conflicts["active_task"],
            criterion=_criterion_detail("proxmox_active_task_not_collected", status="not_collected", blocking=False),
        ),
        "proxmox_ha_state": _check_item(
            "not_collected",
            evidence=proxmox_conflicts["ha_state"],
            criterion=_criterion_detail("proxmox_ha_state_not_collected", status="not_collected", blocking=False),
        ),
        "proxmox_cluster_quorum": _check_item(
            "not_collected",
            evidence=proxmox_conflicts["cluster_quorum"],
            criterion=_criterion_detail("proxmox_cluster_quorum_not_collected", status="not_collected", blocking=False),
        ),
        "proxmox_conflicts": _check_item(
            _proxmox_conflict_status(proxmox_conflicts),
            blocker=proxmox_conflict_blocker,
            evidence=proxmox_conflicts,
            criterion=_criterion_detail(
                "vm_config_lock" if proxmox_conflicts["blocking"] else "vm_config_lock_clear",
                status=_proxmox_conflict_status(proxmox_conflicts),
                blocking=proxmox_conflicts["blocking"],
            ),
        ),
    }
    blockers = []
    for item in checks.values():
        blocker = item.get("blocker")
        if blocker and item.get("status") != "pass":
            blockers.append(blocker)
    blockers.extend(current_rule_blockers)
    blockers.extend(operation_lock_blockers)
    blockers = _unique(blockers)
    precheck_pass = all(
        [
            not stale,
            source_exists,
            source_node_matches,
            target_eligible,
            vm_state_eligible,
            no_current_rule_blockers,
            identity_high,
            policy_allowed,
            not operation_lock_blockers,
            not proxmox_conflicts["blocking"],
        ]
    )
    if not precheck_pass:
        blockers = _unique([*blockers, "drs_final_precheck_failed"])
    criteria, criteria_details, technical_gate_status = _criteria_summary(
        blockers=blockers,
        advisory_signals=advisory_signals,
        extra=_proxmox_pending_technical_criteria(),
    )
    result = {
        "recommendation_id": recommendation_id,
        "read_only": True,
        "executable": False,
        "would_be_executable": precheck_pass,
        "allowed_actions": [],
        "execution": dict(READ_ONLY_EXECUTION),
        "thresholds": dict(THRESHOLDS),
        "blockers": blockers,
        "blocker_details": _blocker_details(blockers),
        "criteria": criteria,
        "criteria_details": criteria_details,
        "advisory_signals": advisory_signals,
        "technical_gate_status": technical_gate_status,
        "identity_evidence": identity_evidence,
        "policy_evidence": policy_evidence,
        "checked_at": checked_at,
        "check": {
            "status": "would_pass" if precheck_pass else "blocked",
            "reference_only": True,
            "recalculated": True,
            "would_be_executable": precheck_pass,
            "blockers": blockers,
            "checks": checks,
            "criteria": criteria,
            "criteria_details": criteria_details,
            "advisory_signals": advisory_signals,
            "technical_gate_status": technical_gate_status,
            "checked_at": checked_at,
            "reason": "Read-only final pre-check completed; recommendation/check output remains execution-closed.",
            "observed_at": model["evidence"]["observed_at"],
        },
        "recommendation": recommendation or {
            "id": recommendation_id,
            "status": "stale",
            "blockers": blockers,
            "blocker_details": _blocker_details(blockers),
            "criteria": criteria,
            "criteria_details": criteria_details,
            "advisory_signals": advisory_signals,
            "technical_gate_status": technical_gate_status,
            "identity_evidence": identity_evidence,
            "policy_evidence": policy_evidence,
            "read_only": True,
            "executable": False,
            "allowed_actions": [],
            "execution": dict(READ_ONLY_EXECUTION),
        },
    }
    from app.drs.approval import build_approval_readiness

    result["approval_readiness"] = build_approval_readiness(result)
    return result
