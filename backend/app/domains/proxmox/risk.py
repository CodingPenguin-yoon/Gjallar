"""Operational risk calculation helpers for the Proxmox operations console.

This module is intentionally pure/read-only: it receives inventory, monitoring,
snapshot, and task evidence and returns deterministic risk items. Proxmox API
calls stay in the service layer.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

SECONDS_PER_DAY = 86_400

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


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number else default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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


def _has_owner_or_tag(vm: Mapping[str, Any]) -> bool:
    tags = _split_tags(vm.get("tags"))
    if tags:
        lowered_tags = [tag.lower() for tag in tags]
        if any(
            tag.startswith(("owner=", "owner:", "owned-by=", "team=", "team:"))
            for tag in lowered_tags
        ):
            return True
        # For the first dashboard version, any explicit tag is treated as a
        # governance signal. A stricter owner taxonomy can be added later.
        return True

    description = str(vm.get("description") or vm.get("notes") or "").lower()
    return any(marker in description for marker in ["owner:", "owner=", "owned by", "team:", "team="])


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
        "evidence": evidence or {},
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


def _snapshot_age_days(snapshot: Mapping[str, Any], *, now_epoch: float) -> Optional[float]:
    snaptime = _safe_float(snapshot.get("snaptime") or snapshot.get("time"), 0.0)
    if snaptime <= 0:
        return None
    return max(0.0, (now_epoch - snaptime) / SECONDS_PER_DAY)


def build_operational_risk_dashboard(
    vms: Sequence[Mapping[str, Any]],
    nodes_monitoring: Sequence[Mapping[str, Any]],
    *,
    snapshots_by_vm: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
    backup_tasks_by_vm: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
    backup_not_backed_up_by_vmid: Optional[Mapping[Any, Mapping[str, Any]]] = None,
    backup_jobs: Optional[Sequence[Mapping[str, Any]]] = None,
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

    risks: List[Dict[str, Any]] = []

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

    # VM-specific risks.
    backup_evidence_enabled = backup_tasks_by_vm is not None
    backup_tasks_by_vm = backup_tasks_by_vm or {}
    for vm in vm_items:
        node = str(vm.get("node") or "unknown-node")
        vmid = _safe_int(vm.get("vmid"), 0)
        vm_name = str(vm.get("name") or vm.get("server_name") or f"vm-{vmid}")
        key = _vm_key(vm)
        status = str(vm.get("status") or "unknown").strip().lower()

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

        if not _has_owner_or_tag(vm):
            risks.append(
                _risk_item(
                    item_id=f"vm:{key}:owner-tag",
                    severity="info",
                    category="governance",
                    scope="vm",
                    node=node,
                    vmid=vmid,
                    vm_name=vm_name,
                    title=f"{vm_name} has no owner/tag signal",
                    detail="No tag or description owner signal was found in VM config metadata.",
                    recommendation="Add owner/team tags or a description so operational responsibility is clear.",
                    evidence={"tags": vm.get("tags", []), "description_present": bool(vm.get("description"))},
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

        if backup_evidence_enabled and not skip_backup_recency and not _has_recent_successful_backup(
            backup_tasks_by_vm.get(key, []) or [],
            now_epoch=now_epoch,
            warning_days=effective_thresholds["backup_warning_days"],
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
                    detail=f"No successful backup/vzdump task was found within {effective_thresholds['backup_warning_days']:.0f} days.",
                    recommendation="Confirm backup job coverage and run or schedule a backup if this VM is important.",
                    evidence={"lookback_days": effective_thresholds["backup_warning_days"]},
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
            "vm_state_history_collected": vm_state_history_collected,
            "vm_state_history_vms": len(vm_state_history) if vm_state_history_collected else None,
            "backup_uncovered_vms": len(backup_not_backed_up) if backup_schedule_evidence_enabled else None,
        },
    }
