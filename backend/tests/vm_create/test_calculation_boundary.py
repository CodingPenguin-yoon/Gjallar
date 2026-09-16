"""Calculation uses supplied policy; persistence retains the review contract."""

import json
from dataclasses import replace
from unittest.mock import patch

import pytest

from app.manifests.loader import load_builtin_profiles
from app.proxmox.inventory import FakeProxmoxInventoryAdapter
from app.vm_create.drafts import build_default_vm_draft
from app.vm_create.planner import calculate_vm_create_plan
from app.vm_create.plan_persistence import persist_vm_create_plan
from app.vm_create.preflight import run_preflight


def _calculate():
    profiles = {profile.profile_id: profile for profile in load_builtin_profiles()}
    draft = build_default_vm_draft(
        profiles=profiles,
        operator_id="calculation-test",
        job_id="job-calculation-test",
        target_node_id="yoonmanserver2",
        proposed_vmid=304,
        bridge_id="vmbr0",
        static_ip="192.168.2.142",
        prefix=24,
        gateway="192.168.2.1",
    )
    preflight = run_preflight(draft, profiles=profiles, inventory_adapter=FakeProxmoxInventoryAdapter())
    return calculate_vm_create_plan(draft, preflight)


def test_calculation_needs_no_database_or_artifact_writes():
    with (
        patch("sqlalchemy.engine.Connection.execute", side_effect=AssertionError("DB access during calculation")),
        patch("app.vm_create.plan_persistence.write_json_artifact", side_effect=AssertionError("artifact write")),
        patch("app.vm_create.plan_persistence.write_yaml_artifact", side_effect=AssertionError("artifact write")),
        patch("app.vm_create.plan_persistence.write_text_artifact", side_effect=AssertionError("artifact write")),
    ):
        first = _calculate()
        second = _calculate()
    assert first == second
    assert first.core["risk_summary"]["level"] == "yellow"
    assert "ssh_public_key" not in first.core["access"]


def test_calculation_rejects_preflight_for_another_draft():
    calculated = _calculate()
    with pytest.raises(ValueError, match="same draft"):
        calculate_vm_create_plan(calculated.draft, replace(calculated.preflight, draft_id="another-draft"))


def test_persistence_keeps_artifact_order_and_review_binding(tmp_path):
    from app.jobs.artifacts import read_artifact_text

    calculated = _calculate()
    plan = persist_vm_create_plan(calculated, run_dir=tmp_path)
    assert [artifact.type for artifact in plan.artifacts] == [
        "preflight_report", "plan", "vm_instance_manifest", "planned_git_diff", "review_summary",
    ]
    artifacts = {artifact.type: artifact for artifact in plan.artifacts}
    assert json.loads(read_artifact_text(artifacts["plan"])) == calculated.core
    assert plan.review_confirm["plan_artifact_id"] == artifacts["plan"].artifact_id
    assert plan.review_confirm["review_summary_checksum"] == artifacts["review_summary"].checksum
    repeated = persist_vm_create_plan(_calculate(), run_dir=tmp_path)
    assert repeated.review_confirm == plan.review_confirm
    assert [(a.artifact_id, a.checksum) for a in repeated.artifacts] == [
        (a.artifact_id, a.checksum) for a in plan.artifacts
    ]


@pytest.mark.parametrize("failed_type", [
    "preflight_report", "vm_instance_manifest", "planned_git_diff", "plan", "review_summary",
])
def test_plan_persistence_failure_prevents_external_execution(monkeypatch, failed_type):
    import asyncio
    from unittest.mock import Mock

    from app.vm_create import application, plan_persistence

    adapter = FakeProxmoxInventoryAdapter()
    payload = {
        "job_id": "job-persistence-failure",
        "bridge_id": "vmbr0",
        "static_ip": "192.168.2.142",
        "prefix": 24,
        "gateway": "192.168.2.1",
    }
    plan = application.build_preview_plan("draft-persistence-failure", payload, inventory_adapter=adapter)
    payload.update({
        "plan_artifact_id": plan.review_confirm["plan_artifact_id"],
        "review_summary_checksum": plan.review_confirm["review_summary_checksum"],
        "yellow_risk_acknowledged": True,
        "proxmox_mutation_acknowledged": True,
    })

    def failing_writer(original):
        def write(**kwargs):
            if kwargs["artifact_type"] == failed_type:
                raise RuntimeError("plan evidence unavailable")
            return original(**kwargs)
        return write

    for name in ("write_json_artifact", "write_yaml_artifact", "write_text_artifact"):
        monkeypatch.setattr(plan_persistence, name, failing_writer(getattr(plan_persistence, name)))
    factory = Mock()
    runner = Mock()
    monkeypatch.setattr(application, "run_proxmox_create", runner)
    with pytest.raises(RuntimeError, match="plan evidence unavailable"):
        asyncio.run(application.execute_proxmox_create(
            "draft-persistence-failure", payload, actor=None,
            inventory_adapter=adapter, mutation_client_factory=factory,
        ))
    factory.assert_not_called()
    runner.assert_not_called()
