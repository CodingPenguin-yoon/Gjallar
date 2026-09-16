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


def _seed_succeeded_create_owner(
    *,
    operation_id: str,
    node_id: str,
    vmid: int,
    operation_details: dict | None = None,
):
    from app.operations.core.domain import OperationActor, OperationSpec
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore

    details = operation_details or {
        "target": {"node_id": node_id, "vmid": vmid, "name": f"vm-{vmid}"},
        "workload": {
            "vm_instance_id": f"{node_id}:{vmid}",
            "node_id": node_id,
            "vmid": vmid,
            "name": f"vm-{vmid}",
        },
    }
    SqlAlchemyOperationStore().create(
        OperationSpec(
            operation_id=operation_id,
            operation_type="vm_create",
            execution_mode="managed_api",
            target_type="proxmox_vm",
            target_id=f"vmid:{vmid}",
            idempotency_key=operation_id,
            intent_digest=f"sha256:intent-{operation_id}",
            plan_digest=f"sha256:plan-{operation_id}",
            actor=OperationActor(username="create-operator", role="operator"),
            initial_status="succeeded",
            initial_stage="post_check",
            details=details,
        ),
        event_payload={"test": True},
    )


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
    assert result["operation_linked"] is False
    assert replay["operation_linked"] is False


def test_exact_succeeded_create_owner_gets_one_checksum_link_and_replay_is_idempotent():
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.vm_create.post_create_readiness import POST_CREATE_READINESS_EVENT_TYPE
    from app.vm_actions.post_create_readiness import record_post_create_readiness_evidence

    operation_id = "create-owner-readiness-exact"
    _seed_succeeded_create_owner(operation_id=operation_id, node_id="node-a", vmid=311)

    result = record_post_create_readiness_evidence(
        node_id="node-a",
        vmid=311,
        payload=_payload(create_operation_id=operation_id, evidence_id="readiness-exact-owner"),
        actor=_actor(),
    )

    assert result["operation_linked"] is True
    assert result["operation_id"] == operation_id
    assert result["operation"]["status"] == "succeeded"
    artifact = result["artifact"]

    operations = SqlAlchemyOperationStore()
    linked_events = [
        event
        for event in operations.list_events(operation_id)
        if event.event_type == POST_CREATE_READINESS_EVENT_TYPE
    ]
    assert len(linked_events) == 1
    link = linked_events[0].payload
    assert link["readiness_job_id"] == result["job_id"]
    assert link["target"] == {"node_id": "node-a", "vmid": 311}
    assert link["artifact"] == {
        "artifact_id": artifact["artifact_id"],
        "type": "post_create_readiness_evidence",
        "checksum": artifact["checksum"],
    }
    assert "path" not in json.dumps(link, sort_keys=True)
    assert "operator-observed-service" not in json.dumps(link, sort_keys=True)
    assert "ticket-readiness-1" not in json.dumps(link, sort_keys=True)

    operation = operations.get(operation_id)
    assert operation is not None
    assert operation.details["post_create_readiness_evidence"] == link

    replay = record_post_create_readiness_evidence(
        node_id="node-a",
        vmid=311,
        payload=_payload(create_operation_id=operation_id, evidence_id="readiness-exact-owner"),
        actor=_actor(),
    )
    assert replay["idempotent_replay"] is True
    assert replay["operation_linked"] is True
    assert len(
        [
            event
            for event in operations.list_events(operation_id)
            if event.event_type == POST_CREATE_READINESS_EVENT_TYPE
        ]
    ) == 1


def test_readiness_link_rejects_artifact_with_wrong_job_or_checksum():
    from app.jobs.artifacts import write_json_artifact
    from app.jobs.runs import run_dir
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.vm_create.post_create_readiness import (
        POST_CREATE_READINESS_EVENT_TYPE,
        ensure_post_create_readiness_operation_link,
    )

    operation_id = "create-owner-readiness-artifact-binding"
    readiness_job_id = "post-create-readiness-node-a-315-binding"
    _seed_succeeded_create_owner(operation_id=operation_id, node_id="node-a", vmid=315)
    artifact = write_json_artifact(
        run_dir=run_dir(readiness_job_id),
        job_id=readiness_job_id,
        artifact_type="post_create_readiness_evidence",
        filename="post_create_readiness_evidence.json",
        payload={"safe": True},
    ).to_dict()

    wrong_job = ensure_post_create_readiness_operation_link(
        node_id="node-a",
        vmid=315,
        readiness_job_id="different-readiness-job",
        evidence_summary={},
        artifact=artifact,
        actor=_actor(),
    )
    wrong_checksum = ensure_post_create_readiness_operation_link(
        node_id="node-a",
        vmid=315,
        readiness_job_id=readiness_job_id,
        evidence_summary={},
        artifact={**artifact, "checksum": "sha256:not-the-stored-checksum"},
        actor=_actor(),
    )

    assert wrong_job is None
    assert wrong_checksum is None
    assert not [
        event
        for event in SqlAlchemyOperationStore().list_events(operation_id)
        if event.event_type == POST_CREATE_READINESS_EVENT_TYPE
    ]


def test_missing_create_operation_owner_remains_jobs_only():
    from app.db.models import VmInstanceRecord
    from app.db.session import session_scope
    from app.vm_actions.post_create_readiness import record_post_create_readiness_evidence

    with session_scope() as session:
        session.add(
            VmInstanceRecord(
                vm_instance_id="node-a:312",
                node_id="node-a",
                vmid=312,
                name="vm-312",
                status="running",
                profile_id="general-vm",
                template_id="template-9000",
                storage_id="local-lvm",
                cpu=2,
                memory_mb=4096,
                disk_gb=50,
                network={},
                access={},
                observed_after={"status": "running"},
                create_job_id="missing-create-operation",
                created_at="2026-08-26T00:00:00+00:00",
                updated_at="2026-08-26T00:00:00+00:00",
            )
        )

    result = record_post_create_readiness_evidence(
        node_id="node-a",
        vmid=312,
        payload=_payload(evidence_id="readiness-missing-owner"),
        actor=_actor(),
    )

    assert result["status"] == "completed"
    assert result["operation_linked"] is False
    assert "operation_id" not in result


def test_corrupt_or_mismatched_create_operation_binding_remains_jobs_only():
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.vm_create.post_create_readiness import POST_CREATE_READINESS_EVENT_TYPE
    from app.vm_actions.post_create_readiness import record_post_create_readiness_evidence

    operation_id = "create-owner-readiness-corrupt-binding"
    _seed_succeeded_create_owner(
        operation_id=operation_id,
        node_id="node-a",
        vmid=313,
        operation_details={
            "target": {"node_id": "node-a", "vmid": "not-an-integer"},
            "workload": {
                "vm_instance_id": "node-a:313",
                "node_id": "node-a",
                "vmid": 313,
            },
        },
    )

    result = record_post_create_readiness_evidence(
        node_id="node-a",
        vmid=313,
        payload=_payload(create_operation_id=operation_id, evidence_id="readiness-corrupt-binding"),
        actor=_actor(),
    )

    assert result["status"] == "completed"
    assert result["operation_linked"] is False
    assert "operation_id" not in result
    assert not [
        event
        for event in SqlAlchemyOperationStore().list_events(operation_id)
        if event.event_type == POST_CREATE_READINESS_EVENT_TYPE
    ]


def test_operation_append_failure_is_stable_503_and_replay_repairs_exact_link():
    from app.jobs.artifacts import list_artifact_records
    from app.jobs.runs import get_job_run
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.vm_create.post_create_readiness import POST_CREATE_READINESS_EVENT_TYPE
    from app.vm_actions.post_create_readiness import (
        PostCreateReadinessError,
        record_post_create_readiness_evidence,
    )

    operation_id = "create-owner-readiness-repair"
    _seed_succeeded_create_owner(operation_id=operation_id, node_id="node-a", vmid=314)
    payload = _payload(create_operation_id=operation_id, evidence_id="readiness-link-repair")

    with patch.object(
        SqlAlchemyOperationStore,
        "append_in_session",
        side_effect=RuntimeError("synthetic operation append failure"),
    ):
        with pytest.raises(PostCreateReadinessError) as raised:
            record_post_create_readiness_evidence(
                node_id="node-a",
                vmid=314,
                payload=payload,
                actor=_actor(),
            )

    assert raised.value.code == "POST_CREATE_READINESS_OPERATION_LINK_UNAVAILABLE"
    assert raised.value.status_code == 503
    assert raised.value.to_detail()["evidence_recorded"] is True
    assert raised.value.to_detail()["operation_linked"] is False
    job_id = raised.value.to_detail()["job_id"]
    assert get_job_run(job_id)["status"] == "completed"
    evidence_artifacts = [
        item
        for item in list_artifact_records(job_id)
        if item["type"] == "post_create_readiness_evidence"
    ]
    assert len(evidence_artifacts) == 1
    assert not [
        event
        for event in SqlAlchemyOperationStore().list_events(operation_id)
        if event.event_type == POST_CREATE_READINESS_EVENT_TYPE
    ]

    replay = record_post_create_readiness_evidence(
        node_id="node-a",
        vmid=314,
        payload=payload,
        actor=_actor(),
    )

    assert replay["idempotent_replay"] is True
    assert replay["operation_linked"] is True
    assert replay["operation_id"] == operation_id
    assert len(
        [
            event
            for event in SqlAlchemyOperationStore().list_events(operation_id)
            if event.event_type == POST_CREATE_READINESS_EVENT_TYPE
        ]
    ) == 1
    assert len(
        [
            item
            for item in list_artifact_records(job_id)
            if item["type"] == "post_create_readiness_evidence"
        ]
    ) == 1


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
    from app.api.v1 import vm_actions as v1_router

    payload = _payload(evidence_id="route-local-evidence")
    live_call_message = "readiness evidence route must not call live-capable helpers"
    with patch.object(
        v1_router.inventory_context,
        "inventory_adapter",
        side_effect=AssertionError(live_call_message),
    ) as inventory, patch.object(
        v1_router,
        "get_default_proxmox_mutation_client",
        side_effect=AssertionError(live_call_message),
    ) as proxmox_client_factory, patch.object(
        v1_router,
        "run_vm_start",
        side_effect=AssertionError(live_call_message),
    ) as run_vm_start, patch.object(
        v1_router,
        "run_vm_shutdown",
        side_effect=AssertionError(live_call_message),
    ) as run_vm_shutdown:
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
    for mocked in (inventory, proxmox_client_factory, run_vm_start, run_vm_shutdown):
        mocked.assert_not_called()
    assert not hasattr(v1_router, "run_proxmox_create")
    assert not hasattr(v1_router, "run_preflight")
