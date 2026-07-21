"""Pure rules mapping existing observations to common Insight findings."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from app.insights.domain import InsightFinding, InsightSection


RISK_RULE_VERSION = "job-risk.v1"
READINESS_RULE_VERSION = "operational-readiness.v1"
CAPACITY_RULE_VERSION = "capacity-pressure.v1"
PLACEMENT_RULE_VERSION = "placement-advisor.v1"
HOT_THRESHOLD = 70.0
CRITICAL_THRESHOLD = 85.0
STORAGE_WARNING_FREE_PERCENT = 20.0
STORAGE_CRITICAL_FREE_PERCENT = 10.0
MAX_FINDINGS_PER_SECTION = 200


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_text(value: Any, fallback: str = "") -> str:
    text = str(value if value is not None else "").strip()
    return text or fallback


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _finding_id(category: str, *identity: Any) -> str:
    canonical = json.dumps([category, *identity], ensure_ascii=True, separators=(",", ":"), sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]
    return f"insight-{category}-{digest}"


def _section_status(findings: Sequence[InsightFinding]) -> str:
    if any(item.status == "active" and item.severity in {"critical", "warning"} for item in findings):
        return "attention"
    if any(item.status == "unknown" or item.severity == "unknown" for item in findings):
        return "unknown"
    return "ready"


def _severity_counts(findings: Sequence[InsightFinding]) -> dict[str, int]:
    return {
        severity: len([finding for finding in findings if finding.severity == severity])
        for severity in ("critical", "warning", "info", "unknown")
    }


def _bounded_findings(findings: Sequence[InsightFinding]) -> tuple[tuple[InsightFinding, ...], dict[str, Any]]:
    returned = tuple(findings[:MAX_FINDINGS_PER_SECTION])
    total = len(findings)
    return returned, {
        "finding_count": total,
        "returned_finding_count": len(returned),
        "truncated": len(returned) < total,
        **_severity_counts(findings),
    }


def _observed_at(snapshot: Mapping[str, Any]) -> str | None:
    value = _as_text(snapshot.get("observed_at"))
    return value or None


def build_risk_section(jobs: Sequence[Mapping[str, Any]]) -> tuple[InsightSection, list[dict[str, Any]]]:
    findings: list[InsightFinding] = []
    raw_risks: list[dict[str, Any]] = []
    newest_observed_at: str | None = None
    for job in jobs:
        job_payload = _as_mapping(job)
        job_id = _as_text(job_payload.get("job_id"), "unknown")
        observed_at = _as_text(job_payload.get("updated_at") or job_payload.get("finished_at") or job_payload.get("started_at")) or None
        if observed_at and (newest_observed_at is None or observed_at > newest_observed_at):
            newest_observed_at = observed_at
        for index, risk_value in enumerate(_as_list(job_payload.get("risks"))):
            risk = _as_mapping(risk_value)
            if not risk:
                continue
            raw_risks.append(risk)
            level = _as_text(risk.get("level") or risk.get("risk_level"), "unknown").lower()
            severity = {"red": "critical", "yellow": "warning", "green": "info"}.get(level, "unknown")
            status = "clear" if severity == "info" else "unknown" if severity == "unknown" else "active"
            code = _as_text(risk.get("code"), "unclassified_risk")
            message = _as_text(risk.get("message") or risk.get("detail") or risk.get("title"), "Recorded operational risk")
            findings.append(
                InsightFinding(
                    finding_id=_finding_id("risk", RISK_RULE_VERSION, "job_runs", job_id, code, index, message),
                    category="risk",
                    severity=severity,
                    status=status,
                    code=code,
                    title=_as_text(risk.get("title"), code.replace("_", " ").title()),
                    message=message,
                    target_type="job",
                    target_id=job_id,
                    source="job_runs",
                    observed_at=observed_at,
                    freshness="recorded",
                    rule_version=RISK_RULE_VERSION,
                    evidence={
                        "job_id": job_id,
                        "job_type": job_payload.get("job_type"),
                        "job_status": job_payload.get("status"),
                        "risk": risk,
                        "artifacts_url": f"/api/v1/jobs/{job_id}/artifacts",
                    },
                )
            )
    returned_findings, finding_summary = _bounded_findings(findings)
    return (
        InsightSection(
            category="risk",
            status=_section_status(findings),
            available=True,
            source="job_runs",
            observed_at=newest_observed_at,
            freshness="recorded",
            rule_version=RISK_RULE_VERSION,
            summary=finding_summary,
            findings=returned_findings,
        ),
        raw_risks,
    )


def _vm_target(vm: Mapping[str, Any]) -> tuple[str, str, int]:
    vmid_value = vm.get("vmid", vm.get("id"))
    try:
        vmid = int(vmid_value)
    except (TypeError, ValueError):
        vmid = 0
    name = _as_text(vm.get("name") or vm.get("vm_name"), f"vm-{vmid or 'unknown'}")
    target_id = f"vmid:{vmid}" if vmid > 0 else f"name:{name}"
    return target_id, name, vmid


def build_readiness_section(
    snapshot: Mapping[str, Any],
    *,
    freshness: str,
) -> InsightSection:
    observed_at = _observed_at(snapshot)
    source = _as_text(snapshot.get("source"), "proxmox_inventory")
    vms = [_as_mapping(item) for item in _as_list(snapshot.get("vms")) if not _as_mapping(item).get("template")]
    findings: list[InsightFinding] = []
    ready_count = 0
    for vm in vms:
        target_id, name, vmid = _vm_target(vm)
        status = _as_text(vm.get("status"), "unknown").lower()
        lock = _as_text(vm.get("config_lock") or vm.get("configLock"))
        guest_agent = _as_mapping(vm.get("guest_agent") or vm.get("guestAgent"))
        guest_agent_available = guest_agent.get("available") is True
        ip_addresses = [
            _as_text(item)
            for item in _as_list(vm.get("ip_addresses") or vm.get("ipAddresses"))
            if _as_text(item)
        ]
        code = ""
        severity = "info"
        finding_status = "clear"
        message = "No operational readiness issue was detected from the current observation."
        if lock:
            code = "vm_config_locked"
            severity = "critical"
            finding_status = "active"
            message = f"VM config is locked with type {lock}."
        elif status in {"", "unknown"}:
            code = "vm_power_state_unknown"
            severity = "unknown"
            finding_status = "unknown"
            message = "VM power state is not available from the current observation."
        elif status == "running" and not guest_agent_available:
            code = "guest_agent_unavailable"
            severity = "warning"
            finding_status = "active"
            message = "Running VM does not expose available guest-agent evidence."
        elif status == "running" and not ip_addresses:
            code = "usable_ip_unavailable"
            severity = "warning"
            finding_status = "active"
            message = "Running VM has no observed IP address evidence."
        if not code:
            ready_count += 1
            continue
        findings.append(
            InsightFinding(
                finding_id=_finding_id("readiness", READINESS_RULE_VERSION, source, target_id, code),
                category="readiness",
                severity=severity,
                status=finding_status,
                code=code,
                title=f"{name}: {code.replace('_', ' ')}",
                message=message,
                target_type="proxmox_vm",
                target_id=target_id,
                source=source,
                observed_at=observed_at,
                freshness=freshness,
                rule_version=READINESS_RULE_VERSION,
                evidence={
                    "node_id": vm.get("node_id") or vm.get("nodeId"),
                    "vmid": vmid or None,
                    "name": name,
                    "power_status": status,
                    "config_lock": lock or None,
                    "guest_agent_available": guest_agent_available,
                    "observed_ip_count": len(ip_addresses),
                },
            )
        )
    returned_findings, finding_summary = _bounded_findings(findings)
    return InsightSection(
        category="readiness",
        status=_section_status(findings),
        available=True,
        source=source,
        observed_at=observed_at,
        freshness=freshness,
        rule_version=READINESS_RULE_VERSION,
        summary={"workload_count": len(vms), "ready_count": ready_count, **finding_summary},
        findings=returned_findings,
    )


def _capacity_finding(
    *,
    code: str,
    severity: str,
    title: str,
    message: str,
    target_type: str,
    target_id: str,
    source: str,
    observed_at: str | None,
    freshness: str,
    evidence: Mapping[str, Any],
) -> InsightFinding:
    return InsightFinding(
        finding_id=_finding_id("capacity", CAPACITY_RULE_VERSION, source, target_type, target_id, code),
        category="capacity",
        severity=severity,
        status="unknown" if severity == "unknown" else "active",
        code=code,
        title=title,
        message=message,
        target_type=target_type,
        target_id=target_id,
        source=source,
        observed_at=observed_at,
        freshness=freshness,
        rule_version=CAPACITY_RULE_VERSION,
        evidence=evidence,
    )


def build_capacity_section(
    snapshot: Mapping[str, Any],
    *,
    freshness: str,
) -> InsightSection:
    observed_at = _observed_at(snapshot)
    source = _as_text(snapshot.get("source"), "proxmox_inventory")
    nodes = [_as_mapping(item) for item in _as_list(snapshot.get("nodes"))]
    findings: list[InsightFinding] = []
    online_count = 0
    observed_storage_count = 0
    if not nodes:
        findings.append(_capacity_finding(
            code="node_inventory_empty",
            severity="unknown",
            title="Cluster capacity unknown",
            message="No node capacity evidence is available from the current observation.",
            target_type="proxmox_cluster",
            target_id="current",
            source=source,
            observed_at=observed_at,
            freshness=freshness,
            evidence={"node_count": 0},
        ))
    for node in nodes:
        node_id = _as_text(node.get("node_id") or node.get("nodeId") or node.get("id"), "unknown")
        node_name = _as_text(node.get("display_name") or node.get("displayName") or node.get("name"), node_id)
        node_status = _as_text(node.get("status"), "unknown").lower()
        cpu = _as_float(node.get("cpu_usage_percent", node.get("cpuUsagePercent")))
        memory = _as_float(node.get("memory_usage_percent", node.get("memoryUsagePercent")))
        if node_status == "online":
            online_count += 1
        elif node_status == "unknown":
            findings.append(_capacity_finding(
                code="node_status_unknown",
                severity="unknown",
                title=f"{node_name}: node status unknown",
                message="Node availability is not known from the current observation.",
                target_type="proxmox_node",
                target_id=node_id,
                source=source,
                observed_at=observed_at,
                freshness=freshness,
                evidence={"status": node_status, "cpu_usage_percent": cpu, "memory_usage_percent": memory},
            ))
        else:
            findings.append(_capacity_finding(
                code="node_offline",
                severity="critical",
                title=f"{node_name}: node offline",
                message=f"Node status is {node_status}.",
                target_type="proxmox_node",
                target_id=node_id,
                source=source,
                observed_at=observed_at,
                freshness=freshness,
                evidence={"status": node_status, "cpu_usage_percent": cpu, "memory_usage_percent": memory},
            ))
        observed_metrics = [value for value in (cpu, memory) if value is not None]
        if not observed_metrics:
            findings.append(_capacity_finding(
                code="node_pressure_unknown",
                severity="unknown",
                title=f"{node_name}: pressure unknown",
                message="CPU and memory pressure metrics are not available.",
                target_type="proxmox_node",
                target_id=node_id,
                source=source,
                observed_at=observed_at,
                freshness=freshness,
                evidence={"cpu_usage_percent": cpu, "memory_usage_percent": memory},
            ))
        else:
            missing_metrics = [name for name, value in (("cpu_usage_percent", cpu), ("memory_usage_percent", memory)) if value is None]
            if missing_metrics:
                findings.append(_capacity_finding(
                    code="node_pressure_incomplete",
                    severity="unknown",
                    title=f"{node_name}: pressure evidence incomplete",
                    message="Some CPU or memory pressure metrics are not available.",
                    target_type="proxmox_node",
                    target_id=node_id,
                    source=source,
                    observed_at=observed_at,
                    freshness=freshness,
                    evidence={
                        "cpu_usage_percent": cpu,
                        "memory_usage_percent": memory,
                        "missing_metrics": missing_metrics,
                    },
                ))
            pressure = max(observed_metrics)
            if pressure >= CRITICAL_THRESHOLD:
                code, severity = "node_pressure_critical", "critical"
            elif pressure >= HOT_THRESHOLD:
                code, severity = "node_pressure_hot", "warning"
            else:
                code, severity = "", "info"
            if code:
                findings.append(_capacity_finding(
                    code=code,
                    severity=severity,
                    title=f"{node_name}: capacity pressure {round(pressure)}%",
                    message=f"Maximum observed CPU/memory pressure is {round(pressure, 2)}%.",
                    target_type="proxmox_node",
                    target_id=node_id,
                    source=source,
                    observed_at=observed_at,
                    freshness=freshness,
                    evidence={
                        "cpu_usage_percent": cpu,
                        "memory_usage_percent": memory,
                        "pressure_percent": pressure,
                        "hot_threshold": HOT_THRESHOLD,
                        "critical_threshold": CRITICAL_THRESHOLD,
                    },
                ))
        for storage_value in _as_list(node.get("storage")):
            storage = _as_mapping(storage_value)
            storage_id = _as_text(storage.get("storage_id") or storage.get("storageId") or storage.get("id"), "unknown")
            total = _as_float(storage.get("total_gb", storage.get("totalGb")))
            free = _as_float(storage.get("free_gb", storage.get("freeGb")))
            if total is None or total <= 0 or free is None:
                findings.append(_capacity_finding(
                    code="storage_capacity_unknown",
                    severity="unknown",
                    title=f"{node_name}/{storage_id}: capacity unknown",
                    message="Storage total or free capacity is not available.",
                    target_type="proxmox_storage",
                    target_id=f"{node_id}:{storage_id}",
                    source=source,
                    observed_at=observed_at,
                    freshness=freshness,
                    evidence={"node_id": node_id, "storage_id": storage_id, "total_gb": total, "free_gb": free},
                ))
                continue
            observed_storage_count += 1
            free_percent = max(0.0, min(100.0, (free / total) * 100))
            if free_percent < STORAGE_CRITICAL_FREE_PERCENT:
                code, severity = "storage_free_critical", "critical"
            elif free_percent < STORAGE_WARNING_FREE_PERCENT:
                code, severity = "storage_free_low", "warning"
            else:
                continue
            findings.append(_capacity_finding(
                code=code,
                severity=severity,
                title=f"{node_name}/{storage_id}: free capacity {round(free_percent)}%",
                message=f"Storage free capacity is {round(free_percent, 2)}%.",
                target_type="proxmox_storage",
                target_id=f"{node_id}:{storage_id}",
                source=source,
                observed_at=observed_at,
                freshness=freshness,
                evidence={
                    "node_id": node_id,
                    "storage_id": storage_id,
                    "total_gb": total,
                    "free_gb": free,
                    "free_percent": free_percent,
                    "warning_threshold": STORAGE_WARNING_FREE_PERCENT,
                    "critical_threshold": STORAGE_CRITICAL_FREE_PERCENT,
                },
            ))
    returned_findings, finding_summary = _bounded_findings(findings)
    return InsightSection(
        category="capacity",
        status=_section_status(findings),
        available=True,
        source=source,
        observed_at=observed_at,
        freshness=freshness,
        rule_version=CAPACITY_RULE_VERSION,
        summary={
            "node_count": len(nodes),
            "online_node_count": online_count,
            "observed_storage_count": observed_storage_count,
            "thresholds": {
                "hot": HOT_THRESHOLD,
                "critical": CRITICAL_THRESHOLD,
                "storage_warning_free_percent": STORAGE_WARNING_FREE_PERCENT,
                "storage_critical_free_percent": STORAGE_CRITICAL_FREE_PERCENT,
            },
            **finding_summary,
        },
        findings=returned_findings,
    )


def build_placement_section(
    model: Mapping[str, Any],
    *,
    freshness: str,
    source_evidence_complete: bool = True,
) -> InsightSection:
    payload = _as_mapping(model)
    evidence = _as_mapping(payload.get("evidence"))
    source = _as_text(evidence.get("source"), "drs_advisor")
    observed_at = _as_text(evidence.get("observed_at")) or None
    recommendations = [_as_mapping(item) for item in _as_list(payload.get("recommendations"))]
    findings: list[InsightFinding] = []
    for recommendation in recommendations:
        recommendation_id = _as_text(recommendation.get("id"), "unknown")
        vmid = recommendation.get("vmid")
        vm_name = _as_text(recommendation.get("vm_name"), f"vm-{vmid or 'unknown'}")
        estimated = _as_mapping(recommendation.get("estimated_effect"))
        source_pressure = _as_float(estimated.get("source_pressure_before")) or 0.0
        target_after = _as_float(estimated.get("target_pressure_after")) or 0.0
        severity = "critical" if max(source_pressure, target_after) >= CRITICAL_THRESHOLD else "warning"
        findings.append(
            InsightFinding(
                finding_id=_finding_id("placement", PLACEMENT_RULE_VERSION, source, recommendation_id),
                category="placement",
                severity=severity,
                status="active",
                code="placement_candidate",
                title=f"Placement candidate: {vm_name}",
                message=_as_text(recommendation.get("reason"), "A lower-pressure target placement was identified."),
                target_type="proxmox_vm",
                target_id=f"vmid:{vmid}" if vmid is not None else f"recommendation:{recommendation_id}",
                source=source,
                observed_at=observed_at,
                freshness=freshness,
                rule_version=PLACEMENT_RULE_VERSION,
                evidence={
                    "recommendation_id": recommendation_id,
                    "vmid": vmid,
                    "vm_name": vm_name,
                    "source_node_id": recommendation.get("source_node_id"),
                    "target_node_id": recommendation.get("target_node_id"),
                    "estimated_effect": estimated,
                    "blockers": _as_list(recommendation.get("blockers")),
                    "criteria": _as_mapping(recommendation.get("criteria")),
                    "identity_evidence": _as_mapping(recommendation.get("identity_evidence")),
                    "policy_evidence": _as_mapping(recommendation.get("policy_evidence")),
                    "route_evidence": _as_mapping(_as_mapping(recommendation.get("evidence")).get("route")),
                    "legacy_product_status": "maintenance",
                },
            )
        )
    summary = _as_mapping(payload.get("summary"))
    cluster_state = _as_text(summary.get("cluster_state"), "unknown").lower()
    status = _section_status(findings)
    if status == "ready" and not source_evidence_complete:
        status = "unknown"
    elif status == "ready" and cluster_state in {"unknown", "unavailable"}:
        status = "unknown"
    elif status == "ready" and cluster_state in {"hot", "critical", "degraded", "imbalanced"}:
        status = "attention"
    returned_findings, finding_summary = _bounded_findings(findings)
    return InsightSection(
        category="placement",
        status=status,
        available=True,
        source=source,
        observed_at=observed_at,
        freshness=freshness,
        rule_version=PLACEMENT_RULE_VERSION,
        summary={
            "cluster_state": cluster_state,
            "recommendation_count": summary.get("recommendation_count", len(findings)),
            "hot_node_count": summary.get("hot_node_count", 0),
            "critical_node_count": summary.get("critical_node_count", 0),
            "source_target_delta": summary.get("source_target_delta", 0),
            "source_evidence_complete": source_evidence_complete,
            **finding_summary,
        },
        findings=returned_findings,
    )
