"""Tests for /api/v1 VM create approval and native create boundary."""

import asyncio
import contextlib
import io
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

TEST_SSH_PUBLIC_KEY = (
    "ssh-ed25519 "
    "AAAAC3NzaC1lZDI1NTE5AAAAIAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8g "
    "gjallar@test"
)


class ApiV1VmCreateApprovalExecuteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            from app.main import app
            from app.api.v1 import router as api_v1_router
        cls.app = app
        cls.paths = {getattr(route, "path", "") for route in app.routes}
        cls.api_v1_router = api_v1_router

    def test_approval_and_native_create_routes_exist_under_api_v1(self):
        expected = {
            "/api/v1/vm-create/{draft_id}/approve",
            "/api/v1/vm-create/{draft_id}/proxmox-preview",
            "/api/v1/vm-create/{draft_id}/proxmox-create",
        }
        missing = sorted(expected - self.paths)
        self.assertEqual([], missing, f"Missing approval/native create safety routes: {missing}")
        self.assertNotIn("/api/v1/vm-create/{draft_id}/terraform-plan", self.paths)
        self.assertNotIn("/api/v1/vm-create/{draft_id}/terraform-apply", self.paths)
        self.assertNotIn("/api/v1/vm-create/{draft_id}/execute", self.paths)
        self.assertNotIn("/api/v1/vm-create/{draft_id}/archive", self.paths)

    def test_removed_terraform_and_gitops_routes_are_not_accepted(self):
        client = TestClient(self.app)

        for suffix in ("terraform-plan", "terraform-apply", "execute", "archive"):
            response = client.post(f"/api/v1/vm-create/removed-terraform/{suffix}", json={})
            self.assertIn(response.status_code, {404, 405})

    def test_approve_validates_exact_plan_artifacts_without_side_effects(self):
        draft_id = "draft-api-approval-green"
        payload = {
            "operator_id": "api-approval-test",
            "job_id": draft_id,
            "bridge_id": "vmbr0",
            "static_ip": "192.168.2.144",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        review = plan_response["data"]["review_confirm"]

        approve_response = asyncio.run(
            self.api_v1_router.approve_vm_draft(
                draft_id,
                {
                    **payload,
                    "plan_artifact_id": review["plan_artifact_id"],
                    "review_summary_checksum": review["review_summary_checksum"],
                    "yellow_risk_acknowledged": False,
                },
            )
        )

        self.assertTrue(approve_response["ok"])
        decision = approve_response["data"]
        self.assertTrue(decision["can_approve"])
        self.assertTrue(decision["can_execute"])
        self.assertEqual([], decision["side_effects"])
        self.assertEqual("approved", decision["approval_record"]["decision"])
        self.assertEqual("approval_validation_only", approve_response["meta"]["mode"])

    def test_approve_rejects_wrong_review_checksum(self):
        draft_id = "draft-api-approval-wrong-checksum"
        payload = {
            "operator_id": "api-approval-test",
            "job_id": draft_id,
            "bridge_id": "vmbr0",
            "static_ip": "192.168.2.145",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        review = plan_response["data"]["review_confirm"]

        approve_response = asyncio.run(
            self.api_v1_router.approve_vm_draft(
                draft_id,
                {
                    **payload,
                    "plan_artifact_id": review["plan_artifact_id"],
                    "review_summary_checksum": "sha256:" + "0" * 64,
                    "yellow_risk_acknowledged": False,
                },
            )
        )

        self.assertTrue(approve_response["ok"])
        decision = approve_response["data"]
        self.assertFalse(decision["can_approve"])
        self.assertFalse(decision["can_execute"])
        self.assertEqual([], decision["side_effects"])
        self.assertIn("checksum", decision["reason"].lower())

    def test_proxmox_preview_after_approval_does_not_mutate(self):
        draft_id = "draft-api-proxmox-preview"
        payload = {
            "operator_id": "api-proxmox-test",
            "job_id": "job-api-proxmox-preview",
            "bridge_id": "vmbr0",
            "static_ip": "192.168.2.142",
            "prefix": 25,
            "gateway": "192.168.2.254",
        }
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        review = plan_response["data"]["review_confirm"]

        with patch.object(self.api_v1_router, "run_proxmox_create") as mutation:
            response = asyncio.run(
                self.api_v1_router.preview_vm_draft_proxmox_create(
                    draft_id,
                    {
                        **payload,
                        "plan_artifact_id": review["plan_artifact_id"],
                        "review_summary_checksum": review["review_summary_checksum"],
                        "yellow_risk_acknowledged": False,
                    },
                )
            )

        self.assertTrue(response["ok"])
        self.assertEqual("proxmox_native_preview_no_mutation", response["meta"]["mode"])
        self.assertFalse(response["data"]["proxmox_mutation_enabled"])
        self.assertEqual([], response["data"]["side_effects"])
        self.assertEqual("/nodes/yoonmanserver2/qemu/9000/clone", response["data"]["clone"]["endpoint"])
        mutation.assert_not_called()

    def test_proxmox_create_blocks_without_final_acknowledgement(self):
        draft_id = "draft-api-proxmox-create-gates"
        payload = {
            "operator_id": "api-proxmox-test",
            "job_id": "job-api-proxmox-create-gates",
            "bridge_id": "vmbr0",
            "static_ip": "192.168.2.143",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        review = plan_response["data"]["review_confirm"]
        approved_payload = {
            **payload,
            "plan_artifact_id": review["plan_artifact_id"],
            "review_summary_checksum": review["review_summary_checksum"],
            "yellow_risk_acknowledged": False,
        }

        with self.assertRaises(HTTPException) as no_ack:
            asyncio.run(self.api_v1_router.create_vm_draft_proxmox_native(draft_id, approved_payload))
        self.assertEqual(409, no_ack.exception.status_code)
        self.assertEqual("PROXMOX_CREATE_ACK_REQUIRED", no_ack.exception.detail["code"])

    def test_proxmox_create_success_marks_applied_only_with_observed_after_artifact(self):
        from app.jobs.artifacts import write_json_artifact

        draft_id = "draft-api-proxmox-create-success"
        payload = {
            "operator_id": "api-proxmox-test",
            "job_id": "job-api-proxmox-create-success",
            "bridge_id": "vmbr0",
            "static_ip": "192.168.2.144",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        review = plan_response["data"]["review_confirm"]
        approved_payload = {
            **payload,
            "plan_artifact_id": review["plan_artifact_id"],
            "review_summary_checksum": review["review_summary_checksum"],
            "yellow_risk_acknowledged": False,
        }
        def fake_create(plan, *, run_dir, client):
            artifact = write_json_artifact(
                run_dir=run_dir,
                job_id=plan.job_id,
                artifact_type="observed_after",
                filename="observed_after.json",
                payload={
                    "vmid": plan.vmid,
                    "target_node_id": plan.target_node_id,
                    "exists": True,
                    "status": "stopped",
                    "fingerprint": {"hash": "sha256:" + "1" * 64},
                },
            )
            return {
                "job_id": plan.job_id,
                "manifest_id": plan.manifest_id,
                "vmid": plan.vmid,
                "target_node_id": plan.target_node_id,
                "success": True,
                "status": "completed",
                "message": "VM exists on target node and is stopped",
                "task": {"upid": "UPID:yoonmanserver2:0001:test", "exitstatus": "OK"},
                "observed_after": {"status": "stopped", "fingerprint": {"hash": "sha256:" + "1" * 64}},
                "observed_after_artifact": artifact.to_dict(),
                "artifacts": [artifact.to_dict()],
                "side_effects": ["proxmox_clone_invoked", "proxmox_task_polled", "proxmox_config_updated", "proxmox_post_check_observed"],
            }

        with patch.object(self.api_v1_router, "get_default_proxmox_mutation_client", return_value=object()):
            with patch.object(self.api_v1_router, "run_proxmox_create", side_effect=fake_create):
                response = asyncio.run(
                    self.api_v1_router.create_vm_draft_proxmox_native(
                        draft_id,
                        {
                            **approved_payload,
                            "proxmox_mutation_acknowledged": True,
                        },
                    )
                )

        self.assertTrue(response["ok"])
        self.assertEqual("proxmox_native_create_live_mutation", response["meta"]["mode"])
        self.assertTrue(response["data"]["proxmox_create_ran"])
        self.assertTrue(response["data"]["proxmox_mutation_enabled"])
        self.assertNotIn("manifest_status", response["data"])
        self.assertIn("proxmox_preview", response["data"])
        self.assertEqual("stopped", response["data"]["observed_after"]["status"])
        self.assertTrue(response["data"]["observed_after_artifact"]["path"].startswith("db://job-artifacts/"))
        self.assertEqual("stopped", response["data"]["vm_instance"]["status"])

    def test_proxmox_create_powered_on_post_check_needs_reconciliation_not_applied(self):
        from app.jobs.artifacts import write_json_artifact

        draft_id = "draft-api-proxmox-create-reconcile"
        payload = {
            "operator_id": "api-proxmox-test",
            "job_id": "job-api-proxmox-create-reconcile",
            "bridge_id": "vmbr0",
            "static_ip": "192.168.2.145",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        review = plan_response["data"]["review_confirm"]
        approved_payload = {
            **payload,
            "plan_artifact_id": review["plan_artifact_id"],
            "review_summary_checksum": review["review_summary_checksum"],
            "yellow_risk_acknowledged": False,
        }
        def fake_create(plan, *, run_dir, client):
            artifact = write_json_artifact(
                run_dir=run_dir,
                job_id=plan.job_id,
                artifact_type="observed_after",
                filename="observed_after.json",
                payload={
                    "vmid": plan.vmid,
                    "target_node_id": plan.target_node_id,
                    "exists": True,
                    "status": "running",
                    "fingerprint": {"hash": "sha256:" + "2" * 64},
                },
            )
            return {
                "job_id": plan.job_id,
                "manifest_id": plan.manifest_id,
                "vmid": plan.vmid,
                "target_node_id": plan.target_node_id,
                "success": False,
                "status": "needs_reconciliation",
                "message": "VM post-check expected stopped, observed running",
                "observed_after": {"status": "running", "fingerprint": {"hash": "sha256:" + "2" * 64}},
                "observed_after_artifact": artifact.to_dict(),
                "artifacts": [artifact.to_dict()],
                "side_effects": ["proxmox_clone_invoked", "proxmox_task_polled", "proxmox_config_updated", "proxmox_post_check_observed"],
            }

        with patch.object(self.api_v1_router, "get_default_proxmox_mutation_client", return_value=object()):
            with patch.object(self.api_v1_router, "run_proxmox_create", side_effect=fake_create):
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(
                        self.api_v1_router.create_vm_draft_proxmox_native(
                            draft_id,
                            {
                                **approved_payload,
                                "proxmox_mutation_acknowledged": True,
                            },
                        )
                    )

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("PROXMOX_CREATE_NEEDS_RECONCILIATION", raised.exception.detail["code"])
        self.assertNotIn("manifest_status", raised.exception.detail)
        self.assertIn("proxmox_preview", raised.exception.detail)

    def test_string_false_does_not_acknowledge_yellow_risk(self):
        draft_id = "draft-api-approval-yellow"
        payload = {
            "operator_id": "api-approval-test",
            "job_id": draft_id,
            "bridge_id": "vmbr0",
            "ip_mode": "dhcp",
        }
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        self.assertEqual("yellow", plan_response["data"]["risk_summary"]["level"])
        review = plan_response["data"]["review_confirm"]

        approve_response = asyncio.run(
            self.api_v1_router.approve_vm_draft(
                draft_id,
                {
                    **payload,
                    "plan_artifact_id": review["plan_artifact_id"],
                    "review_summary_checksum": review["review_summary_checksum"],
                    "yellow_risk_acknowledged": "false",
                },
            )
        )

        decision = approve_response["data"]
        self.assertFalse(decision["can_approve"])
        self.assertFalse(decision["can_execute"])
        self.assertTrue(decision["requires_yellow_ack"])
        self.assertEqual([], decision["side_effects"])

    def test_artifact_records_are_db_backed_for_malicious_job_id(self):
        draft_id = "draft-api-path-containment"
        plan_response = asyncio.run(
            self.api_v1_router.plan_vm_draft(
                draft_id,
                {
                    "operator_id": "api-approval-test",
                    "job_id": "/tmp/gjallar-path-escape",
                    "bridge_id": "vmbr0",
                    "static_ip": "192.168.2.146",
                    "prefix": 24,
                    "gateway": "192.168.2.1",
                },
            )
        )
        for artifact in plan_response["data"]["artifacts"]:
            self.assertTrue(artifact["path"].startswith("db://job-artifacts/"))
            self.assertNotIn("/tmp/", artifact["path"])
            self.assertNotIn("..", artifact["path"])


if __name__ == "__main__":
    unittest.main()
