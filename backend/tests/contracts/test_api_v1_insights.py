"""Contract tests for the additive observe-only Insights API."""

import contextlib
import io
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
