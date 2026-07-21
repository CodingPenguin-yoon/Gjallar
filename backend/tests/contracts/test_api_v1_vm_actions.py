"""Contract tests for explicit /api/v1 VM action routes."""

import asyncio
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.proxmox.client import ProxmoxMutationError
from app.proxmox.models import VmInventory


class StubInventoryAdapter:
    source = "test_read_only"

    def __init__(self, *, vms=None, templates=None):
        self._vms = list(vms or [])
        self._templates = list(templates or [])

    def list_vms(self):
        return list(self._vms)

    def list_templates(self):
        return list(self._templates)


class RecordingStartClient:
    def __init__(
        self,
        *,
        task_exitstatus="OK",
        post_status="running",
        start_upid=None,
        start_error=None,
        wait_error=None,
        post_error=None,
    ):
        self.task_exitstatus = task_exitstatus
        self.post_status = post_status
        self.start_upid = start_upid
        self.start_error = start_error
        self.wait_error = wait_error
        self.post_error = post_error
        self.calls = []

    def redacted_connection_context(self):
        return {
            "mode": "native_mutation",
            "api_url": "https://pve.example.test/api2/json",
            "token_id": "root@pam!gjallar",
            "token_secret": "secret",
        }

    def start_vm(self, *, node, vmid):
        self.calls.append(("start_vm", {"node": node, "vmid": vmid}))
        if self.start_error is not None:
            raise self.start_error
        if self.start_upid is not None:
            return self.start_upid
        return f"UPID:{node}:0001:start"

    def wait_for_task(self, *, node, upid, heartbeat=None):
        self.calls.append(("wait_for_task", {"node": node, "upid": upid}))
        if heartbeat is not None:
            heartbeat()
        if self.wait_error is not None:
            raise self.wait_error
        return {
            "node": node,
            "upid": upid,
            "status": "stopped",
            "exitstatus": self.task_exitstatus,
            "polls": [{"status": "running"}, {"status": "stopped", "exitstatus": self.task_exitstatus}],
        }

    def get_vm_status(self, *, node, vmid):
        self.calls.append(("get_vm_status", {"node": node, "vmid": vmid}))
        if self.post_error is not None:
            raise self.post_error
        return {"vmid": vmid, "name": "stopped-app", "status": self.post_status}


def stopped_vm(*, vmid=306, node_id="node-a", name="stopped-app", status="stopped", template=False):
    return VmInventory(
        vmid=vmid,
        name=name,
        node_id=node_id,
        status=status,
        template=template,
        cpu=2,
        memory_mb=4096,
        disk_gb=40,
    )


class ApiV1VmActionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            from app.main import app
            from app.api.v1 import router as api_v1_router
        cls.paths = {getattr(route, "path", "") for route in app.routes}
        cls.api_v1_router = api_v1_router

    def _run_start(self, *, adapter=None, client=None, payload=None, node_id="node-a", vmid=306):
        adapter = adapter or StubInventoryAdapter(vms=[stopped_vm(vmid=vmid, node_id=node_id)])
        client = client or RecordingStartClient()
        with patch.object(self.api_v1_router, "_inventory_adapter", return_value=adapter):
            with patch.object(self.api_v1_router, "get_default_proxmox_mutation_client", return_value=client):
                return asyncio.run(
                    self.api_v1_router.start_vm_action(
                        node_id,
                        vmid,
                        payload
                        or {
                            "vm_start_acknowledged": True,
                            "idempotency_key": "idem-start-1",
                            "expected_name": "stopped-app",
                            "expected_status": "stopped",
                        },
                    )
                )

    def _cleanup_retained_target_lock(self, job_id):
        from app.jobs.runs import get_job_run
        from app.operations.target_lock import _target_operation_lock_path

        job = get_job_run(job_id)
        details = job.get("details") if isinstance(job, dict) and isinstance(job.get("details"), dict) else {}
        result = details.get("vm_start_result") if isinstance(details.get("vm_start_result"), dict) else {}
        lock = result.get("target_operation_lock") if isinstance(result.get("target_operation_lock"), dict) else {}
        target_type = str(lock.get("target_type") or "proxmox_vm")
        target_id = str(lock.get("target_id") or f"{result.get('target', {}).get('node_id', 'node-a')}:{result.get('target', {}).get('vmid', 306)}")
        _target_operation_lock_path(target_type=target_type, target_id=target_id).unlink(missing_ok=True)

    def _cleanup_target_lock(self, *, target_type="proxmox_vm", target_id="vmid:306"):
        from app.operations.target_lock import _target_operation_lock_path

        _target_operation_lock_path(target_type=target_type, target_id=target_id).unlink(missing_ok=True)

    def test_start_route_exists_without_legacy_instance_action_routes(self):
        self.assertIn("/api/v1/nodes/{node_id}/vms/{vmid}/actions/start", self.paths)
        self.assertNotIn("/api/instances/action", self.paths)
        self.assertNotIn("/api/v1/instances/action", self.paths)

    def test_post_create_readiness_evidence_route_exists_without_bootstrap_aliases(self):
        self.assertIn("/api/v1/nodes/{node_id}/vms/{vmid}/post-create-readiness-evidence", self.paths)
        self.assertNotIn("/api/v1/nodes/{node_id}/vms/{vmid}/actions/bootstrap", self.paths)
        self.assertNotIn("/api/v1/nodes/{node_id}/vms/{vmid}/actions/ssh", self.paths)
        self.assertNotIn("/api/v1/nodes/{node_id}/vms/{vmid}/actions/ansible", self.paths)
        self.assertNotIn("/api/v1/nodes/{node_id}/vms/{vmid}/post-create-bootstrap", self.paths)

    def test_start_blocks_without_acknowledgement(self):
        with self.assertRaises(HTTPException) as raised:
            self._run_start(payload={"idempotency_key": "idem-no-ack"})

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("VM_START_ACK_REQUIRED", raised.exception.detail["code"])
        self.assertFalse(raised.exception.detail["proxmox_mutation_enabled"])

    def test_start_blocks_without_idempotency_key(self):
        with self.assertRaises(HTTPException) as raised:
            self._run_start(payload={"vm_start_acknowledged": True})

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("VM_START_IDEMPOTENCY_KEY_REQUIRED", raised.exception.detail["code"])
        self.assertFalse(raised.exception.detail["proxmox_mutation_enabled"])

    def test_start_precheck_blocks_missing_moved_template_and_non_stopped_vms(self):
        cases = [
            (
                StubInventoryAdapter(vms=[]),
                "VM_START_MISSING_BLOCKED",
                "node-a",
                306,
                "stopped",
            ),
            (
                StubInventoryAdapter(vms=[stopped_vm(node_id="node-b")]),
                "VM_START_MOVED_BLOCKED",
                "node-a",
                306,
                "stopped",
            ),
            (
                StubInventoryAdapter(vms=[stopped_vm(template=True)]),
                "VM_START_TEMPLATE_BLOCKED",
                "node-a",
                306,
                "stopped",
            ),
            (
                StubInventoryAdapter(vms=[stopped_vm(status="running")]),
                "VM_START_NON_STOPPED_BLOCKED",
                "node-a",
                306,
                "running",
            ),
        ]

        for index, (adapter, code, node_id, vmid, expected_status) in enumerate(cases):
            client = RecordingStartClient()
            with self.subTest(code=code):
                with self.assertRaises(HTTPException) as raised:
                    self._run_start(
                        adapter=adapter,
                        client=client,
                        node_id=node_id,
                        vmid=vmid,
                        payload={
                            "vm_start_acknowledged": True,
                            "idempotency_key": f"idem-block-{index}",
                            "expected_name": "stopped-app",
                            "expected_status": expected_status,
                        },
                    )
                self.assertEqual(409, raised.exception.status_code)
                self.assertEqual(code, raised.exception.detail["code"])
                self.assertFalse(raised.exception.detail["proxmox_mutation_enabled"])
                self.assertEqual([], [call for call in client.calls if call[0] == "start_vm"])

    def test_start_precheck_blocks_expected_name_context_mismatch(self):
        client = RecordingStartClient()

        with self.assertRaises(HTTPException) as raised:
            self._run_start(
                client=client,
                payload={
                    "vm_start_acknowledged": True,
                    "idempotency_key": "idem-name-mismatch",
                    "expected_name": "old-name",
                    "expected_status": "stopped",
                },
            )

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("VM_START_CONTEXT_MISMATCH", raised.exception.detail["code"])
        self.assertFalse(raised.exception.detail["proxmox_mutation_enabled"])
        self.assertEqual("stopped-app", raised.exception.detail["observed_before"]["name"])
        self.assertEqual([], [call for call in client.calls if call[0] == "start_vm"])

    def test_start_precheck_blocks_expected_status_context_mismatch(self):
        client = RecordingStartClient()

        with self.assertRaises(HTTPException) as raised:
            self._run_start(
                client=client,
                payload={
                    "vm_start_acknowledged": True,
                    "idempotency_key": "idem-status-mismatch",
                    "expected_name": "stopped-app",
                    "expected_status": "running",
                },
            )

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("VM_START_CONTEXT_MISMATCH", raised.exception.detail["code"])
        self.assertFalse(raised.exception.detail["proxmox_mutation_enabled"])
        self.assertEqual("stopped", raised.exception.detail["observed_before"]["status"])
        self.assertEqual([], [call for call in client.calls if call[0] == "start_vm"])

    def test_start_success_writes_job_artifact_and_calls_proxmox_once(self):
        from app.jobs.artifacts import read_artifact_text
        from app.jobs.runs import get_job_run
        from app.operations.core.domain import verify_event_chain
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
        from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
        from app.operations.target_lock import get_target_operation_lock

        client = RecordingStartClient()
        response = self._run_start(client=client)

        self.assertTrue(response["ok"])
        self.assertEqual("proxmox_native_vm_start", response["meta"]["mode"])
        result = response["data"]
        self.assertTrue(result["proxmox_mutation_enabled"])
        self.assertFalse(result["idempotent_replay"])
        self.assertEqual("completed", result["status"])
        self.assertNotIn("path", result["target_operation_lock"])
        self.assertEqual("running", result["observed_after"]["status"])
        self.assertEqual(["start_vm", "wait_for_task", "get_vm_status"], [call[0] for call in client.calls])
        self.assertTrue(result["observed_after_artifact"]["path"].startswith("db://job-artifacts/"))
        artifact_payload = json.loads(read_artifact_text(result["observed_after_artifact"]))
        self.assertEqual("vm_start", artifact_payload["operation"])
        self.assertEqual("stopped", artifact_payload["observed_before"]["status"])
        self.assertEqual("running", artifact_payload["observed_after"]["status"])
        self.assertEqual("[REDACTED]", artifact_payload["evidence"]["connection"]["token_secret"])
        job = get_job_run(result["job_id"])
        self.assertEqual("vm_start", job["job_type"])
        self.assertEqual("completed", job["status"])
        self.assertNotIn("path", job["details"]["target_operation_lock"])
        self.assertEqual(
            {
                "schema": "vm_start_intent.v1",
                "operation": "vm_start",
                "target": {"node_id": "node-a", "vmid": 306},
                "expected": {"expected_name": "stopped-app", "expected_status": "stopped"},
            },
            job["details"]["vm_start_intent"],
        )
        self.assertTrue(any(artifact["type"] == "vm_start_observed_after" for artifact in job["artifacts"]))
        operation_store = SqlAlchemyOperationStore()
        operation = operation_store.get(result["job_id"])
        operation_events = operation_store.list_events(result["job_id"])
        self.assertEqual("succeeded", operation.status)
        self.assertEqual("managed_api", operation.execution_mode)
        self.assertEqual(
            [
                "operation_created",
                "dispatch_prepared",
                "dispatch_accepted",
                "task_and_state_observed",
                "verification_succeeded",
                "recovery_compatibility_projection_recorded",
            ],
            [event.event_type for event in operation_events],
        )
        self.assertTrue(verify_event_chain(operation_events))
        recovery = SqlAlchemyRecoveryStore().get(result["job_id"])
        self.assertIsNotNone(recovery)
        self.assertEqual("completed", recovery.status)
        self.assertIsNone(recovery.lease_owner)
        self.assertEqual(
            {
                "node": "node-a",
                "upid": "UPID:node-a:0001:start",
                "status": "stopped",
                "exitstatus": "OK",
            },
            recovery.details["task"],
        )
        self.assertNotIn("polls", recovery.details["task"])
        self.assertEqual(
            {
                "node_id": "node-a",
                "vmid": 306,
                "name": "stopped-app",
                "status": "running",
                "error": "",
            },
            recovery.details["observed_after"],
        )
        self.assertIsNone(get_target_operation_lock("proxmox_vm", "vmid:306"))

    def test_recovery_registration_failure_blocks_before_proxmox_dispatch(self):
        client = RecordingStartClient()

        with patch(
            "app.vm_actions.start.SqlAlchemyRecoveryStore.prepare_and_claim",
            side_effect=RuntimeError("database unavailable"),
        ):
            with self.assertRaises(HTTPException) as raised:
                self._run_start(
                    client=client,
                    payload={
                        "vm_start_acknowledged": True,
                        "idempotency_key": "idem-recovery-registration-failure",
                        "expected_name": "stopped-app",
                        "expected_status": "stopped",
                    },
                )

        self.assertEqual(503, raised.exception.status_code)
        self.assertEqual("VM_START_RECOVERY_UNAVAILABLE", raised.exception.detail["code"])
        self.assertFalse(raised.exception.detail["proxmox_mutation_enabled"])
        self.assertEqual([], [call for call in client.calls if call[0] == "start_vm"])

    def test_duplicate_idempotency_key_returns_existing_job_without_second_start(self):
        client = RecordingStartClient()
        payload = {
            "vm_start_acknowledged": True,
            "idempotency_key": "same-idem-key",
            "expected_name": "stopped-app",
            "expected_status": "stopped",
        }

        first = self._run_start(client=client, payload=payload)
        second = self._run_start(client=client, payload=payload)

        self.assertEqual(first["data"]["job_id"], second["data"]["job_id"])
        self.assertTrue(first["data"]["proxmox_mutation_enabled"])
        self.assertFalse(second["data"]["proxmox_mutation_enabled"])
        self.assertTrue(second["data"]["idempotent_replay"])
        self.assertEqual(1, len([call for call in client.calls if call[0] == "start_vm"]))

    def test_duplicate_idempotency_key_with_different_intent_is_conflict(self):
        client = RecordingStartClient()
        payload = {
            "vm_start_acknowledged": True,
            "idempotency_key": "same-key-different-intent",
            "expected_name": "stopped-app",
            "expected_status": "stopped",
        }

        first = self._run_start(client=client, payload=payload)
        with self.assertRaises(HTTPException) as raised:
            self._run_start(
                client=client,
                payload={**payload, "expected_status": "running"},
            )

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("VM_START_IDEMPOTENCY_CONFLICT", raised.exception.detail["code"])
        self.assertEqual(first["data"]["job_id"], raised.exception.detail["job_id"])
        self.assertEqual(1, len([call for call in client.calls if call[0] == "start_vm"]))

    def test_legacy_duplicate_without_stored_intent_keeps_replay_compatibility(self):
        from app.jobs.runs import record_job_run
        from app.vm_actions.start import build_vm_start_job_id

        job_id = build_vm_start_job_id(node_id="node-a", vmid=306, idempotency_key="legacy-idem")
        record_job_run(
            job_id=job_id,
            job_type="vm_start",
            status="completed",
            target_id="node-a:306:stopped-app",
            risk_level="unknown",
            stage="post_check",
            step_status="completed",
            message="Legacy VM start job",
            details={
                "target": {"node_id": "node-a", "vmid": 306, "name": "stopped-app"},
                "vm_start_result": {
                    "job_id": job_id,
                    "status": "completed",
                    "target": {"node_id": "node-a", "vmid": 306, "name": "stopped-app"},
                    "proxmox_mutation_enabled": True,
                },
            },
        )
        client = RecordingStartClient()

        response = self._run_start(
            client=client,
            payload={
                "vm_start_acknowledged": True,
                "idempotency_key": "legacy-idem",
                "expected_name": "stopped-app",
                "expected_status": "running",
            },
        )

        self.assertTrue(response["data"]["idempotent_replay"])
        self.assertEqual([], [call for call in client.calls if call[0] == "start_vm"])

    def test_target_lock_blocks_different_idempotency_key_for_same_vm(self):
        from app.operations.target_lock import acquire_target_operation_lock, release_target_operation_lock

        handle = acquire_target_operation_lock("proxmox_vm", "vmid:306", "other-job")
        client = RecordingStartClient()
        try:
            with self.assertRaises(HTTPException) as raised:
                self._run_start(
                    client=client,
                    payload={
                        "vm_start_acknowledged": True,
                        "idempotency_key": "different-idem-while-target-busy",
                        "expected_name": "stopped-app",
                        "expected_status": "stopped",
                    },
                )
        finally:
            release_target_operation_lock(handle)

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("VM_START_TARGET_LOCK_BUSY", raised.exception.detail["code"])
        self.assertFalse(raised.exception.detail["proxmox_mutation_enabled"])
        self.assertNotIn("path", raised.exception.detail["target_operation_lock"])
        self.assertEqual([], [call for call in client.calls if call[0] == "start_vm"])

    def test_task_failure_returns_409_with_artifact_and_failed_job(self):
        from app.jobs.runs import get_job_run

        client = RecordingStartClient(task_exitstatus="ERROR", post_status="stopped")
        with self.assertRaises(HTTPException) as raised:
            self._run_start(client=client, payload={
                "vm_start_acknowledged": True,
                "idempotency_key": "idem-task-failed",
                "expected_name": "stopped-app",
                "expected_status": "stopped",
            })

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("VM_START_TASK_FAILED", raised.exception.detail["code"])
        self.assertTrue(raised.exception.detail["proxmox_mutation_enabled"])
        self.assertTrue(raised.exception.detail["observed_after_artifact"]["path"].startswith("db://job-artifacts/"))
        job = get_job_run(raised.exception.detail["job_id"])
        self.assertEqual("failed", job["status"])
        self.assertEqual("task_poll", job["current_stage"])

    def test_definitive_4xx_start_rejection_releases_target_lock(self):
        from app.jobs.runs import get_job_run

        rejecting_client = RecordingStartClient(
            start_error=ProxmoxMutationError("bad request", details={"status_code": 400})
        )
        with self.assertRaises(HTTPException) as raised:
            self._run_start(client=rejecting_client, payload={
                "vm_start_acknowledged": True,
                "idempotency_key": "idem-definitive-4xx",
                "expected_name": "stopped-app",
                "expected_status": "stopped",
            })

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("VM_START_REQUEST_FAILED", raised.exception.detail["code"])
        self.assertFalse(raised.exception.detail["proxmox_mutation_enabled"])
        self.assertNotIn("path", raised.exception.detail["target_operation_lock"])
        job = get_job_run(raised.exception.detail["job_id"])
        self.assertEqual("failed", job["status"])
        self.assertNotIn("path", job["details"]["target_operation_lock"])

        allowed_client = RecordingStartClient()
        response = self._run_start(client=allowed_client, payload={
            "vm_start_acknowledged": True,
            "idempotency_key": "idem-after-definitive-4xx",
            "expected_name": "stopped-app",
            "expected_status": "stopped",
        })
        self.assertEqual("completed", response["data"]["status"])
        self.assertEqual(1, len([call for call in allowed_client.calls if call[0] == "start_vm"]))

    def test_ambiguous_408_start_error_preserves_needs_reconciliation_and_lock(self):
        from app.jobs.runs import get_job_run
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore

        client = RecordingStartClient(
            start_error=ProxmoxMutationError("request timeout", details={"status_code": 408}),
            post_status="stopped",
        )
        try:
            with self.assertRaises(HTTPException) as raised:
                self._run_start(client=client, payload={
                    "vm_start_acknowledged": True,
                    "idempotency_key": "idem-ambiguous-408",
                    "expected_name": "stopped-app",
                    "expected_status": "stopped",
                })

            self.assertEqual(409, raised.exception.status_code)
            self.assertEqual("VM_START_REQUEST_RECONCILIATION_REQUIRED", raised.exception.detail["code"])
            self.assertTrue(raised.exception.detail["proxmox_mutation_enabled"])
            self.assertNotIn("path", raised.exception.detail["target_operation_lock"])
            job = get_job_run(raised.exception.detail["job_id"])
            self.assertEqual("needs_reconciliation", job["status"])
            self.assertNotIn("path", job["details"]["target_operation_lock"])
            operation = SqlAlchemyOperationStore().get(raised.exception.detail["job_id"])
            self.assertEqual("needs_reconciliation", operation.status)

            with self.assertRaises(HTTPException) as blocked:
                self._run_start(client=client, payload={
                    "vm_start_acknowledged": True,
                    "idempotency_key": "idem-after-ambiguous-408",
                    "expected_name": "stopped-app",
                    "expected_status": "stopped",
                })
            self.assertEqual("VM_START_TARGET_LOCK_BUSY", blocked.exception.detail["code"])
        finally:
            if "raised" in locals() and raised.exception.detail.get("job_id"):
                self._cleanup_retained_target_lock(raised.exception.detail["job_id"])

    def test_post_check_non_running_returns_409_with_artifact_and_needs_reconciliation_job(self):
        from app.jobs.runs import get_job_run

        client = RecordingStartClient(post_status="stopped")
        try:
            with self.assertRaises(HTTPException) as raised:
                self._run_start(client=client, payload={
                    "vm_start_acknowledged": True,
                    "idempotency_key": "idem-post-check-needs-reconciliation",
                    "expected_name": "stopped-app",
                    "expected_status": "stopped",
                })

            self.assertEqual(409, raised.exception.status_code)
            self.assertEqual("VM_START_POST_CHECK_RECONCILIATION_REQUIRED", raised.exception.detail["code"])
            self.assertTrue(raised.exception.detail["proxmox_mutation_enabled"])
            self.assertEqual("stopped", raised.exception.detail["observed_after"]["status"])
            self.assertTrue(raised.exception.detail["observed_after_artifact"]["path"].startswith("db://job-artifacts/"))
            self.assertNotIn("path", raised.exception.detail["target_operation_lock"])
            job = get_job_run(raised.exception.detail["job_id"])
            self.assertEqual("needs_reconciliation", job["status"])
            self.assertEqual("post_check", job["current_stage"])
            self.assertTrue(job["details"]["vm_start_result"]["reconciliation_required"])
            self.assertNotIn("path", job["details"]["target_operation_lock"])
        finally:
            if "raised" in locals() and raised.exception.detail.get("job_id"):
                self._cleanup_retained_target_lock(raised.exception.detail["job_id"])

    def test_missing_upid_preserves_needs_reconciliation_and_blocks_second_mutation(self):
        from app.jobs.runs import get_job_run

        client = RecordingStartClient(start_upid="", post_status="stopped")
        try:
            with self.assertRaises(HTTPException) as raised:
                self._run_start(client=client, payload={
                    "vm_start_acknowledged": True,
                    "idempotency_key": "idem-missing-upid",
                    "expected_name": "stopped-app",
                    "expected_status": "stopped",
                })

            self.assertEqual(409, raised.exception.status_code)
            self.assertEqual("VM_START_REQUEST_RECONCILIATION_REQUIRED", raised.exception.detail["code"])
            job_id = raised.exception.detail["job_id"]
            job = get_job_run(job_id)
            self.assertEqual("needs_reconciliation", job["status"])
            self.assertNotIn("path", raised.exception.detail["target_operation_lock"])
            self.assertNotIn("path", job["details"]["target_operation_lock"])

            replay = self._run_start(client=client, payload={
                "vm_start_acknowledged": True,
                "idempotency_key": "idem-missing-upid",
                "expected_name": "stopped-app",
                "expected_status": "stopped",
            })
            self.assertTrue(replay["data"]["idempotent_replay"])
            self.assertFalse(replay["data"]["proxmox_mutation_enabled"])

            with self.assertRaises(HTTPException) as blocked:
                self._run_start(client=client, payload={
                    "vm_start_acknowledged": True,
                    "idempotency_key": "idem-after-retained-lock",
                    "expected_name": "stopped-app",
                    "expected_status": "stopped",
                })
            self.assertEqual("VM_START_TARGET_LOCK_BUSY", blocked.exception.detail["code"])
            self.assertEqual(1, len([call for call in client.calls if call[0] == "start_vm"]))
        finally:
            if "raised" in locals() and raised.exception.detail.get("job_id"):
                self._cleanup_retained_target_lock(raised.exception.detail["job_id"])

    def test_task_poll_timeout_preserves_needs_reconciliation(self):
        from app.jobs.runs import get_job_run

        client = RecordingStartClient(
            wait_error=ProxmoxMutationError(
                "Timed out waiting for Proxmox task",
                details={"node": "node-a", "upid": "UPID:node-a:0001:start"},
            ),
            post_status="stopped",
        )
        try:
            with self.assertRaises(HTTPException) as raised:
                self._run_start(client=client, payload={
                    "vm_start_acknowledged": True,
                    "idempotency_key": "idem-task-timeout",
                    "expected_name": "stopped-app",
                    "expected_status": "stopped",
                })

            self.assertEqual(409, raised.exception.status_code)
            self.assertEqual("VM_START_TASK_RECONCILIATION_REQUIRED", raised.exception.detail["code"])
            job = get_job_run(raised.exception.detail["job_id"])
            self.assertEqual("needs_reconciliation", job["status"])
            self.assertEqual("task_poll", job["current_stage"])
        finally:
            if "raised" in locals() and raised.exception.detail.get("job_id"):
                self._cleanup_retained_target_lock(raised.exception.detail["job_id"])

    def test_artifact_write_failure_after_start_retains_target_lock(self):
        client = RecordingStartClient()
        try:
            with patch("app.vm_actions.start.write_json_artifact", side_effect=RuntimeError("artifact write failed")):
                with self.assertRaises(RuntimeError):
                    self._run_start(client=client, payload={
                        "vm_start_acknowledged": True,
                        "idempotency_key": "idem-artifact-write-failed",
                        "expected_name": "stopped-app",
                        "expected_status": "stopped",
                    })

            with self.assertRaises(HTTPException) as blocked:
                self._run_start(client=client, payload={
                    "vm_start_acknowledged": True,
                    "idempotency_key": "idem-after-artifact-write-failed",
                    "expected_name": "stopped-app",
                    "expected_status": "stopped",
                })
            self.assertEqual("VM_START_TARGET_LOCK_BUSY", blocked.exception.detail["code"])
            self.assertEqual(1, len([call for call in client.calls if call[0] == "start_vm"]))
        finally:
            self._cleanup_target_lock(target_id="vmid:306")

    def test_completed_job_projection_failure_retains_durable_lock_after_file_loss(self):
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
        from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
        from app.vm_actions import start as start_module
        from app.vm_actions.start import build_vm_start_job_id

        client = RecordingStartClient()
        original_record_job_run = start_module.record_job_run

        def fail_completed_projection(**kwargs):
            if kwargs.get("status") == "completed":
                raise RuntimeError("completed job projection failed")
            return original_record_job_run(**kwargs)

        payload = {
            "vm_start_acknowledged": True,
            "idempotency_key": "idem-completed-job-projection-failed",
            "expected_name": "stopped-app",
            "expected_status": "stopped",
        }
        operation_id = build_vm_start_job_id(
            node_id="node-a",
            vmid=306,
            idempotency_key=payload["idempotency_key"],
        )
        try:
            with patch("app.vm_actions.start.record_job_run", side_effect=fail_completed_projection):
                with self.assertRaises(RuntimeError, msg="completed job projection failed"):
                    self._run_start(client=client, payload=payload)

            operation = SqlAlchemyOperationStore().get(operation_id)
            recovery = SqlAlchemyRecoveryStore().get(operation_id)
            self.assertEqual("succeeded", operation.status)
            self.assertEqual("leased", recovery.status)

            # Simulate container-local compatibility file loss. PostgreSQL must
            # still reject a second mutation for the same cluster/VMID.
            self._cleanup_target_lock(target_id="vmid:306")
            with self.assertRaises(HTTPException) as blocked:
                self._run_start(
                    client=RecordingStartClient(),
                    payload={
                        "vm_start_acknowledged": True,
                        "idempotency_key": "idem-after-completed-job-projection-failed",
                        "expected_name": "stopped-app",
                        "expected_status": "stopped",
                    },
                )
            self.assertEqual("VM_START_TARGET_LOCK_BUSY", blocked.exception.detail["code"])
            self.assertEqual(operation_id, blocked.exception.detail["target_operation_lock"]["existing"]["owner_id"])
        finally:
            self._cleanup_target_lock(target_id="vmid:306")

    def test_operation_persistence_failure_blocks_before_proxmox_dispatch(self):
        client = RecordingStartClient()

        with patch(
            "app.vm_actions.start.SqlAlchemyOperationStore.create",
            side_effect=RuntimeError("operation persistence failed"),
        ):
            with self.assertRaises(RuntimeError):
                self._run_start(
                    client=client,
                    payload={
                        "vm_start_acknowledged": True,
                        "idempotency_key": "idem-operation-persistence-failed",
                        "expected_name": "stopped-app",
                        "expected_status": "stopped",
                    },
                )

        self.assertEqual([], client.calls)


if __name__ == "__main__":
    unittest.main()
