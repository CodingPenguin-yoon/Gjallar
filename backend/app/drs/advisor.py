"""Read-only DRS Advisor calculations.

Phase 1 deliberately produces advisory candidates only. It never writes jobs,
artifacts, database records, or Proxmox mutations.
"""

from __future__ import annotations

import re
from typing import Any


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
READ_ONLY_EXECUTION = {
    "available": False,
    "allowed_actions": [],
    "reason": "DRS Phase 1 is advisory only; live migration execution is not exposed.",
}
BASE_BLOCKERS = (
    "identity_unknown",
    "metadata_missing",
    "policy_unknown",
    "final_precheck_not_run",
)
LOCAL_STORAGE_TYPES = {"dir", "lvm", "lvmthin", "zfspool", "zfs"}
LOCAL_STORAGE_IDS = {"local", "local-lvm", "local-zfs"}
PASSTHROUGH_TAG_TERMS = ("passthrough", "pci", "gpu", "usb")


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


def _vm_bridge_ids(vm: Any) -> list[str]:
    evidence = _as_list(_field(vm, "nic_bridge_evidence", "nicBridgeEvidence", default=[]))
    return _unique(
        [
            _field(item, "bridge_id", "bridgeId", "bridge", default="")
            for item in evidence
        ]
    )


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
        "bridge_ids": _vm_bridge_ids(source),
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
        "matched_tags": _unique(matched),
        "method": "tags_only",
        "limitation": "Phase 1 passthrough detection uses VM tags only; Proxmox device config parsing is not yet included.",
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
        "network_evidence_sufficient": network_sufficient,
        "storage_evidence_sufficient": storage_sufficient,
        "vm_bridge_ids": sorted(vm_bridge_ids),
        "source_bridge_ids": sorted(source_bridge_ids),
        "target_bridge_ids": sorted(target_bridge_ids),
        "matching_target_bridge_ids": matching_bridges,
        "vm_storage_ids": sorted(vm_storage_ids),
        "target_storage_ids": sorted(target_storage_ids),
    }


def _blocker_detail(code: str) -> dict[str, str]:
    messages = {
        "identity_unknown": "VM identity is not mapped to a stable DRS identity record.",
        "metadata_missing": "Required VM metadata/fingerprint records are not available.",
        "policy_unknown": "Placement policy data is not available.",
        "final_precheck_not_run": "Final migration precheck has not run.",
        "route_unknown": "Route, storage, or network evidence is insufficient.",
        "local_storage_dependency": "VM depends on local-style storage.",
        "passthrough_device_dependency": "VM has passthrough evidence.",
        "target_over_threshold": "Estimated target pressure would reach or exceed the critical threshold.",
    }
    return {"code": code, "message": messages.get(code, code), "severity": "blocking"}


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
) -> dict[str, Any]:
    route = _route_evidence(vm, source_node, target_node)
    local_storage = _local_storage_evidence(vm, nodes)
    passthrough = _passthrough_evidence(vm)
    pressure_effect = _estimate_pressure_effect(vm, source_node)
    target_pressure_after = min(100, target_node["pressure"] + pressure_effect)
    target_over_threshold = target_pressure_after >= THRESHOLDS["critical"]
    blockers = [
        *BASE_BLOCKERS,
        "route_unknown" if route["blocked"] else "",
        "local_storage_dependency" if local_storage["blocked"] else "",
        "passthrough_device_dependency" if passthrough["blocked"] else "",
        "target_over_threshold" if target_over_threshold else "",
    ]
    blockers = _unique([code for code in blockers if code])
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
        "blocker_details": [_blocker_detail(code) for code in blockers],
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


def _build_recommendations(nodes: list[dict[str, Any]], vms: list[dict[str, Any]], risks: list[Any]) -> list[dict[str, Any]]:
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
            recommendations.append(
                _build_recommendation(
                    vm=vm,
                    source_node=source_node,
                    target_node=target_node,
                    nodes=nodes,
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


def build_drs_advisor_model(adapter: Any, *, risks: list[Any] | None = None) -> dict[str, Any]:
    """Return a read-only DRS Advisor model from current inventory evidence."""
    snapshot = _snapshot(adapter)
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
    recommendations = _build_recommendations(nodes, vms, risk_items)
    summary = _summary(nodes, vms, risk_items, recommendations)
    return {
        "summary": summary,
        "recommendations": recommendations,
        "thresholds": dict(THRESHOLDS),
        "read_only": True,
        "executable": False,
        "allowed_actions": [],
        "execution": dict(READ_ONLY_EXECUTION),
        "evidence": {
            "source": _source_label(adapter, snapshot),
            "observed_at": _as_text(_field(snapshot, "observed_at", default="")),
            "candidate_filter": "running_non_template_vms_without_red_risk",
            "passthrough_detection": "tags_only",
        },
    }


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


def build_drs_check_result(
    adapter: Any,
    recommendation_id: str,
    *,
    risks: list[Any] | None = None,
) -> dict[str, Any] | None:
    model = build_drs_advisor_model(adapter, risks=risks)
    recommendation = next(
        (item for item in model["recommendations"] if item["id"] == recommendation_id),
        None,
    )
    if recommendation is None:
        return None
    return {
        "recommendation_id": recommendation_id,
        "read_only": True,
        "executable": False,
        "allowed_actions": [],
        "execution": dict(READ_ONLY_EXECUTION),
        "thresholds": dict(THRESHOLDS),
        "check": {
            "status": "blocked",
            "reference_only": True,
            "recalculated": True,
            "blockers": list(recommendation["blockers"]),
            "reason": "Reference-only recalculation completed; execution remains unavailable in DRS Phase 1.",
            "observed_at": model["evidence"]["observed_at"],
        },
        "recommendation": recommendation,
    }
