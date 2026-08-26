"""Contract tests for the additive observe-only Insights API."""

import contextlib
import io
from types import SimpleNamespace
from unittest.mock import patch


def test_insights_route_exists_under_api_v1():
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        from app.main import app

    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/v1/insights" in paths


def test_insights_route_preserves_observe_only_envelope():
    from app.api.v1 import insights as v1_router

    aggregate = {
        "execution_mode": "observe_only",
        "read_only": True,
        "allowed_actions": [],
        "sections": {category: {} for category in ("risk", "readiness", "capacity", "placement")},
    }
    with patch.object(v1_router, "get_insights", return_value=aggregate):
        response = v1_router.get_insights_route()

    assert response == {"ok": True, "data": aggregate, "meta": {"mode": "observe_only"}}


def test_insights_route_composes_current_fake_inventory_and_empty_job_store():
    from app.api.v1 import insights as v1_router

    response = v1_router.get_insights_route()
    data = response["data"]

    assert response["ok"] is True
    assert data["execution_mode"] == "observe_only"
    assert data["connection"]["state"] == "test_fixture"
    assert set(data["sections"]) == {"risk", "readiness", "capacity", "placement"}
    assert all(section["read_only"] is True for section in data["sections"].values())
    assert all(section["allowed_actions"] == [] for section in data["sections"].values())


def test_insights_route_exposes_partial_inventory_sources_as_unknown_findings():
    from app.api.v1 import insights as v1_router

    snapshot = {
        "source": "live-proxmox",
        "observed_at": "2026-08-26T00:00:00+00:00",
        "connection": {"cluster_id": "cluster-a"},
        "nodes": [
            {
                "node_id": "node-a",
                "display_name": "Node A",
                "status": "online",
                "cpu_usage_percent": 10,
                "memory_usage_percent": 20,
                "storage": [],
                "networks": [],
            }
        ],
        "vms": [
            {
                "vmid": 301,
                "name": "partial-vm",
                "node_id": "node-a",
                "status": "running",
                "template": False,
                "guest_agent": {"available": False},
                "ip_addresses": [],
            }
        ],
        "templates": [],
        "availability": {
            "available": True,
            "complete": False,
            "sources": {
                "storage": {
                    "available": False,
                    "complete": False,
                    "expected_targets": 1,
                    "observed_targets": 0,
                    "failed_targets": ["node-a"],
                },
                "guest_agent": {
                    "available": False,
                    "complete": False,
                    "expected_targets": 1,
                    "observed_targets": 0,
                    "failed_targets": ["node-a:301"],
                },
            },
        },
    }
    observation = SimpleNamespace(
        snapshot=SimpleNamespace(to_dict=lambda: snapshot),
        status=SimpleNamespace(
            to_dict=lambda: {
                "state": "degraded",
                "source": "live-proxmox",
                "observed_at": snapshot["observed_at"],
                "freshness": "partial",
                "reason": "proxmox_inventory_partial",
                "inventory_available": True,
            }
        ),
    )
    query = SimpleNamespace(observe=lambda: observation)

    with (
        patch("app.insights.facade.get_default_workload_inventory_query", return_value=query),
        patch("app.insights.facade.list_job_runs_strict", return_value=[]),
    ):
        response = v1_router.get_insights_route()

    data = response["data"]
    readiness = data["sections"]["readiness"]
    capacity = data["sections"]["capacity"]
    assert readiness["status"] == "unknown"
    assert readiness["findings"][0]["code"] == "vm_readiness_observation_failed"
    assert readiness["findings"][0]["evidence"]["failed_sources"] == ["guest_agent"]
    assert capacity["status"] == "unknown"
    assert capacity["findings"][0]["code"] == "storage_observation_failed"
    assert capacity["findings"][0]["evidence"]["failed_target"] == "node-a"
