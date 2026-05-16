"""Contract tests for explicit /api/v1 VM action routes."""

import asyncio
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException

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
    def __init__(self, *, task_exitstatus="OK", post_status="running"):
        self.task_exitstatus = task_exitstatus
        self.post_status = post_status
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
        return f"UPID:{node}:0001:start"

    def wait_for_task(self, *, node, upid):
        self.calls.append(("wait_for_task", {"node": node, "upid": upid}))
        return {
            "node": node,
            "upid": upid,
            "status": "stopped",
            "exitstatus": self.task_exitstatus,
            "polls": [{"status": "running"}, {"status": "stopped", "exitstatus": self.task_exitstatus}],
        }

    def get_vm_status(self, *, node, vmid):
        self.calls.append(("get_vm_status", {"node": node, "vmid": vmid}))
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

    def test_start_route_exists_without_legacy_instance_action_routes(self):
        self.assertIn("/api/v1/nodes/{node_id}/vms/{vmid}/actions/start", self.paths)
        self.assertNotIn("/api/instances/action", self.paths)
        self.assertNotIn("/api/v1/instances/action", self.paths)

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

        client = RecordingStartClient()
        response = self._run_start(client=client)

        self.assertTrue(response["ok"])
        self.assertEqual("proxmox_native_vm_start", response["meta"]["mode"])
        result = response["data"]
        self.assertTrue(result["proxmox_mutation_enabled"])
        self.assertFalse(result["idempotent_replay"])
        self.assertEqual("completed", result["status"])
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
        self.assertTrue(any(artifact["type"] == "vm_start_observed_after" for artifact in job["artifacts"]))

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

    def test_post_check_non_running_returns_409_with_artifact_and_failed_job(self):
        from app.jobs.runs import get_job_run

        client = RecordingStartClient(post_status="stopped")
        with self.assertRaises(HTTPException) as raised:
            self._run_start(client=client, payload={
                "vm_start_acknowledged": True,
                "idempotency_key": "idem-post-check-failed",
                "expected_name": "stopped-app",
                "expected_status": "stopped",
            })

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("VM_START_POST_CHECK_FAILED", raised.exception.detail["code"])
        self.assertTrue(raised.exception.detail["proxmox_mutation_enabled"])
        self.assertEqual("stopped", raised.exception.detail["observed_after"]["status"])
        self.assertTrue(raised.exception.detail["observed_after_artifact"]["path"].startswith("db://job-artifacts/"))
        job = get_job_run(raised.exception.detail["job_id"])
        self.assertEqual("failed", job["status"])
        self.assertEqual("post_check", job["current_stage"])


if __name__ == "__main__":
    unittest.main()
