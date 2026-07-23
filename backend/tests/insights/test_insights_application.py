"""Unit tests for availability-aware, execution-closed Insights."""

from __future__ import annotations

from pathlib import Path

from app.insights.application import InsightsQueryService
from app.insights.domain import InsightFinding
from app.insights.ports import InventoryInsightSource
from app.insights.rules import (
    MAX_FINDINGS_PER_SECTION,
    build_capacity_section,
    build_placement_section,
    build_readiness_section,
    build_risk_section,
)


OBSERVED_AT = "2026-07-21T01:02:03+00:00"


def _snapshot() -> dict:
    return {
        "source": "fake-proxmox",
        "observed_at": OBSERVED_AT,
        "connection": {"cluster_id": "cluster-a"},
        "nodes": [
            {
                "node_id": "node-hot",
                "display_name": "Node Hot",
                "status": "online",
                "cpu_usage_percent": 91,
                "memory_usage_percent": 72,
                "storage": [
                    {"storage_id": "local-lvm", "total_gb": 100, "free_gb": 9},
                ],
                "networks": [],
            },
            {
                "node_id": "node-cool",
                "display_name": "Node Cool",
                "status": "online",
                "cpu_usage_percent": 20,
                "memory_usage_percent": 30,
                "storage": [],
                "networks": [],
            },
        ],
        "vms": [
            {
                "vmid": 101,
                "name": "app-101",
                "node_id": "node-hot",
                "status": "running",
                "template": False,
                "guest_agent": {"available": False},
                "ip_addresses": [],
            },
        ],
        "templates": [],
    }


def _connection(*, state: str = "live", inventory_available: bool = True) -> dict:
    return {
        "state": state,
        "source": "fake-proxmox",
        "observed_at": OBSERVED_AT if inventory_available else None,
        "freshness": "live" if inventory_available else "unavailable",
        "reason": "configured" if inventory_available else "proxmox_unconfigured",
        "inventory_available": inventory_available,
    }


class _Inventory:
    def __init__(self, snapshot: dict | None, *, state: str = "live") -> None:
        self._source = InventoryInsightSource(
            connection=_connection(state=state, inventory_available=snapshot is not None),
            snapshot=snapshot,
        )

    def observe(self) -> InventoryInsightSource:
        return self._source


class _Risks:
    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail

    def list_jobs(self) -> list[dict]:
        if self._fail:
            raise RuntimeError("database password must not leak")
        return [
            {
                "job_id": "job-1",
                "job_type": "vm_create",
                "status": "blocked",
                "updated_at": OBSERVED_AT,
                "risks": [
                    {
                        "level": "red",
                        "code": "vm_blocked",
                        "message": "The workload is blocked",
                        "vmid": 101,
                    },
                ],
            },
        ]


class _Placement:
    def __init__(self, *, fail: bool = False) -> None:
        self.called = False
        self._fail = fail

    def build(self, snapshot: dict, risks: list[dict]) -> dict:
        self.called = True
        if self._fail:
            raise RuntimeError("placement unavailable")
        assert risks[0]["code"] == "vm_blocked"
        return {
            "evidence": {"source": snapshot["source"], "observed_at": snapshot["observed_at"]},
            "summary": {"cluster_state": "critical", "recommendation_count": 1},
            "recommendations": [
                {
                    "id": "drs-rec-1",
                    "vmid": 102,
                    "vm_name": "worker-102",
                    "source_node_id": "node-hot",
                    "target_node_id": "node-cool",
                    "reason": "Source pressure is high.",
                    "estimated_effect": {"source_pressure_before": 91, "target_pressure_after": 45},
                    "blockers": ["final_precheck_not_run"],
                },
            ],
        }


def _service(*, snapshot: dict | None = None, risks_fail: bool = False, placement: _Placement | None = None):
    return InsightsQueryService(
        inventory=_Inventory(snapshot if snapshot is not None else _snapshot()),
        risks=_Risks(fail=risks_fail),
        placement=placement or _Placement(),
        clock=lambda: "2026-07-21T02:00:00+00:00",
    )


def test_live_sources_compose_four_observe_only_sections():
    payload = _service().query().to_dict()

    assert payload["status"] == "attention"
    assert payload["execution_mode"] == "observe_only"
    assert payload["read_only"] is True
    assert payload["allowed_actions"] == []
    assert set(payload["sections"]) == {"risk", "readiness", "capacity", "placement"}
    for section in payload["sections"].values():
        assert section["available"] is True
        assert section["source"]
        assert section["freshness"]
        assert section["rule_version"]
        assert section["read_only"] is True
        assert section["allowed_actions"] == []
        for finding in section["findings"]:
            assert finding["source"]
            assert finding["observed_at"]
            assert finding["freshness"]
            assert finding["rule_version"]
            assert finding["allowed_actions"] == []


def test_non_live_inventory_keeps_recorded_risk_and_marks_inventory_sections_unavailable():
    service = InsightsQueryService(
        inventory=_Inventory(None, state="unconfigured"),
        risks=_Risks(),
        placement=_Placement(),
        clock=lambda: "2026-07-21T02:00:00+00:00",
    )

    payload = service.query().to_dict()

    assert payload["status"] == "partial"
    assert payload["sections"]["risk"]["available"] is True
    for category in ("readiness", "capacity", "placement"):
        section = payload["sections"][category]
        assert section["status"] == "unavailable"
        assert section["available"] is False
        assert section["findings"] == []
        assert section["unavailable_reason"] == "proxmox_unconfigured"


def test_risk_failure_is_not_empty_healthy_and_prevents_placement_calculation():
    placement = _Placement()

    payload = _service(risks_fail=True, placement=placement).query().to_dict()

    assert payload["status"] == "partial"
    assert payload["sections"]["risk"]["status"] == "unavailable"
    assert payload["sections"]["risk"]["unavailable_reason"] == "risk_source_unavailable"
    assert payload["sections"]["placement"]["unavailable_reason"] == "risk_source_unavailable"
    assert placement.called is False


def test_missing_capacity_metrics_and_unknown_power_are_not_counted_as_ready():
    snapshot = _snapshot()
    snapshot["nodes"][0]["cpu_usage_percent"] = None
    snapshot["nodes"][0]["memory_usage_percent"] = None
    snapshot["vms"][0]["status"] = "unknown"

    capacity = build_capacity_section(snapshot, freshness="live").to_dict()
    readiness = build_readiness_section(snapshot, freshness="live").to_dict()

    assert capacity["status"] != "ready"
    assert "node_pressure_unknown" in {finding["code"] for finding in capacity["findings"]}
    assert readiness["status"] == "unknown"
    assert readiness["summary"]["ready_count"] == 0
    assert "vm_power_state_unknown" in {finding["code"] for finding in readiness["findings"]}


def test_one_missing_pressure_metric_and_empty_node_inventory_are_unknown():
    snapshot = _snapshot()
    snapshot["nodes"] = [{
        "node_id": "node-partial",
        "status": "online",
        "cpu_usage_percent": 10,
        "memory_usage_percent": None,
        "storage": [],
    }]

    partial = build_capacity_section(snapshot, freshness="live").to_dict()
    snapshot["nodes"] = []
    empty = build_capacity_section(snapshot, freshness="live").to_dict()

    assert partial["status"] == "unknown"
    assert "node_pressure_incomplete" in {finding["code"] for finding in partial["findings"]}
    assert empty["status"] == "unknown"
    assert empty["findings"][0]["code"] == "node_inventory_empty"


def test_unknown_placement_state_is_not_ready_without_recommendations():
    section = build_placement_section(
        {
            "evidence": {"source": "fake-proxmox", "observed_at": OBSERVED_AT},
            "summary": {"cluster_state": "unknown", "recommendation_count": 0},
            "recommendations": [],
        },
        freshness="live",
    ).to_dict()

    assert section["status"] == "unknown"
    assert section["summary"]["cluster_state"] == "unknown"

    incomplete = build_placement_section(
        {
            "evidence": {"source": "fake-proxmox", "observed_at": OBSERVED_AT},
            "summary": {"cluster_state": "balanced", "recommendation_count": 0},
            "recommendations": [],
        },
        freshness="live",
        source_evidence_complete=False,
    ).to_dict()
    assert incomplete["status"] == "unknown"
    assert incomplete["summary"]["source_evidence_complete"] is False


def test_neutral_placement_accepts_the_inventory_snapshot_compatibility_adapter():
    from app.insights.facade import _PlacementPort

    model = _PlacementPort().build(_snapshot(), [])

    assert model["read_only"] is True
    assert model["allowed_actions"] == []
    assert model["evidence"]["source"] == "fake-proxmox"
    assert model["evidence"]["observed_at"] == OBSERVED_AT


def test_insights_placement_does_not_resolve_or_persist_drs_identity(monkeypatch):
    from app.drs import advisor as drs_advisor
    from app.insights.facade import _PlacementPort

    def unexpected_identity_resolution(*args, **kwargs):
        raise AssertionError("Insights placement must not resolve or persist DRS identity")

    monkeypatch.setattr(
        drs_advisor,
        "resolve_inventory_identities",
        unexpected_identity_resolution,
    )

    model = _PlacementPort().build(_snapshot(), [])

    assert model["recommendations"]
    assert model["recommendations"][0]["identity_evidence"] == {}
    assert model["recommendations"][0]["policy_evidence"] == {}


def test_placement_candidate_identity_and_pressure_contract_is_stable():
    from app.insights.facade import _PlacementPort

    model = _PlacementPort().build(_snapshot(), [])

    assert model["summary"]["cluster_state"] == "critical"
    assert model["summary"]["recommendation_count"] == 1
    recommendation = model["recommendations"][0]
    assert recommendation["id"] == "drs-rec-vm-101-node-hot-node-cool"
    assert recommendation["vmid"] == 101
    assert recommendation["source_node_id"] == "node-hot"
    assert recommendation["target_node_id"] == "node-cool"
    assert recommendation["estimated_effect"] == {
        "source_pressure_before": 91.0,
        "target_pressure_before": 30.0,
        "source_pressure_after": 73.0,
        "target_pressure_after": 48.0,
        "source_target_delta": 61.0,
    }
    assert recommendation["read_only"] is True
    assert recommendation["executable"] is False
    assert recommendation["allowed_actions"] == []


def test_finding_limit_discloses_total_and_truncation():
    jobs = [
        {
            "job_id": f"job-{index}",
            "updated_at": OBSERVED_AT,
            "risks": [{"level": "yellow", "code": "review", "message": f"Review {index}"}],
        }
        for index in range(MAX_FINDINGS_PER_SECTION + 1)
    ]

    section, raw_risks = build_risk_section(jobs)
    payload = section.to_dict()

    assert payload["summary"]["finding_count"] == MAX_FINDINGS_PER_SECTION + 1
    assert payload["summary"]["returned_finding_count"] == MAX_FINDINGS_PER_SECTION
    assert payload["summary"]["truncated"] is True
    assert len(payload["findings"]) == MAX_FINDINGS_PER_SECTION
    assert len(raw_risks) == MAX_FINDINGS_PER_SECTION + 1


def test_finding_id_is_deterministic_and_evidence_is_redacted():
    finding = InsightFinding(
        finding_id="fixed-id",
        category="risk",
        severity="warning",
        status="active",
        code="credential_exposure",
        title="Credential evidence",
        message="Sensitive evidence was detected.",
        target_type="job",
        target_id="job-1",
        source="job_runs",
        observed_at=OBSERVED_AT,
        freshness="recorded",
        rule_version="test.v1",
        evidence={"password": "do-not-return", "safe": "visible"},
    ).to_dict()
    first = build_readiness_section(_snapshot(), freshness="live").to_dict()["findings"][0]["finding_id"]
    second = build_readiness_section(_snapshot(), freshness="live").to_dict()["findings"][0]["finding_id"]

    assert first == second
    assert finding["evidence"] == {"password": "[REDACTED]", "safe": "visible"}


def test_domain_and_application_layers_do_not_depend_on_commands_or_web_frameworks():
    app_root = Path(__file__).resolve().parents[2] / "app" / "insights"
    source = "\n".join(
        (app_root / name).read_text()
        for name in (
            "domain.py",
            "ports.py",
            "rules.py",
            "application.py",
            "placement.py",
        )
    )
    facade_source = (app_root / "facade.py").read_text()

    for forbidden in (
        "fastapi",
        "sqlalchemy",
        "ProxmoxMutation",
        "record_job_run",
        "approval_packet",
        "app.drs",
        "session_scope",
    ):
        assert forbidden not in source
    assert "app.drs" not in facade_source
