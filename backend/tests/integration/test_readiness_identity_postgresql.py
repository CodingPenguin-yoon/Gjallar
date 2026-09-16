"""Concurrent first evidence writers must not overwrite another Create history."""

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest


@pytest.mark.postgresql
@pytest.mark.parametrize("same_owner", [False, True])
def test_readiness_first_writer_claim_is_atomic(monkeypatch, same_owner):
    from app.db.session import reset_session_cache, session_scope
    from app.db.models import JobArtifactRecord
    from app.operations.core.domain import OperationActor, OperationSpec
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.vm_actions import post_create_readiness as recorder

    url = os.getenv("GJALLAR_POSTGRES_TEST_URL")
    if not url:
        pytest.skip("GJALLAR_POSTGRES_TEST_URL is required")
    monkeypatch.setenv("GJALLAR_DATABASE_URL", url)
    reset_session_cache()
    suffix = uuid.uuid4().hex
    owners = [f"pg-readiness-a-{suffix}", f"pg-readiness-b-{suffix}"]
    store = SqlAlchemyOperationStore()
    for owner in owners:
        store.create(OperationSpec(
            operation_id=owner, operation_type="vm_create", execution_mode="managed_api",
            target_type="proxmox_vm", target_id="vmid:987654", idempotency_key=owner,
            intent_digest=f"sha256:{suffix}", plan_digest=f"sha256:{suffix}",
            actor=OperationActor(username="test", role="operator"), initial_status="succeeded",
            initial_stage="post_check", details={
                "target": {"node_id": "node-test", "vmid": 987654},
                "workload": {"node_id": "node-test", "vmid": 987654, "vm_instance_id": "node-test:987654"},
            },
        ), event_payload={"test": True})
    if same_owner:
        owners[1] = owners[0]
    barrier = threading.Barrier(2)
    local = threading.local()
    read_job = recorder.get_job_run_strict

    def synchronized_first_read(job_id):
        result = read_job(job_id)
        if not getattr(local, "has_read", False):
            local.has_read = True
            barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(recorder, "get_job_run_strict", synchronized_first_read)

    def submit(owner):
        try:
            return recorder.record_post_create_readiness_evidence(
                node_id="node-test", vmid=987654, payload={
                    "create_operation_id": owner,
                    "post_create_readiness_evidence_acknowledged": True,
                    "evidence_id": f"pg-evidence-{suffix}", "summary": "local evidence",
                    "limitations": "test", "checks": [{"name": "test", "status": "passed"}],
                },
            )
        except recorder.PostCreateReadinessError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(submit, owners))
    successes = [value for value in outcomes if isinstance(value, dict)]
    errors = [value for value in outcomes if isinstance(value, recorder.PostCreateReadinessError)]
    assert len(successes) == (2 if same_owner else 1)
    assert [error.code for error in errors] == ([] if same_owner else ["POST_CREATE_READINESS_OWNER_CONFLICT"])
    winner = successes[0]
    assert winner["operation_linked"] is True
    with session_scope() as session:
        artifact = session.get(JobArtifactRecord, winner["artifact"]["artifact_id"])
        assert artifact.checksum == winner["artifact"]["checksum"]
    events = [event for owner in set(owners) for event in store.list_events(owner)
              if event.event_type == "post_create_readiness_evidence_linked"]
    assert len(events) == 1
    assert events[0].payload["artifact"]["checksum"] == winner["artifact"]["checksum"]
