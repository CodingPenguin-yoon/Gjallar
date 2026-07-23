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
    with patch.object(router.inventory_context, "inventory_adapter", return_value=inventory), patch.object(
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
    client = ShutdownClient()

    with pytest.raises(HTTPException) as raised:
        run_shutdown(
            client=client,
            inventory=Inventory(status="stopped"),
            payload={
                "vm_shutdown_acknowledged": True,
                "idempotency_key": "shutdown-stopped-precheck",
                "expected_name": "app",
            },
        )

    assert raised.value.detail["code"] == "VM_SHUTDOWN_NON_RUNNING_BLOCKED"
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
    from app.operations.target_lock import acquire_target_operation_lock, release_target_operation_lock

    lock = acquire_target_operation_lock(
        "proxmox_vm",
        "vmid:306",
        "existing-vm-start",
        operation_type="vm_start",
    )
    client = ShutdownClient()
    try:
        with pytest.raises(HTTPException) as raised:
            run_shutdown(
                client=client,
                payload={
                    "vm_shutdown_acknowledged": True,
                    "idempotency_key": "shutdown-cross-action-lock",
                    "expected_name": "app",
                    "expected_status": "running",
                },
            )
    finally:
        release_target_operation_lock(lock)

    assert raised.value.detail["code"] == "VM_SHUTDOWN_TARGET_LOCK_BUSY"
    assert raised.value.detail["target_operation_lock"]["existing"]["operation_type"] == "vm_start"
    assert client.calls == []


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
    assert SqlAlchemyOperationStore().get(raised.value.detail["job_id"]).status == "failed"


def test_shutdown_missing_mutation_client_is_failed_without_post_or_retained_lock():
    from app.api.v1 import vm_actions as router
    from app.jobs.runs import get_job_run
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.target_lock import get_target_operation_lock

    with patch.object(router.inventory_context, "inventory_adapter", return_value=Inventory()), patch.object(
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
    assert SqlAlchemyOperationStore().get(raised.value.detail["job_id"]).status == "failed"
    assert get_target_operation_lock("proxmox_vm", "vmid:306") is None


def test_shutdown_recovery_lease_loss_after_post_retains_lock_and_never_claims_success():
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.recovery.domain import RecoveryLeaseLost
    from app.operations.target_lock import get_target_operation_lock

    client = ShutdownClient()
    with patch(
        "app.vm_actions.shutdown.SqlAlchemyRecoveryStore.commit_observation",
        side_effect=RecoveryLeaseLost("shutdown-lease-lost"),
    ):
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


def test_explicit_non_ambiguous_rejection_is_failed_without_forced_fallback():
    from app.operations.target_lock import get_target_operation_lock

    client = ShutdownClient(
        error=ProxmoxMutationError(
            "permission denied",
            details={"status_code": 403, "method": "POST", "path": "/status/shutdown"},
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
    assert [call[0] for call in client.calls] == ["shutdown_vm"]
    assert get_target_operation_lock("proxmox_vm", "vmid:306") is None
