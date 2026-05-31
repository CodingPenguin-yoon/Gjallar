"""Tests for local-only post-create readiness evidence recording."""

import asyncio
import json
from unittest.mock import patch

import pytest


def _payload(*, evidence_id: str = "evidence-1", checks=None, **extra):
    return {
        "post_create_readiness_evidence_acknowledged": True,
        "evidence_id": evidence_id,
        "summary": "Operator reviewed post-create readiness evidence.",
        "limitations": "No live checks were run by Gjallar.",
        "checks": checks
        if checks is not None
        else [
            {
                "name": "operator-observed-service",
                "status": "passed",
                "observed_at": "2026-05-31T09:00:00Z",
                "summary": "Service responded in the operator-supplied evidence.",
                "evidence_ref": "ticket-readiness-1",
            }
        ],
        **extra,
    }


def _actor():
    return {"user_id": "user-operator-1", "username": "operator", "role": "operator"}


def test_acknowledgement_and_identity_are_required_before_persistence():
    from app.jobs.runs import list_job_runs
    from app.vm_actions.post_create_readiness import (
        PostCreateReadinessError,
        record_post_create_readiness_evidence,
    )

    with pytest.raises(PostCreateReadinessError) as missing_ack:
        record_post_create_readiness_evidence(
            node_id="node-a",
            vmid=306,
            payload={"evidence_id": "evidence-no-ack"},
            actor=_actor(),
        )

    assert missing_ack.value.code == "POST_CREATE_READINESS_ACK_REQUIRED"
    assert missing_ack.value.to_detail()["proxmox_mutation_enabled"] is False

    with pytest.raises(PostCreateReadinessError) as missing_identity:
        record_post_create_readiness_evidence(
            node_id="node-a",
            vmid=306,
            payload={"post_create_readiness_evidence_acknowledged": True},
            actor=_actor(),
        )

    assert missing_identity.value.code == "POST_CREATE_READINESS_IDENTITY_REQUIRED"
    assert list_job_runs() == []


def test_valid_evidence_writes_job_and_artifact_and_replays_without_second_artifact():
    from app.jobs.artifacts import list_artifact_records, read_artifact_text
    from app.jobs.runs import get_job_run
    from app.vm_actions.post_create_readiness import record_post_create_readiness_evidence

    result = record_post_create_readiness_evidence(
        node_id="node-a",
        vmid=306,
        payload=_payload(),
        actor=_actor(),
    )

    assert result["status"] == "completed"
    assert result["side_effects"] == []
    assert result["proxmox_mutation_enabled"] is False
    assert result["live_checks_performed_by_gjallar"] is False
    assert result["allowed_actions"] == []
    assert result["target"] == {"node_id": "node-a", "vmid": 306}
    assert result["actor_username"] == "operator"
    assert result["artifact"]["type"] == "post_create_readiness_evidence"
    assert result["artifact"]["path"].startswith("db://job-artifacts/")

    artifact_payload = json.loads(read_artifact_text(result["artifact"]))
    assert artifact_payload["operation"] == "post_create_readiness_evidence"
    assert artifact_payload["boundary"]["live_checks_performed_by_gjallar"] is False
    assert artifact_payload["actor_username"] == "operator"
    assert artifact_payload["evidence"]["status_counts"] == {"passed": 1}

    job = get_job_run(result["job_id"])
    assert job["job_type"] == "post_create_readiness"
    assert job["status"] == "completed"
    assert job["current_stage"] == "evidence_record"
    assert [step["id"] for step in job["steps"]] == ["request", "validation", "evidence_record"]
    assert [step["status"] for step in job["steps"]] == ["completed", "completed", "completed"]

    artifact_ids_before = [artifact["artifact_id"] for artifact in list_artifact_records(result["job_id"])]
    replay = record_post_create_readiness_evidence(
        node_id="node-a",
        vmid=306,
        payload=_payload(),
        actor=_actor(),
    )
    artifact_ids_after = [artifact["artifact_id"] for artifact in list_artifact_records(result["job_id"])]
    assert replay["job_id"] == result["job_id"]
    assert replay["idempotent_replay"] is True
    assert artifact_ids_after == artifact_ids_before


def test_skipped_unavailable_and_unapproved_statuses_are_preserved():
    from app.vm_actions.post_create_readiness import record_post_create_readiness_evidence

    result = record_post_create_readiness_evidence(
        node_id="node-a",
        vmid=307,
        payload=_payload(
            evidence_id="evidence-preserve-status",
            checks=[
                {"name": "ssh-login", "status": "unapproved", "summary": "Operator did not approve live SSH."},
                {"name": "guest-agent", "status": "unavailable", "summary": "No trusted evidence supplied."},
                {"name": "ansible-bootstrap", "status": "skipped", "summary": "Outside Goal 8 scope."},
            ],
        ),
        actor=_actor(),
    )

    assert [check["status"] for check in result["checks"]] == ["unapproved", "unavailable", "skipped"]
    assert result["evidence_summary"]["status_counts"] == {
        "skipped": 1,
        "unapproved": 1,
        "unavailable": 1,
    }


def test_secret_looking_values_are_rejected_before_persistence_without_echoing_values():
    from app.jobs.artifacts import list_artifact_records
    from app.jobs.runs import get_job_run
    from app.vm_actions.post_create_readiness import (
        PostCreateReadinessError,
        build_post_create_readiness_job_id,
        record_post_create_readiness_evidence,
    )

    evidence_id = "evidence-secret-rejected"
    secret_value = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secretpayload.signaturepayload"
    job_id = build_post_create_readiness_job_id(
        node_id="node-a",
        vmid=308,
        evidence_identity=evidence_id,
    )
    with pytest.raises(PostCreateReadinessError) as raised:
        record_post_create_readiness_evidence(
            node_id="node-a",
            vmid=308,
            payload=_payload(evidence_id=evidence_id, summary=secret_value),
            actor=_actor(),
        )

    detail = raised.value.to_detail()
    assert raised.value.code == "POST_CREATE_READINESS_SECRET_VALUE_REJECTED"
    assert secret_value not in json.dumps(detail)
    assert "Bearer" not in json.dumps(detail)
    assert get_job_run(job_id) is None
    assert list_artifact_records(job_id) == []


def test_live_command_and_endpoint_fields_are_rejected_before_persistence():
    from app.jobs.artifacts import list_artifact_records
    from app.jobs.runs import get_job_run
    from app.vm_actions.post_create_readiness import (
        PostCreateReadinessError,
        build_post_create_readiness_job_id,
        record_post_create_readiness_evidence,
    )

    evidence_id = "evidence-command-rejected"
    job_id = build_post_create_readiness_job_id(
        node_id="node-a",
        vmid=309,
        evidence_identity=evidence_id,
    )
    with pytest.raises(PostCreateReadinessError) as raised:
        record_post_create_readiness_evidence(
            node_id="node-a",
            vmid=309,
            payload=_payload(
                evidence_id=evidence_id,
                checks=[{"name": "operator-shell", "status": "unknown", "command": "uptime"}],
            ),
            actor=_actor(),
        )

    assert raised.value.code == "POST_CREATE_READINESS_DISALLOWED_FIELD"
    assert raised.value.to_detail()["field"] == "$.checks[0].command"
    assert get_job_run(job_id) is None
    assert list_artifact_records(job_id) == []

    with pytest.raises(PostCreateReadinessError):
        record_post_create_readiness_evidence(
            node_id="node-a",
            vmid=309,
            payload=_payload(evidence_id="evidence-live-rejected", run_live_checks=True),
            actor=_actor(),
        )


def test_route_records_local_evidence_without_calling_live_capable_router_functions():
    from app.api.v1 import router as v1_router

    payload = _payload(evidence_id="route-local-evidence")
    live_call_message = "Goal 8 route must not call live-capable helpers"
    with patch.object(v1_router, "_inventory_adapter", side_effect=AssertionError(live_call_message)) as inventory, patch.object(
        v1_router, "get_default_proxmox_mutation_client", side_effect=AssertionError(live_call_message)
    ) as proxmox_client_factory, patch.object(
        v1_router, "get_default_drs_proxmox_migration_client", side_effect=AssertionError(live_call_message)
    ) as drs_client_factory, patch.object(
        v1_router, "run_vm_start", side_effect=AssertionError(live_call_message)
    ) as run_vm_start, patch.object(
        v1_router, "run_proxmox_create", side_effect=AssertionError(live_call_message)
    ) as run_proxmox_create, patch.object(
        v1_router, "build_drs_check_result", side_effect=AssertionError(live_call_message)
    ) as build_drs_check_result, patch.object(
        v1_router, "execute_drs_migration_job", side_effect=AssertionError(live_call_message)
    ) as execute_drs, patch.object(
        v1_router, "run_preflight", side_effect=AssertionError(live_call_message)
    ) as run_preflight, patch.object(
        v1_router, "run_iac_readiness", side_effect=AssertionError(live_call_message)
    ) as run_iac_readiness:
        response = asyncio.run(
            v1_router.post_create_readiness_evidence_action(
                "node-a",
                310,
                payload,
                actor=_actor(),
            )
        )

    assert response["ok"] is True
    assert response["meta"]["mode"] == "post_create_readiness_evidence_local_only"
    assert response["data"]["live_checks_performed_by_gjallar"] is False
    for mocked in [
        inventory,
        proxmox_client_factory,
        drs_client_factory,
        run_vm_start,
        run_proxmox_create,
        build_drs_check_result,
        execute_drs,
        run_preflight,
        run_iac_readiness,
    ]:
        mocked.assert_not_called()
