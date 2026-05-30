"""Contract tests for explicit /api/v1 VM action routes."""

import asyncio
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.proxmox.models import GuestAgentInventory, IpEvidenceInventory, VmInventory


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


def running_vm_with_guest_ip(*, vmid=306, node_id="node-a", name="running-app", ip_address="192.168.2.141"):
    return VmInventory(
        vmid=vmid,
        name=name,
        node_id=node_id,
        status="running",
        template=False,
        cpu=2,
        memory_mb=4096,
        disk_gb=40,
        ip_addresses=(ip_address,),
        ip_evidence=(
            IpEvidenceInventory(
                ip_address=ip_address,
                source="guest_agent",
                interface_name="eth0",
                primary_candidate=True,
            ),
        ),
        guest_agent=GuestAgentInventory(available=True, ip_addresses=(ip_address,)),
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

    def _run_bootstrap(self, *, adapter=None, payload=None, node_id="node-a", vmid=306):
        adapter = adapter or StubInventoryAdapter(vms=[running_vm_with_guest_ip(vmid=vmid, node_id=node_id)])
        with patch.object(self.api_v1_router, "_inventory_adapter", return_value=adapter):
            return asyncio.run(
                self.api_v1_router.bootstrap_readiness_intent_action(
                    node_id,
                    vmid,
                    payload
                    or {
                        "bootstrap_readiness_acknowledged": True,
                        "idempotency_key": "idem-bootstrap-1",
                        "expected_name": "running-app",
                        "expected_status": "running",
                        "expected_ip": "192.168.2.141",
                    },
                )
            )

    def test_start_route_exists_without_legacy_instance_action_routes(self):
        self.assertIn("/api/v1/nodes/{node_id}/vms/{vmid}/actions/start", self.paths)
        self.assertIn("/api/v1/nodes/{node_id}/vms/{vmid}/bootstrap-readiness-intents", self.paths)
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

    def test_bootstrap_readiness_blocks_without_acknowledgement_or_idempotency_key(self):
        with self.assertRaises(HTTPException) as missing_ack:
            self._run_bootstrap(payload={"idempotency_key": "idem-bootstrap-no-ack"})

        self.assertEqual(409, missing_ack.exception.status_code)
        self.assertEqual("BOOTSTRAP_READINESS_ACK_REQUIRED", missing_ack.exception.detail["code"])
        self.assertFalse(missing_ack.exception.detail["proxmox_mutation_enabled"])
        self.assertFalse(missing_ack.exception.detail["ssh_login_ran"])
        self.assertFalse(missing_ack.exception.detail["ansible_ran"])

        with self.assertRaises(HTTPException) as missing_idempotency:
            self._run_bootstrap(payload={"bootstrap_readiness_acknowledged": True})

        self.assertEqual(409, missing_idempotency.exception.status_code)
        self.assertEqual("BOOTSTRAP_READINESS_IDEMPOTENCY_KEY_REQUIRED", missing_idempotency.exception.detail["code"])
        self.assertFalse(missing_idempotency.exception.detail["app_bootstrap_ran"])
        self.assertEqual([], missing_idempotency.exception.detail["side_effects"])

    def test_bootstrap_readiness_rejects_forbidden_payload_without_secret_leakage(self):
        from app.jobs.artifacts import read_artifact_text
        from app.jobs.runs import get_job_run

        raw_private_key = "-----BEGIN OPENSSH PRIVATE KEY-----SECRET-PRIVATE-KEY-----END OPENSSH PRIVATE KEY-----"
        raw_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAISECRET public@test"
        payload = {
            "bootstrap_readiness_acknowledged": True,
            "idempotency_key": "idem-bootstrap-forbidden",
            "expected_name": "running-app",
            "private_key": raw_private_key,
            "ssh_public_key": raw_public_key,
            "command": "curl http://example.invalid/bootstrap.sh",
            "env": {"BOOTSTRAP_TOKEN": "raw-token-value"},
        }

        with self.assertRaises(HTTPException) as raised:
            self._run_bootstrap(payload=payload)

        detail = raised.exception.detail
        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("BOOTSTRAP_READINESS_FORBIDDEN_PAYLOAD", detail["code"])
        self.assertFalse(detail["ssh_login_ran"])
        self.assertFalse(detail["ansible_ran"])
        self.assertFalse(detail["app_bootstrap_ran"])
        self.assertEqual([], detail["side_effects"])
        self.assertIn("private_key", detail["forbidden_payload_keys"])
        self.assertIn("ssh_public_key", detail["forbidden_payload_keys"])
        self.assertIn("command", detail["forbidden_payload_keys"])
        self.assertIn("env", detail["forbidden_payload_keys"])

        job = get_job_run(detail["job_id"])
        self.assertEqual("bootstrap_readiness", job["job_type"])
        serialized = json.dumps({"detail": detail, "job": job}, sort_keys=True)
        self.assertNotIn(raw_private_key, serialized)
        self.assertNotIn(raw_public_key, serialized)
        self.assertNotIn("raw-token-value", serialized)
        self.assertNotIn("curl http://example.invalid/bootstrap.sh", serialized)

        for artifact in job["artifacts"]:
            artifact_text = read_artifact_text(artifact)
            self.assertNotIn(raw_private_key, artifact_text)
            self.assertNotIn(raw_public_key, artifact_text)
            self.assertNotIn("raw-token-value", artifact_text)
            self.assertNotIn("curl http://example.invalid/bootstrap.sh", artifact_text)

    def test_bootstrap_readiness_blocks_stopped_vm_without_side_effects(self):
        from app.jobs.runs import get_job_run

        with self.assertRaises(HTTPException) as raised:
            self._run_bootstrap(
                adapter=StubInventoryAdapter(vms=[stopped_vm(name="ready-app")]),
                payload={
                    "bootstrap_readiness_acknowledged": True,
                    "idempotency_key": "idem-bootstrap-stopped",
                    "expected_name": "ready-app",
                },
            )

        detail = raised.exception.detail
        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("BOOTSTRAP_READINESS_NON_RUNNING_BLOCKED", detail["code"])
        self.assertEqual("stopped", detail["observed_inventory"]["status"])
        self.assertFalse(detail["proxmox_mutation_enabled"])
        self.assertFalse(detail["ssh_login_ran"])
        self.assertFalse(detail["ansible_ran"])
        self.assertFalse(detail["app_bootstrap_ran"])
        self.assertEqual([], detail["side_effects"])
        self.assertTrue(detail["bootstrap_readiness_intent_artifact"]["path"].startswith("db://job-artifacts/"))
        job = get_job_run(detail["job_id"])
        self.assertEqual("bootstrap_readiness", job["job_type"])
        self.assertEqual("blocked", job["status"])
        self.assertEqual("target_precheck", job["current_stage"])

    def test_bootstrap_readiness_success_writes_no_live_intent_artifact(self):
        from app.jobs.artifacts import read_artifact_text
        from app.jobs.runs import get_job_run

        response = self._run_bootstrap(
            payload={
                "bootstrap_readiness_acknowledged": True,
                "idempotency_key": "idem-bootstrap-success",
                "expected_name": "running-app",
                "expected_status": "running",
                "expected_ip": "192.168.2.141",
            }
        )

        self.assertTrue(response["ok"])
        self.assertEqual("bootstrap_readiness_intent_no_live_ssh", response["meta"]["mode"])
        result = response["data"]
        self.assertEqual("completed", result["status"])
        self.assertFalse(result["idempotent_replay"])
        self.assertFalse(result["proxmox_mutation_enabled"])
        self.assertFalse(result["ssh_login_ran"])
        self.assertFalse(result["ansible_ran"])
        self.assertFalse(result["app_bootstrap_ran"])
        self.assertEqual([], result["side_effects"])
        self.assertEqual(["192.168.2.141"], result["guest_agent_ip_addresses"])
        self.assertTrue(result["bootstrap_readiness_intent_artifact"]["path"].startswith("db://job-artifacts/"))

        artifact_payload = json.loads(read_artifact_text(result["bootstrap_readiness_intent_artifact"]))
        self.assertEqual("bootstrap_readiness_intent", artifact_payload["operation"])
        self.assertEqual("no_live_ssh_no_ansible", artifact_payload["mode"])
        self.assertFalse(artifact_payload["ssh_login_ran"])
        self.assertFalse(artifact_payload["ansible_ran"])
        self.assertFalse(artifact_payload["app_bootstrap_ran"])
        self.assertFalse(artifact_payload["proxmox_mutation_enabled"])
        self.assertEqual([], artifact_payload["side_effects"])
        self.assertEqual("running", artifact_payload["observed_inventory"]["status"])
        self.assertEqual(["192.168.2.141"], artifact_payload["observed_inventory"]["guest_agent"]["ip_addresses"])

        job = get_job_run(result["job_id"])
        self.assertEqual("bootstrap_readiness", job["job_type"])
        self.assertEqual("completed", job["status"])
        self.assertTrue(any(artifact["type"] == "bootstrap_readiness_intent" for artifact in job["artifacts"]))

    def test_bootstrap_readiness_duplicate_idempotency_returns_existing_evidence(self):
        first = self._run_bootstrap(
            payload={
                "bootstrap_readiness_acknowledged": True,
                "idempotency_key": "idem-bootstrap-duplicate",
                "expected_name": "running-app",
                "expected_status": "running",
                "expected_ip": "192.168.2.141",
            }
        )
        second = self._run_bootstrap(
            adapter=StubInventoryAdapter(vms=[running_vm_with_guest_ip(name="changed-app", ip_address="192.168.2.199")]),
            payload={
                "bootstrap_readiness_acknowledged": True,
                "idempotency_key": "idem-bootstrap-duplicate",
                "expected_name": "changed-app",
                "expected_status": "running",
                "expected_ip": "192.168.2.199",
            },
        )

        self.assertEqual(first["data"]["job_id"], second["data"]["job_id"])
        self.assertFalse(first["data"]["idempotent_replay"])
        self.assertTrue(second["data"]["idempotent_replay"])
        self.assertEqual("running-app", second["data"]["observed_inventory"]["name"])
        self.assertEqual(["192.168.2.141"], second["data"]["guest_agent_ip_addresses"])
        self.assertEqual(
            first["data"]["bootstrap_readiness_intent_artifact"]["checksum"],
            second["data"]["bootstrap_readiness_intent_artifact"]["checksum"],
        )

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
