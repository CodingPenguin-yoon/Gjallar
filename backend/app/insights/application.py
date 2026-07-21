"""Read-only application service composing risk and inventory Insights."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Mapping

from app.insights.domain import InsightSection, InsightsSnapshot, unavailable_section
from app.insights.ports import InventoryInsightPort, PlacementInsightPort, RiskInsightPort
from app.insights.rules import (
    CAPACITY_RULE_VERSION,
    PLACEMENT_RULE_VERSION,
    READINESS_RULE_VERSION,
    RISK_RULE_VERSION,
    build_capacity_section,
    build_placement_section,
    build_readiness_section,
    build_risk_section,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snapshot_status(sections: Mapping[str, InsightSection]) -> str:
    values = list(sections.values())
    if all(not section.available for section in values):
        return "unavailable"
    if any(not section.available or section.status == "unknown" for section in values):
        return "partial"
    if any(section.status == "attention" for section in values):
        return "attention"
    return "ready"


class InsightsQueryService:
    def __init__(
        self,
        *,
        inventory: InventoryInsightPort,
        risks: RiskInsightPort,
        placement: PlacementInsightPort,
        clock: Callable[[], str] = _now_iso,
    ) -> None:
        self._inventory = inventory
        self._risks = risks
        self._placement = placement
        self._clock = clock

    def query(self) -> InsightsSnapshot:
        risk_available = True
        raw_risks: list[dict] = []
        try:
            jobs = self._risks.list_jobs()
            risk_section, raw_risks = build_risk_section(jobs)
        except Exception:
            risk_available = False
            risk_section = unavailable_section(
                "risk",
                source="job_runs",
                rule_version=RISK_RULE_VERSION,
                reason="risk_source_unavailable",
            )

        try:
            inventory = self._inventory.observe()
            connection = dict(inventory.connection)
        except Exception:
            inventory = None
            connection = {
                "state": "degraded",
                "source": "unavailable",
                "freshness": "unavailable",
                "reason": "inventory_observation_failed",
                "inventory_available": False,
            }

        snapshot = inventory.snapshot if inventory is not None else None
        source = str(connection.get("source") or "proxmox_inventory")
        observed_at = connection.get("observed_at")
        freshness = str(connection.get("freshness") or "unknown")
        if snapshot is None:
            reason = str(connection.get("reason") or "inventory_unavailable")
            readiness = unavailable_section(
                "readiness",
                source=source,
                rule_version=READINESS_RULE_VERSION,
                reason=reason,
                observed_at=observed_at,
            )
            capacity = unavailable_section(
                "capacity",
                source=source,
                rule_version=CAPACITY_RULE_VERSION,
                reason=reason,
                observed_at=observed_at,
            )
            placement = unavailable_section(
                "placement",
                source=source,
                rule_version=PLACEMENT_RULE_VERSION,
                reason=reason,
                observed_at=observed_at,
            )
        else:
            try:
                readiness = build_readiness_section(snapshot, freshness=freshness)
            except Exception:
                readiness = unavailable_section(
                    "readiness",
                    source=source,
                    rule_version=READINESS_RULE_VERSION,
                    reason="readiness_calculation_failed",
                    observed_at=observed_at,
                )
            try:
                capacity = build_capacity_section(snapshot, freshness=freshness)
            except Exception:
                capacity = unavailable_section(
                    "capacity",
                    source=source,
                    rule_version=CAPACITY_RULE_VERSION,
                    reason="capacity_calculation_failed",
                    observed_at=observed_at,
                )
            if not risk_available:
                placement = unavailable_section(
                    "placement",
                    source="drs_advisor",
                    rule_version=PLACEMENT_RULE_VERSION,
                    reason="risk_source_unavailable",
                    observed_at=observed_at,
                )
            else:
                try:
                    placement_model = self._placement.build(snapshot, raw_risks)
                    capacity_summary = capacity.summary if capacity.available else {}
                    placement = build_placement_section(
                        placement_model,
                        freshness=freshness,
                        source_evidence_complete=(
                            int(capacity_summary.get("node_count") or 0) > 0
                            and int(capacity_summary.get("unknown") or 0) == 0
                        ),
                    )
                except Exception:
                    placement = unavailable_section(
                        "placement",
                        source="drs_advisor",
                        rule_version=PLACEMENT_RULE_VERSION,
                        reason="placement_calculation_failed",
                        observed_at=observed_at,
                    )

        sections = {
            "risk": risk_section,
            "readiness": readiness,
            "capacity": capacity,
            "placement": placement,
        }
        return InsightsSnapshot(
            generated_at=self._clock(),
            status=_snapshot_status(sections),
            connection=connection,
            sections=sections,
        )
