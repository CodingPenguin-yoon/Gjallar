"""RED tests for /api/v1 VM create approval and safe execute boundary."""

import asyncio
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException


class ApiV1VmCreateApprovalExecuteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            from app.main import app
            from app.api.v1 import router as api_v1_router
        cls.paths = {getattr(route, "path", "") for route in app.routes}
        cls.api_v1_router = api_v1_router

    def test_approval_and_execute_routes_exist_under_api_v1(self):
        expected = {
            "/api/v1/vm-create/{draft_id}/approve",
            "/api/v1/vm-create/{draft_id}/execute",
        }
        missing = sorted(expected - self.paths)
        self.assertEqual([], missing, f"Missing approval/execute safety routes: {missing}")

    def test_approve_validates_exact_plan_artifacts_without_side_effects(self):
        draft_id = "draft-api-approval-green"
        payload = {
            "operator_id": "api-approval-test",
            "job_id": draft_id,
            "static_ip": "192.168.2.144",
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
            "static_ip": "192.168.2.145",
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


    def test_string_false_does_not_acknowledge_yellow_risk(self):
        draft_id = "draft-api-approval-yellow"
        payload = {
            "operator_id": "api-approval-test",
            "job_id": draft_id,
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

    def test_artifact_paths_stay_under_preview_run_root_for_malicious_job_id(self):
        draft_id = "draft-api-path-containment"
        plan_response = asyncio.run(
            self.api_v1_router.plan_vm_draft(
                draft_id,
                {
                    "operator_id": "api-approval-test",
                    "job_id": "/tmp/gjallar-path-escape",
                    "static_ip": "192.168.2.146",
                },
            )
        )
        base = Path(tempfile.gettempdir()) / "gjallar-set6-api-preview"
        base_resolved = base.resolve()
        for artifact in plan_response["data"]["artifacts"]:
            artifact_path = Path(artifact["path"]).resolve()
            self.assertTrue(
                artifact_path.is_relative_to(base_resolved),
                f"artifact path escaped preview root: {artifact_path}",
            )

    def test_execute_route_fails_closed_until_live_apply_is_approved(self):
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                self.api_v1_router.execute_vm_draft(
                    "draft-api-execute-blocked",
                    {"confirm": True, "job_id": "draft-api-execute-blocked"},
                )
            )
        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("EXECUTE_REQUIRES_EXPLICIT_LIVE_APPROVAL", raised.exception.detail["code"])
        self.assertEqual([], raised.exception.detail["side_effects"])


if __name__ == "__main__":
    unittest.main()
