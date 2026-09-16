"""Contracts for verified graceful VM Shutdown."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.proxmox.client import ProxmoxMutationError
from app.proxmox.models import VmInventory


class Inventory:
    source = "test_read_only"

    def __init__(self, *, status: str = "running", name: str = "app", node_id: str = "node-a", vmid: int = 306):
        self.vm = VmInventory(
            vmid=vmid,
            name=name,
            node_id=node_id,
            status=status,
            template=False,
            cpu=2,
            memory_mb=2048,
            disk_gb=20,
        )

    def list_vms(self):
        return [self.vm]

    def list_templates(self):
        return []


class ShutdownClient:
    def __init__(self, *, upid="UPID:node-a:0002:qmshutdown", task=None, observed_status="stopped", error=None):
        self.upid = upid
        self.task = task or {
            "node": "node-a",
            "upid": upid,
            "status": "stopped",
            "exitstatus": "OK",
            "polls": [{"status": "running"}, {"status": "stopped", "exitstatus": "OK"}],
        }
        self.observed_status = observed_status
        self.error = error
        self.calls = []

    def redacted_connection_context(self):
        return {"api_url": "https://pve.example.test/api2/json", "token_secret": "[REDACTED]"}

    def shutdown_vm(self, *, node, vmid):
        self.calls.append(("shutdown_vm", {"node": node, "vmid": vmid}))
        if self.error is not None:
            raise self.error
        return self.upid

    def wait_for_task(self, *, node, upid, heartbeat=None):
        self.calls.append(("wait_for_task", {"node": node, "upid": upid}))
        if heartbeat is not None:
            heartbeat()
        return dict(self.task)

    def get_vm_status(self, *, node, vmid):
        self.calls.append(("get_vm_status", {"node": node, "vmid": vmid}))
        return {"node_id": node, "vmid": vmid, "name": "app", "status": self.observed_status}


def run_shutdown(*, client=None, inventory=None, payload=None):
    from app.api.v1 import vm_actions as router

    client = client or ShutdownClient()
    inventory = inventory or Inventory()
    with patch.object(router.inventory_context, "mutation_inventory_adapter", return_value=inventory), patch.object(
        router,
        "get_default_proxmox_mutation_client",
        return_value=client,
    ):
        return asyncio.run(
            router.shutdown_vm_action(
                "node-a",
                306,
                payload
                or {
                    "vm_shutdown_acknowledged": True,
                    "idempotency_key": "shutdown-default",
                    "expected_name": "app",
                    "expected_status": "running",
                },
            )
        )


def test_shutdown_route_is_additive():
    from app.main import app

    assert "/api/v1/nodes/{node_id}/vms/{vmid}/actions/shutdown" in {
        getattr(route, "path", "") for route in app.routes
    }


def test_shutdown_requires_ack_and_idempotency_before_client_creation():
    from app.api.v1 import vm_actions as router

    with patch.object(router, "get_default_proxmox_mutation_client") as factory:
        with pytest.raises(HTTPException) as missing_ack:
            asyncio.run(router.shutdown_vm_action("node-a", 306, {"idempotency_key": "idem"}))
        with pytest.raises(HTTPException) as missing_key:
            asyncio.run(router.shutdown_vm_action("node-a", 306, {"vm_shutdown_acknowledged": True}))

    assert missing_ack.value.detail["code"] == "VM_SHUTDOWN_ACK_REQUIRED"
    assert missing_key.value.detail["code"] == "VM_SHUTDOWN_IDEMPOTENCY_KEY_REQUIRED"
    factory.assert_not_called()


def test_shutdown_precheck_requires_running_vm_without_post():
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.target_lock import get_target_operation_lock

    client = ShutdownClient()
    payload = {
        "vm_shutdown_acknowledged": True,
        "idempotency_key": "shutdown-stopped-precheck",
        "expected_name": "app",
    }

    with pytest.raises(HTTPException) as raised:
        run_shutdown(
            client=client,
            inventory=Inventory(status="stopped"),
            payload=payload,
        )

    assert raised.value.detail["code"] == "VM_SHUTDOWN_NON_RUNNING_BLOCKED"
    assert client.calls == []
    job_id = raised.value.detail["job_id"]
    operation_store = SqlAlchemyOperationStore()
    operation = operation_store.get(job_id)
    latest_event = operation_store.list_events(job_id)[-1]
    assert operation.status == "blocked"
    assert operation.details["pre_dispatch_terminal_no_effect"] is True
    assert operation.details["mutation_dispatched"] is False
    assert operation.details["pre_dispatch_terminal_reason"] == "precheck_blocked"
    assert operation.details["target_lock_id"].startswith("operation-lock-")
    assert operation.details["cluster_id"] == "gjallar-mvp"
    assert latest_event.payload["target_lock_id"] == operation.details["target_lock_id"]
    assert get_target_operation_lock("proxmox_vm", "vmid:306") is None

    replay_client = ShutdownClient()
    replay = run_shutdown(client=replay_client, inventory=Inventory(status="stopped"), payload=payload)
    assert replay["data"]["idempotent_replay"] is True
    assert replay["data"]["status"] == "blocked"
    assert get_target_operation_lock("proxmox_vm", "vmid:306") is None
    assert replay_client.calls == []


def test_shutdown_blocked_terminal_release_crash_is_operator_recoverable_without_proxmox():
    from app.operations.core.domain import OperationActor
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
    from app.operations.recovery.runtime import RecoveryRuntimeConfig, build_recovery_coordinator
    from app.operations.target_lock import get_target_operation_lock

    client = ShutdownClient()
    with patch("app.vm_actions.shutdown._LockAdapter.release_target", return_value=None):
        with pytest.raises(HTTPException) as raised:
            run_shutdown(
                client=client,
                inventory=Inventory(status="stopped"),
                payload={
                    "vm_shutdown_acknowledged": True,
                    "idempotency_key": "shutdown-blocked-terminal-release-crash",
                    "expected_name": "app",
                },
            )

    job_id = raised.value.detail["job_id"]
    operation_store = SqlAlchemyOperationStore()
    operation = operation_store.get(job_id)
    assert operation.status == "blocked"
    assert operation.details["pre_dispatch_terminal_reason"] == "precheck_blocked"
    assert get_target_operation_lock("proxmox_vm", "vmid:306")["owner_id"] == job_id
    assert SqlAlchemyRecoveryStore().get(job_id) is None

    recovered = build_recovery_coordinator(
        config=RecoveryRuntimeConfig(enabled=True, poll_seconds=5, lease_seconds=60)
    ).observe(
        job_id,
        actor=OperationActor(user_id="operator-1", username="operator", role="operator"),
        expected_version=operation.version,
        expected_checksum=operation.last_event_checksum,
        idempotency_key="observe-shutdown-blocked-terminal-release-crash",
    )

    assert recovered["outcome"] == "blocked"
    assert operation_store.get(job_id).status == "blocked"
    assert SqlAlchemyRecoveryStore().get(job_id).status == "completed"
    assert get_target_operation_lock("proxmox_vm", "vmid:306") is None
    assert client.calls == []


def test_shutdown_precheck_terminal_job_write_failure_retains_lock_for_common_recovery():
    from app.jobs.runs import get_job_run
    from app.operations.core.domain import OperationActor
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
    from app.operations.recovery.runtime import RecoveryRuntimeConfig, build_recovery_coordinator
    from app.operations.target_lock import get_target_operation_lock
    from app.operations.vm_shutdown.domain import build_vm_shutdown_job_id
    from app.vm_actions import shutdown as shutdown_module

    idempotency_key = "shutdown-precheck-terminal-job-write-failure"
    operation_id = build_vm_shutdown_job_id(
        node_id="node-a",
        vmid=306,
        idempotency_key=idempotency_key,
    )
    original_record_job_run = shutdown_module.record_job_run

    def fail_blocked_projection(**kwargs):
        if kwargs.get("status") == "blocked":
            raise RuntimeError("blocked shutdown job projection unavailable")
        return original_record_job_run(**kwargs)

    client = ShutdownClient()
    with patch("app.vm_actions.shutdown.record_job_run", side_effect=fail_blocked_projection):
        with pytest.raises(RuntimeError, match="blocked shutdown job projection unavailable"):
            run_shutdown(
                client=client,
                inventory=Inventory(status="stopped"),
                payload={
                    "vm_shutdown_acknowledged": True,
                    "idempotency_key": idempotency_key,
                    "expected_name": "app",
                },
            )

    operation_store = SqlAlchemyOperationStore()
    operation = operation_store.get(operation_id)
    assert operation is not None
    assert operation.status == "blocked"
    assert operation.details["pre_dispatch_terminal_no_effect"] is True
    assert get_job_run(operation_id)["status"] == "running"
    assert SqlAlchemyRecoveryStore().get(operation_id) is None
    assert get_target_operation_lock("proxmox_vm", "vmid:306")["owner_id"] == operation_id
    assert client.calls == []

    recovered = build_recovery_coordinator(
        config=RecoveryRuntimeConfig(enabled=True, poll_seconds=5, lease_seconds=60)
    ).observe(
        operation_id,
        actor=OperationActor(user_id="operator-1", username="operator", role="operator"),
        expected_version=operation.version,
        expected_checksum=operation.last_event_checksum,
        idempotency_key="observe-shutdown-precheck-job-write-failure",
    )

    assert recovered["outcome"] == "blocked"
    assert get_job_run(operation_id)["status"] == "blocked"
    assert SqlAlchemyRecoveryStore().get(operation_id).status == "completed"
    assert get_target_operation_lock("proxmox_vm", "vmid:306") is None
    assert client.calls == []


def test_shutdown_success_records_operation_recovery_artifact_and_releases_lock():
    from app.jobs.artifacts import read_artifact_text
    from app.jobs.runs import get_job_run
    from app.operations.core.domain import verify_event_chain
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
    from app.operations.target_lock import get_target_operation_lock

    client = ShutdownClient()
    response = run_shutdown(client=client)
    result = response["data"]

    assert response["meta"]["mode"] == "proxmox_native_vm_shutdown"
    assert result["status"] == "completed"
    assert result["forced_stop_enabled"] is False
    assert [call[0] for call in client.calls] == ["shutdown_vm", "wait_for_task", "get_vm_status"]
    artifact = json.loads(read_artifact_text(result["observed_after_artifact"]))
    assert artifact["operation"] == "vm_shutdown"
    assert artifact["evidence"]["forced_stop_enabled"] is False
    assert artifact["evidence"]["connection"] == {}
    assert artifact["evidence"]["observation_kinds"] == [
        "vm_shutdown",
        "task_status",
        "vm_status",
    ]
    assert "polls" not in artifact["task"]
    assert "polls" not in result["task"]
    serialized_artifact = json.dumps(artifact, sort_keys=True)
    assert "pve.example.test" not in serialized_artifact
    assert "token_secret" not in serialized_artifact
    assert "/nodes/" not in serialized_artifact
    job = get_job_run(result["job_id"])
    assert job["job_type"] == "vm_shutdown"
    assert job["status"] == "completed"
    operations = SqlAlchemyOperationStore()
    operation = operations.get(result["job_id"])
    events = operations.list_events(result["job_id"])
    assert operation.status == "succeeded"
    assert operation.operation_type == "vm_shutdown"
    assert [event.event_type for event in events] == [
        "operation_created",
        "dispatch_prepared",
        "dispatch_accepted",
        "task_and_state_observed",
        "verification_succeeded",
        "recovery_compatibility_projection_recorded",
    ]
    assert verify_event_chain(events)
    recovery = SqlAlchemyRecoveryStore().get(result["job_id"])
    assert recovery.status == "completed"
    assert "polls" not in recovery.details["task"]
    assert recovery.details["observed_after"]["status"] == "stopped"
    assert get_target_operation_lock("proxmox_vm", "vmid:306") is None


def test_shutdown_same_intent_replay_does_not_post_twice():
    client = ShutdownClient()
    payload = {
        "vm_shutdown_acknowledged": True,
        "idempotency_key": "shutdown-replay",
        "expected_name": "app",
        "expected_status": "running",
    }

    first = run_shutdown(client=client, payload=payload)
    second = run_shutdown(client=client, payload=payload)

    assert first["data"]["job_id"] == second["data"]["job_id"]
    assert second["data"]["idempotent_replay"] is True
    assert [call[0] for call in client.calls].count("shutdown_vm") == 1


def test_shutdown_same_key_with_different_intent_is_conflict_without_second_post():
    client = ShutdownClient()
    first_payload = {
        "vm_shutdown_acknowledged": True,
        "idempotency_key": "shutdown-intent-conflict",
        "expected_name": "app",
        "expected_status": "running",
    }
    run_shutdown(client=client, payload=first_payload)

    with pytest.raises(HTTPException) as raised:
        run_shutdown(client=client, payload={**first_payload, "expected_name": "different-app"})

    assert raised.value.detail["code"] == "VM_SHUTDOWN_IDEMPOTENCY_CONFLICT"
    assert [call[0] for call in client.calls].count("shutdown_vm") == 1


def test_shutdown_is_blocked_by_existing_vm_start_target_lock_before_post():
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.vm_shutdown.domain import build_vm_shutdown_job_id
    from app.operations.target_lock import acquire_target_operation_lock, release_target_operation_lock

    lock = acquire_target_operation_lock(
        "proxmox_vm",
        "vmid:306",
        "existing-vm-start",
        operation_type="vm_start",
    )
    client = ShutdownClient()
    idempotency_key = "shutdown-cross-action-lock"
    operation_id = build_vm_shutdown_job_id(node_id="node-a", vmid=306, idempotency_key=idempotency_key)
    try:
        with pytest.raises(HTTPException) as raised:
            run_shutdown(
                client=client,
                payload={
                    "vm_shutdown_acknowledged": True,
                    "idempotency_key": idempotency_key,
                    "expected_name": "app",
                    "expected_status": "running",
                },
            )
    finally:
        release_target_operation_lock(lock)

    assert raised.value.detail["code"] == "VM_SHUTDOWN_TARGET_LOCK_BUSY"
    assert raised.value.detail["operation_id"] == operation_id
    assert raised.value.detail["conflicting_operation_id"] == "existing-vm-start"
    operation_store = SqlAlchemyOperationStore()
    operation = operation_store.get(operation_id)
    events = operation_store.list_events(operation_id)
    assert operation.status == "blocked"
    assert operation.current_stage == "precheck"
    assert operation.details["conflicting_operation_id"] == "existing-vm-start"
    assert operation.details["target_operation_lock"]["existing"]["owner_id"] == "existing-vm-start"
    assert events[-1].event_type == "target_lock_blocked"
    assert events[-1].from_status == "planned"
    assert events[-1].to_status == "blocked"
    assert events[-1].payload["conflicting_operation_id"] == "existing-vm-start"
    assert raised.value.detail["target_operation_lock"]["existing"]["operation_type"] == "vm_start"
    assert client.calls == []


def test_shutdown_same_operation_target_lock_collision_is_in_progress_without_blocking_owner():
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.target_lock import (
        acquire_target_operation_lock,
        get_target_operation_lock,
        release_target_operation_lock,
    )
    from app.operations.vm_shutdown.domain import build_vm_shutdown_job_id

    idempotency_key = "shutdown-same-owner-target-lock"
    operation_id = build_vm_shutdown_job_id(
        node_id="node-a",
        vmid=306,
        idempotency_key=idempotency_key,
    )
    owner_lock = acquire_target_operation_lock(
        "proxmox_vm",
        "vmid:306",
        operation_id,
        operation_type="vm_shutdown",
    )
    client = ShutdownClient()
    try:
        with pytest.raises(HTTPException) as raised:
            run_shutdown(
                client=client,
                payload={
                    "vm_shutdown_acknowledged": True,
                    "idempotency_key": idempotency_key,
                    "expected_name": "app",
                    "expected_status": "running",
                },
            )

        assert raised.value.status_code == 409
        assert raised.value.detail["code"] == "VM_SHUTDOWN_IN_PROGRESS"
        operation_store = SqlAlchemyOperationStore()
        operation = operation_store.get(operation_id)
        assert operation.status == "planned"
        assert [event.event_type for event in operation_store.list_events(operation_id)] == ["operation_created"]
        assert get_target_operation_lock("proxmox_vm", "vmid:306")["owner_id"] == operation_id
        assert client.calls == []
    finally:
        release_target_operation_lock(owner_lock)


def test_shutdown_recovery_registration_failure_blocks_before_post():
    client = ShutdownClient()
    with patch(
        "app.vm_actions.shutdown.SqlAlchemyRecoveryStore.prepare_and_claim",
        side_effect=RuntimeError("database unavailable"),
    ):
        with pytest.raises(HTTPException) as raised:
            run_shutdown(client=client, payload={
                "vm_shutdown_acknowledged": True,
                "idempotency_key": "shutdown-recovery-failure",
                "expected_name": "app",
                "expected_status": "running",
            })

    assert raised.value.status_code == 503
    assert raised.value.detail["code"] == "VM_SHUTDOWN_RECOVERY_UNAVAILABLE"
    assert client.calls == []

    from app.jobs.runs import get_job_run
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore

    job = get_job_run(raised.value.detail["job_id"])
    assert job["status"] == "failed"
    operation_store = SqlAlchemyOperationStore()
    operation = operation_store.get(raised.value.detail["job_id"])
    assert operation.status == "failed"
    assert operation.details["pre_dispatch_terminal_no_effect"] is True
    assert operation.details["mutation_dispatched"] is False
    assert operation.details["pre_dispatch_terminal_reason"] == "recovery_registration_failed"
    assert operation.details["target_lock_id"].startswith("operation-lock-")
    assert operation.details["cluster_id"] == "gjallar-mvp"
    assert operation_store.list_events(operation.operation_id)[-1].payload["target_lock_id"] == (
        operation.details["target_lock_id"]
    )





def test_shutdown_recovery_registration_operation_write_failure_retains_lock_until_replay_closes():
    from app.jobs.runs import get_job_run
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
    from app.operations.target_lock import get_target_operation_lock
    from app.operations.vm_shutdown.domain import build_vm_shutdown_job_id

    client = ShutdownClient()
    payload = {
        "vm_shutdown_acknowledged": True,
        "idempotency_key": "shutdown-recovery-operation-write-failure",
        "expected_name": "app",
        "expected_status": "running",
    }
    with patch(
        "app.vm_actions.shutdown.SqlAlchemyRecoveryStore.prepare_and_claim",
        side_effect=RuntimeError("recovery database unavailable"),
    ), patch(
        "app.vm_actions.shutdown.SqlAlchemyOperationStore.transition_pre_dispatch_failure",
        side_effect=RuntimeError("shutdown operation transition unavailable"),
    ):
        with pytest.raises(RuntimeError, match="shutdown operation transition unavailable"):
            run_shutdown(client=client, payload=payload)

    job_id = build_vm_shutdown_job_id(node_id="node-a", vmid=306, idempotency_key=payload["idempotency_key"])
    operation_store = SqlAlchemyOperationStore()
    job = get_job_run(job_id)
    assert job["status"] == "failed"
    assert job["details"]["vm_shutdown_result"]["pre_dispatch_no_effect_verified"] is True
    assert operation_store.get(job_id).status == "planned"
    assert get_target_operation_lock("proxmox_vm", "vmid:306")["owner_id"] == job_id
    assert client.calls == []

    replay = run_shutdown(client=client, payload=payload)

    assert replay["data"]["idempotent_replay"] is True
    assert replay["data"]["status"] == "failed"
    operation = operation_store.get(job_id)
    assert operation.status == "failed"
    assert operation.details["recovered_pre_dispatch"] is True
    assert operation_store.list_events(job_id)[-1].event_type == "replayed_pre_dispatch_failure_closed"
    assert SqlAlchemyRecoveryStore().get(job_id).status == "completed"
    assert get_target_operation_lock("proxmox_vm", "vmid:306") is None
    assert client.calls == []





def test_shutdown_missing_mutation_client_is_failed_without_post_or_retained_lock():
    from app.api.v1 import vm_actions as router
    from app.jobs.runs import get_job_run
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.target_lock import get_target_operation_lock

    with patch.object(router.inventory_context, "mutation_inventory_adapter", return_value=Inventory()), patch.object(
        router,
        "get_default_proxmox_mutation_client",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as raised:
            asyncio.run(
                router.shutdown_vm_action(
                    "node-a",
                    306,
                    {
                        "vm_shutdown_acknowledged": True,
                        "idempotency_key": "shutdown-missing-client",
                        "expected_name": "app",
                        "expected_status": "running",
                    },
                )
            )

    assert raised.value.status_code == 503
    assert raised.value.detail["code"] == "VM_SHUTDOWN_CLIENT_UNAVAILABLE"
    job = get_job_run(raised.value.detail["job_id"])
    assert job["status"] == "failed"
    operation_store = SqlAlchemyOperationStore()
    operation = operation_store.get(raised.value.detail["job_id"])
    assert operation.status == "failed"
    assert operation.details["pre_dispatch_terminal_no_effect"] is True
    assert operation.details["mutation_dispatched"] is False
    assert operation.details["pre_dispatch_terminal_reason"] == "mutation_client_unavailable"
    assert operation.details["target_lock_id"].startswith("operation-lock-")
    assert operation.details["cluster_id"] == "gjallar-mvp"
    assert operation_store.list_events(operation.operation_id)[-1].payload["target_lock_id"] == (
        operation.details["target_lock_id"]
    )
    assert get_target_operation_lock("proxmox_vm", "vmid:306") is None


def test_shutdown_recovery_lease_loss_after_post_retains_lock_and_never_claims_success():
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.recovery.domain import RecoveryLeaseLost
    from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
    from app.operations.target_lock import get_target_operation_lock

    client = ShutdownClient()
    original_commit = SqlAlchemyRecoveryStore.commit_observation

    def lose_lease_after_post(store, lease, **kwargs):
        if kwargs.get("event_type") == "dispatch_accepted":
            raise RecoveryLeaseLost("shutdown-lease-lost")
        return original_commit(store, lease, **kwargs)

    with patch.object(SqlAlchemyRecoveryStore, "commit_observation", new=lose_lease_after_post):
        with pytest.raises(HTTPException) as raised:
            run_shutdown(
                client=client,
                payload={
                    "vm_shutdown_acknowledged": True,
                    "idempotency_key": "shutdown-lease-lost",
                    "expected_name": "app",
                    "expected_status": "running",
                },
            )

    assert raised.value.status_code == 503
    assert raised.value.detail["code"] == "VM_SHUTDOWN_RECOVERY_LEASE_LOST"
    assert [call[0] for call in client.calls] == ["shutdown_vm"]
    operation = SqlAlchemyOperationStore().get(raised.value.detail["job_id"])
    assert operation.status == "dispatching"
    assert get_target_operation_lock("proxmox_vm", "vmid:306") is not None


def test_missing_upid_is_reconciliation_and_retains_cross_action_lock():
    from app.operations.target_lock import get_target_operation_lock

    client = ShutdownClient(upid="")
    payload = {
        "vm_shutdown_acknowledged": True,
        "idempotency_key": "shutdown-missing-upid",
        "expected_name": "app",
        "expected_status": "running",
    }
    with pytest.raises(HTTPException) as raised:
        run_shutdown(client=client, payload=payload)

    assert raised.value.detail["code"] == "VM_SHUTDOWN_REQUEST_RECONCILIATION_REQUIRED"
    lock = get_target_operation_lock("proxmox_vm", "vmid:306")
    assert lock is not None and lock["durable"]["operation_type"] == "vm_shutdown"
    with pytest.raises(HTTPException) as blocked:
        run_shutdown(
            client=ShutdownClient(),
            payload={
                **payload,
                "idempotency_key": "shutdown-blocked-by-retained-lock",
            },
        )
    assert blocked.value.detail["code"] == "VM_SHUTDOWN_TARGET_LOCK_BUSY"
    assert [call[0] for call in client.calls].count("shutdown_vm") == 1


def test_invalid_upid_is_not_persisted_or_used_for_task_observation():
    from app.jobs.runs import get_job_run
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore

    opaque_locator = "opaque-secret?token=do-not-store"
    client = ShutdownClient(upid=opaque_locator)
    with pytest.raises(HTTPException) as raised:
        run_shutdown(
            client=client,
            payload={
                "vm_shutdown_acknowledged": True,
                "idempotency_key": "shutdown-invalid-upid",
                "expected_name": "app",
                "expected_status": "running",
            },
        )

    operation_id = raised.value.detail["job_id"]
    operation_store = SqlAlchemyOperationStore()
    serialized = json.dumps(
        {
            "detail": raised.value.detail,
            "job": get_job_run(operation_id),
            "operation": operation_store.get(operation_id).details,
            "events": [event.payload for event in operation_store.list_events(operation_id)],
        },
        sort_keys=True,
    )
    assert raised.value.detail["code"] == "VM_SHUTDOWN_REQUEST_RECONCILIATION_REQUIRED"
    assert opaque_locator not in serialized
    assert "wait_for_task" not in [call[0] for call in client.calls]


def test_shutdown_task_or_direct_state_mismatch_never_succeeds_or_unlocks():
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.target_lock import get_target_operation_lock

    client = ShutdownClient(observed_status="running")
    with pytest.raises(HTTPException) as raised:
        run_shutdown(
            client=client,
            payload={
                "vm_shutdown_acknowledged": True,
                "idempotency_key": "shutdown-post-check-mismatch",
                "expected_name": "app",
                "expected_status": "running",
            },
        )

    assert raised.value.detail["code"] == "VM_SHUTDOWN_RESULT_RECONCILIATION_REQUIRED"
    operation = SqlAlchemyOperationStore().get(raised.value.detail["job_id"])
    assert operation.status == "needs_reconciliation"
    assert get_target_operation_lock("proxmox_vm", "vmid:306") is not None


def test_shutdown_artifact_write_failure_returns_stable_recoverable_503_without_recreating_artifact():
    from app.jobs.runs import get_job_run
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.facade import get_operation
    from app.operations.recovery.application import VmShutdownRecoveryHandler
    from app.operations.recovery.infrastructure.job_projection import SqlAlchemyVmShutdownRecoveryJobProjection
    from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
    from app.operations.target_lock import get_target_operation_lock

    client = ShutdownClient()
    with patch("app.vm_actions.shutdown.write_json_artifact", side_effect=RuntimeError("artifact write failed")):
        with pytest.raises(HTTPException) as raised:
            run_shutdown(
                client=client,
                payload={
                    "vm_shutdown_acknowledged": True,
                    "idempotency_key": "shutdown-artifact-write-failed",
                    "expected_name": "app",
                    "expected_status": "running",
                },
            )

    detail = raised.value.detail
    operation_id = detail["operation_id"]
    assert raised.value.status_code == 503
    assert detail["code"] == "VM_SHUTDOWN_OBSERVED_EVIDENCE_PERSISTENCE_UNAVAILABLE"
    assert detail["job_id"] == operation_id
    assert detail["operation_status"] == "needs_reconciliation"
    assert detail["recovery_status"] == "retry_wait"
    assert detail["evidence_status"] == "persistence_failed"
    assert detail["evidence_recorded"] is False
    assert detail["observed_after_artifact"] == {}
    assert detail["target"] == {"node_id": "node-a", "vmid": 306, "name": "app"}
    assert detail["side_effects"] == [
        "proxmox_shutdown_invoked",
        "proxmox_task_polled",
        "proxmox_post_check_observed",
    ]
    operation_store = SqlAlchemyOperationStore()
    recovery_store = SqlAlchemyRecoveryStore()
    assert operation_store.get(operation_id).status == "needs_reconciliation"
    assert recovery_store.get(operation_id).status == "retry_wait"
    assert get_operation(operation_id)["recovery_available_actions"][0]["action"] == "observe"
    assert get_target_operation_lock("proxmox_vm", "vmid:306")["owner_id"] == operation_id
    assert [call[0] for call in client.calls].count("shutdown_vm") == 1

    class GetOnlyObservation:
        def __init__(self):
            self.calls = []

        def get_task_status(self, *, node, upid):
            self.calls.append(("get_task_status", node, upid))
            return {"node": node, "upid": upid, "status": "stopped", "exitstatus": "OK"}

        def get_vm_status(self, *, node, vmid):
            self.calls.append(("get_vm_status", node, vmid))
            return {"node_id": node, "vmid": vmid, "name": "app", "status": "stopped"}

    observation = GetOnlyObservation()
    lease = recovery_store.claim_due(lease_owner="shutdown-artifact-recovery", lease_seconds=60)[0]
    recovered = VmShutdownRecoveryHandler(
        recovery=recovery_store,
        operations=operation_store,
        observation_factory=lambda: observation,
        compatibility_projection=SqlAlchemyVmShutdownRecoveryJobProjection(),

        target_lock_reader=get_target_operation_lock,
    ).handle(lease)

    assert recovered.outcome == "succeeded"
    assert [call[0] for call in observation.calls] == ["get_task_status", "get_vm_status"]
    assert recovery_store.get(operation_id).status == "completed"
    assert get_target_operation_lock("proxmox_vm", "vmid:306") is None
    assert all(
        artifact["type"] != "vm_shutdown_observed_after"
        for artifact in get_job_run(operation_id)["artifacts"]
    )


def test_shutdown_completed_job_projection_failure_returns_stable_503_and_retains_lock():
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.facade import get_operation
    from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
    from app.operations.target_lock import get_target_operation_lock
    from app.operations.vm_shutdown.domain import build_vm_shutdown_job_id
    from app.vm_actions import shutdown as shutdown_module

    idempotency_key = "shutdown-completed-job-projection-failed"
    operation_id = build_vm_shutdown_job_id(node_id="node-a", vmid=306, idempotency_key=idempotency_key)
    original_record_job_run = shutdown_module.record_job_run

    def fail_completed_projection(**kwargs):
        if kwargs.get("status") == "completed":
            raise RuntimeError("shutdown completed job projection unavailable")
        return original_record_job_run(**kwargs)

    client = ShutdownClient()
    with patch("app.vm_actions.shutdown.record_job_run", side_effect=fail_completed_projection):
        with pytest.raises(HTTPException) as raised:
            run_shutdown(
                client=client,
                payload={
                    "vm_shutdown_acknowledged": True,
                    "idempotency_key": idempotency_key,
                    "expected_name": "app",
                    "expected_status": "running",
                },
            )

    detail = raised.value.detail
    assert raised.value.status_code == 503
    assert detail["code"] == "VM_SHUTDOWN_COMPATIBILITY_PROJECTION_PERSISTENCE_UNAVAILABLE"
    assert detail["operation_id"] == operation_id
    assert detail["job_id"] == operation_id
    assert detail["operation_status"] == "succeeded"
    assert detail["recovery_status"] == "retry_wait"
    assert detail["evidence_status"] == "recorded"
    assert detail["evidence_recorded"] is True
    assert detail["observed_after_artifact"]["artifact_id"]
    assert detail["side_effects"] == [
        "proxmox_shutdown_invoked",
        "proxmox_task_polled",
        "proxmox_post_check_observed",
    ]
    assert SqlAlchemyOperationStore().get(operation_id).status == "succeeded"
    assert SqlAlchemyRecoveryStore().get(operation_id).status == "retry_wait"
    assert get_operation(operation_id)["recovery_available_actions"][0]["action"] == "observe"
    assert get_target_operation_lock("proxmox_vm", "vmid:306")["owner_id"] == operation_id
    assert [call[0] for call in client.calls].count("shutdown_vm") == 1


def test_shutdown_projection_failure_secondary_recovery_write_still_returns_exact_stable_503():
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
    from app.operations.target_lock import get_target_operation_lock
    from app.operations.vm_shutdown.domain import build_vm_shutdown_job_id
    from app.vm_actions import shutdown as shutdown_module

    idempotency_key = "shutdown-projection-secondary-recovery-failed"
    operation_id = build_vm_shutdown_job_id(node_id="node-a", vmid=306, idempotency_key=idempotency_key)
    original_record_job_run = shutdown_module.record_job_run
    original_commit = SqlAlchemyRecoveryStore.commit_observation

    def fail_completed_projection(**kwargs):
        if kwargs.get("status") == "completed":
            raise RuntimeError("shutdown completed job projection unavailable")
        return original_record_job_run(**kwargs)

    def fail_handoff_commit(store, lease, **kwargs):
        if kwargs.get("event_type") == "compatibility_projection_persistence_failed":
            raise RuntimeError("secondary recovery handoff unavailable")
        return original_commit(store, lease, **kwargs)

    client = ShutdownClient()
    with patch.object(SqlAlchemyRecoveryStore, "commit_observation", new=fail_handoff_commit), patch(
        "app.vm_actions.shutdown.record_job_run",
        side_effect=fail_completed_projection,
    ):
        with pytest.raises(HTTPException) as raised:
            run_shutdown(
                client=client,
                payload={
                    "vm_shutdown_acknowledged": True,
                    "idempotency_key": idempotency_key,
                    "expected_name": "app",
                    "expected_status": "running",
                },
            )

    detail = raised.value.detail
    assert raised.value.status_code == 503
    assert detail["code"] == "VM_SHUTDOWN_COMPATIBILITY_PROJECTION_PERSISTENCE_UNAVAILABLE"
    assert detail["operation_id"] == operation_id
    assert detail["job_id"] == operation_id
    assert detail["operation_status"] == "succeeded"
    assert detail["recovery_status"] == "leased"
    assert detail["evidence_status"] == "recorded"
    assert SqlAlchemyOperationStore().get(operation_id).status == "succeeded"
    assert SqlAlchemyRecoveryStore().get(operation_id).status == "leased"
    assert get_target_operation_lock("proxmox_vm", "vmid:306")["owner_id"] == operation_id
    assert [call[0] for call in client.calls].count("shutdown_vm") == 1


def test_explicit_non_ambiguous_rejection_is_failed_without_forced_fallback():
    from app.operations.target_lock import get_target_operation_lock

    client = ShutdownClient(
        error=ProxmoxMutationError(
            "permission denied",
            details={
                "status_code": 403,
                "method": "POST",
                "path": "/nodes/customer-node/qemu/306/status/shutdown",
                "response_text": "opaque-customer-value",
                "response_json": {
                    "errors": {"description": "opaque-customer-description"},
                },
            },
        )
    )
    with pytest.raises(HTTPException) as raised:
        run_shutdown(
            client=client,
            payload={
                "vm_shutdown_acknowledged": True,
                "idempotency_key": "shutdown-rejected",
                "expected_name": "app",
                "expected_status": "running",
            },
        )

    assert raised.value.detail["code"] == "VM_SHUTDOWN_REQUEST_FAILED"
    serialized_detail = json.dumps(raised.value.detail, sort_keys=True)
    assert "opaque-customer-value" not in serialized_detail
    assert "opaque-customer-description" not in serialized_detail
    assert "/nodes/customer-node" not in serialized_detail
    assert raised.value.detail["task"]["details"] == {
        "status_code": 403,
        "method": "POST",
        "invalid_fields": ["description"],
    }
    assert [call[0] for call in client.calls] == ["shutdown_vm"]
    assert get_target_operation_lock("proxmox_vm", "vmid:306") is None


def test_shutdown_rejection_projection_failure_keeps_recovery_retryable_until_handler_finishes():
    from app.jobs.runs import get_job_run
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.recovery.application import VmShutdownRecoveryHandler
    from app.operations.recovery.infrastructure.job_projection import SqlAlchemyVmShutdownRecoveryJobProjection
    from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
    from app.operations.target_lock import get_target_operation_lock
    from app.operations.vm_shutdown.domain import build_vm_shutdown_job_id
    from app.vm_actions import shutdown as shutdown_module

    idempotency_key = "shutdown-rejection-projection-failed"
    operation_id = build_vm_shutdown_job_id(
        node_id="node-a",
        vmid=306,
        idempotency_key=idempotency_key,
    )
    original_record_job_run = shutdown_module.record_job_run

    def fail_failed_projection(**kwargs):
        if kwargs.get("status") == "failed":
            raise RuntimeError("shutdown failed job projection unavailable")
        return original_record_job_run(**kwargs)

    client = ShutdownClient(
        error=ProxmoxMutationError(
            "permission denied",
            details={"status_code": 403, "method": "POST", "path": "/status/shutdown"},
        )
    )
    with patch("app.vm_actions.shutdown.record_job_run", side_effect=fail_failed_projection):
        with pytest.raises(HTTPException) as raised:
            run_shutdown(
                client=client,
                payload={
                    "vm_shutdown_acknowledged": True,
                    "idempotency_key": idempotency_key,
                    "expected_name": "app",
                    "expected_status": "running",
                },
            )

    assert raised.value.status_code == 503
    assert raised.value.detail["code"] == "VM_SHUTDOWN_COMPATIBILITY_PROJECTION_PERSISTENCE_UNAVAILABLE"
    assert raised.value.detail["operation_id"] == operation_id
    assert raised.value.detail["job_id"] == operation_id
    assert raised.value.detail["operation_status"] == "failed"
    assert raised.value.detail["recovery_status"] == "retry_wait"
    assert raised.value.detail["evidence_status"] == "not_required"
    assert raised.value.detail["evidence_recorded"] is False
    assert raised.value.detail["side_effects"] == ["proxmox_shutdown_request_rejected"]

    operation_store = SqlAlchemyOperationStore()
    recovery_store = SqlAlchemyRecoveryStore()
    assert operation_store.get(operation_id).status == "failed"
    assert recovery_store.get(operation_id).status == "retry_wait"
    assert get_job_run(operation_id)["status"] == "running"
    assert operation_store.list_events(operation_id)[-1].event_type == "compatibility_projection_persistence_failed"
    assert get_target_operation_lock("proxmox_vm", "vmid:306")["owner_id"] == operation_id
    assert [call[0] for call in client.calls] == ["shutdown_vm"]

    lease = recovery_store.claim_due(lease_owner="shutdown-recovery-test", lease_seconds=60)[0]
    handler = VmShutdownRecoveryHandler(
        recovery=recovery_store,
        operations=operation_store,
        observation_factory=lambda: pytest.fail("terminal rejection recovery must not observe Proxmox"),
        compatibility_projection=SqlAlchemyVmShutdownRecoveryJobProjection(),

        target_lock_reader=get_target_operation_lock,
    )

    recovered = handler.handle(lease)

    assert recovered.outcome == "failed"
    assert get_job_run(operation_id)["status"] == "failed"
    assert recovery_store.get(operation_id).status == "completed"
    assert get_target_operation_lock("proxmox_vm", "vmid:306") is None


def test_shutdown_ignores_and_preserves_old_request_lock_file(tmp_path):
    from app.operations.vm_shutdown.domain import build_vm_shutdown_job_id

    payload = {"vm_shutdown_acknowledged": True, "idempotency_key": "shutdown-old-file"}
    job_id = build_vm_shutdown_job_id(node_id="node-a", vmid=306, idempotency_key=payload["idempotency_key"])
    directory = tmp_path / job_id
    directory.mkdir()
    old_lock = directory / "vm_shutdown.lock"
    old_lock.write_bytes(b"old worker evidence")
    client = ShutdownClient()

    with patch("app.vm_actions.shutdown.run_dir", return_value=directory):
        first = run_shutdown(client=client, payload=payload)
        replay = run_shutdown(client=client, payload=payload)

    assert first["data"]["status"] == "completed"
    assert replay["data"]["idempotent_replay"] is True
    assert [call[0] for call in client.calls].count("shutdown_vm") == 1
    assert old_lock.read_bytes() == b"old worker evidence"


def test_shutdown_rechecks_job_when_predecessor_finishes_after_first_lookup():
    from app.jobs.runs import get_job_run
    from app.vm_actions.shutdown import run_vm_shutdown

    client = ShutdownClient()
    payload = {"vm_shutdown_acknowledged": True, "idempotency_key": "shutdown-first-lookup-race"}
    first_lookup = True

    def get_after_predecessor_finishes(job_id):
        nonlocal first_lookup
        snapshot = get_job_run(job_id)
        if first_lookup:
            first_lookup = False
            run_vm_shutdown(node_id="node-a", vmid=306, payload=payload, inventory_adapter=Inventory(), client=client)
        return snapshot

    with patch("app.vm_actions.shutdown.get_job_run", side_effect=get_after_predecessor_finishes):
        result = run_shutdown(client=client, payload=payload)

    assert result["data"]["status"] == "completed"
    assert result["data"]["idempotent_replay"] is True
    assert [call[0] for call in client.calls].count("shutdown_vm") == 1


def test_shutdown_rechecks_completed_projection_after_target_lock_acquisition():
    from app.jobs.runs import get_job_run, record_job_run
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.vm_shutdown.domain import VmShutdownCommand
    from app.operations.target_lock import acquire_target_operation_lock

    payload = {"vm_shutdown_acknowledged": True, "idempotency_key": "shutdown-target-acquire-race"}
    command = VmShutdownCommand.from_request(node_id="node-a", vmid=306, payload=payload, actor=None)
    client = ShutdownClient()
    saved_job = None

    def finish_predecessor_then_acquire(target_type, target_id, operation_id, **kwargs):
        nonlocal saved_job
        store = SqlAlchemyOperationStore()
        for status in ("dispatching", "running", "verifying", "succeeded"):
            store.transition(operation_id, next_status=status, event_type="predecessor_progress", stage="shutdown")
        saved_job = record_job_run(
            job_id=operation_id,
            job_type="vm_shutdown",
            status="completed",
            stage="post_check",
            step_status="completed",
            message="Predecessor completed shutdown.",
            target_id="node-a:306:app",
            risk_level="high",
            details={
                "vm_shutdown_intent": command.stable_intent,
                "vm_shutdown_result": {"proxmox_mutation_enabled": True, "proxmox_shutdown_ran": True},
            },
        )
        return acquire_target_operation_lock(target_type, target_id, operation_id, **kwargs)

    with patch("app.vm_actions.shutdown.acquire_target_operation_lock", side_effect=finish_predecessor_then_acquire):
        result = run_shutdown(client=client, payload=payload)

    assert result["data"]["status"] == "completed"
    assert result["data"]["idempotent_replay"] is True
    assert get_job_run(saved_job["job_id"]) == saved_job
    assert client.calls == []


def test_shutdown_foreign_busy_transition_race_returns_stable_conflict():
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.target_lock import acquire_target_operation_lock, release_target_operation_lock

    foreign = acquire_target_operation_lock("proxmox_vm", "vmid:306", "foreign-busy-race", operation_type="vm_start")
    client = ShutdownClient()

    transition = SqlAlchemyOperationStore.transition_for_target_lock_conflict

    def concurrent_block(store, operation_id, **kwargs):
        transition(store, operation_id, **kwargs)
        return transition(store, operation_id, **kwargs)

    try:
        with patch.object(SqlAlchemyOperationStore, "transition_for_target_lock_conflict", autospec=True, side_effect=concurrent_block):
            with pytest.raises(HTTPException) as raised:
                run_shutdown(
                    client=client,
                    payload={"vm_shutdown_acknowledged": True, "idempotency_key": "shutdown-busy-transition-race"},
                )
        assert raised.value.status_code == 409
        assert raised.value.detail["code"] == "VM_SHUTDOWN_TARGET_LOCK_BUSY"
        operation_id = raised.value.detail["operation_id"]
        store = SqlAlchemyOperationStore()
        assert store.get(operation_id).status == "blocked"
        assert [event.event_type for event in store.list_events(operation_id)].count("target_lock_blocked") == 1
        assert client.calls == []
    finally:
        release_target_operation_lock(foreign)


def test_shutdown_stale_foreign_busy_does_not_block_new_same_operation_owner():
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.target_lock import (
        acquire_target_operation_lock,
        get_target_operation_lock,
        release_target_operation_lock,
    )

    foreign = acquire_target_operation_lock("proxmox_vm", "vmid:306", "foreign-retired", operation_type="vm_start")
    transition = SqlAlchemyOperationStore.transition_for_target_lock_conflict
    successor = None
    client = ShutdownClient()

    def replace_foreign_before_conflict_transition(store, operation_id, **kwargs):
        nonlocal successor
        release_target_operation_lock(foreign)
        successor = acquire_target_operation_lock("proxmox_vm", "vmid:306", operation_id, operation_type="vm_shutdown")
        return transition(store, operation_id, **kwargs)

    try:
        with patch.object(
            SqlAlchemyOperationStore,
            "transition_for_target_lock_conflict",
            autospec=True,
            side_effect=replace_foreign_before_conflict_transition,
        ):
            with pytest.raises(HTTPException) as raised:
                run_shutdown(
                    client=client,
                    payload={"vm_shutdown_acknowledged": True, "idempotency_key": "shutdown-stale-foreign-owner"},
                )
        assert raised.value.detail["code"] == "VM_SHUTDOWN_TARGET_LOCK_BUSY"
        operation_id = raised.value.detail["operation_id"]
        store = SqlAlchemyOperationStore()
        assert store.get(operation_id).status == "planned"
        assert [event.event_type for event in store.list_events(operation_id)] == ["operation_created"]
        assert get_target_operation_lock("proxmox_vm", "vmid:306")["owner_id"] == operation_id
        assert client.calls == []
    finally:
        release_target_operation_lock(foreign)
        if successor is not None:
            release_target_operation_lock(successor)


@pytest.mark.parametrize("failure", ["missing_client", "client_error", "recovery_unavailable"])
def test_shutdown_pre_dispatch_failed_projection_replay_cannot_race_terminal_write(failure):
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
    from app.operations.target_lock import get_target_operation_lock
    from app.operations.vm_shutdown.errors import VmShutdownError
    from app.vm_actions import shutdown as shutdown_module

    payload = {"vm_shutdown_acknowledged": True, "idempotency_key": "shutdown-terminal-projection-race"}
    client = ShutdownClient()
    original_record = shutdown_module.record_job_run
    original_prepare = SqlAlchemyRecoveryStore.prepare_and_claim
    replay = None

    def record_then_replay(**kwargs):
        nonlocal replay
        job = original_record(**kwargs)
        if kwargs.get("status") == "failed":
            replay = shutdown_module.run_vm_shutdown(
                node_id="node-a", vmid=306, payload=payload, inventory_adapter=Inventory(), client=client,
            )
        return job

    def prepare(store, spec, **kwargs):
        if failure == "recovery_unavailable" and kwargs["lease_owner"].startswith("foreground:"):
            raise RuntimeError("foreground recovery registration unavailable")
        return original_prepare(store, spec, **kwargs)

    def factory():
        if failure == "client_error":
            raise ProxmoxMutationError("client unavailable")
        return None

    with patch.object(shutdown_module, "record_job_run", side_effect=record_then_replay), patch.object(
        SqlAlchemyRecoveryStore, "prepare_and_claim", autospec=True, side_effect=prepare,
    ):
        with pytest.raises(VmShutdownError) as raised:
            shutdown_module.run_vm_shutdown(
                node_id="node-a", vmid=306, payload=payload, inventory_adapter=Inventory(),
                client=client if failure == "recovery_unavailable" else None,
                client_factory=None if failure == "recovery_unavailable" else factory,
            )

    assert raised.value.code == (
        "VM_SHUTDOWN_RECOVERY_UNAVAILABLE" if failure == "recovery_unavailable" else "VM_SHUTDOWN_CLIENT_UNAVAILABLE"
    )
    assert replay["status"] == "failed"
    assert replay["idempotent_replay"] is True
    operation_id = replay["job_id"]
    store = SqlAlchemyOperationStore()
    assert store.get(operation_id).status == "failed"
    assert get_target_operation_lock("proxmox_vm", "vmid:306") is None
    assert client.calls == []


@pytest.mark.parametrize("claim_replay_first", [False, True])
def test_shutdown_pre_dispatch_replay_and_foreground_terminal_are_fenced(claim_replay_first):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
    from app.operations.target_lock import get_target_operation_lock
    from app.operations.vm_shutdown.errors import VmShutdownError
    from app.vm_actions import shutdown as shutdown_module

    payload = {"vm_shutdown_acknowledged": True, "idempotency_key": "shutdown-no-effect-fenced-race"}
    failed_published = Event()
    replay_ready = Event()
    foreground_done = Event()
    original_record = shutdown_module.record_job_run
    original_prepare = SqlAlchemyRecoveryStore.prepare_and_claim

    def record_failed_and_pause(**kwargs):
        job = original_record(**kwargs)
        if kwargs.get("status") == "failed":
            failed_published.set()
            assert replay_ready.wait(5), "replay did not reach its claim boundary"
        return job

    def coordinate_replay_claim(store, spec, **kwargs):
        if not kwargs["lease_owner"].startswith("replay:"):
            return original_prepare(store, spec, **kwargs)
        if claim_replay_first:
            lease = original_prepare(store, spec, **kwargs)
            replay_ready.set()
            assert foreground_done.wait(5), "foreground did not yield to replay ownership"
            return lease
        replay_ready.set()
        assert foreground_done.wait(5), "foreground did not complete its terminal transition"
        return original_prepare(store, spec, **kwargs)

    def foreground():
        try:
            with pytest.raises(VmShutdownError) as raised:
                shutdown_module.run_vm_shutdown(
                    node_id="node-a", vmid=306, payload=payload, inventory_adapter=Inventory(),
                )
            return raised.value
        finally:
            foreground_done.set()

    with patch.object(shutdown_module, "record_job_run", side_effect=record_failed_and_pause), patch.object(
        SqlAlchemyRecoveryStore, "prepare_and_claim", autospec=True, side_effect=coordinate_replay_claim,
    ), patch.object(
        shutdown_module._LockAdapter, "release_target", wraps=shutdown_module._LockAdapter().release_target,
    ) as release_target:
        with ThreadPoolExecutor(max_workers=2) as executor:
            foreground_result = executor.submit(foreground)
            assert failed_published.wait(5), "foreground did not publish its no-effect failure"
            replay_result = executor.submit(
                shutdown_module.run_vm_shutdown,
                node_id="node-a", vmid=306, payload=payload, inventory_adapter=Inventory(),
            )
            error = foreground_result.result(timeout=10)
            replay = replay_result.result(timeout=10)

    assert error.code == "VM_SHUTDOWN_CLIENT_UNAVAILABLE"
    assert replay["status"] == "failed"
    assert replay["idempotent_replay"] is True
    operation_id = replay["job_id"]
    assert SqlAlchemyOperationStore().get(operation_id).status == "failed"
    assert get_target_operation_lock("proxmox_vm", "vmid:306") is None
    recovery = SqlAlchemyRecoveryStore().get(operation_id)
    if claim_replay_first:
        assert recovery.status == "completed"
        release_target.assert_not_called()
    else:
        assert recovery is None
        release_target.assert_called_once()
