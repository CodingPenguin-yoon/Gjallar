"""RED tests for Set 7 Review & Confirm and approval request policy."""

import json
import tempfile
import unittest

TEST_SSH_PUBLIC_KEY = (
    "ssh-ed25519 "
    "AAAAC3NzaC1lZDI1NTE5AAAAIAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8g "
    "gjallar@test"
)
TEST_SSH_FINGERPRINT = "SHA256:mKqU+0K8OhKmA8bBQi9Rz0Q5l7/g160hIP+rJYSTNj4"


class ReviewConfirmContractTests(unittest.TestCase):
    def _green_plan(self, run_dir):
        from app.proxmox.inventory import FakeProxmoxInventoryAdapter
        from app.vm_create.drafts import build_default_vm_draft
        from app.vm_create.planner import build_vm_create_plan
        from app.vm_create.preflight import run_preflight

        draft = build_default_vm_draft(
            operator_id="test-operator",
            job_id="job-set7-review",
            target_node_id="yoonmanserver2",
            bridge_id="vmbr0",
            static_ip="192.168.2.143",
            prefix=25,
            gateway="192.168.2.254",
        )
        preflight = run_preflight(draft, inventory_adapter=FakeProxmoxInventoryAdapter())
        self.assertEqual("green", preflight.risk_level)
        return build_vm_create_plan(draft, preflight, run_dir=run_dir)

    def test_review_confirm_contains_required_items_and_real_review_checksum(self):
        from app.jobs.artifacts import read_artifact_text

        with tempfile.TemporaryDirectory() as run_dir:
            plan = self._green_plan(run_dir)
            review = plan.review_confirm

            required_keys = {
                "profile_id",
                "vm_name",
                "vmid",
                "target_node_id",
                "storage_id",
                "template_id",
                "hardware",
                "profile_hardware_limits",
                "network",
                "access",
                "selected_template",
                "selected_bridge",
                "first_power_on_included",
                "power_policy",
                "smoke_timeout_summary",
                "risk_summary",
                "plan_artifact_id",
                "planned_git_diff_summary",
            }
            self.assertEqual(set(), required_keys - set(review), "missing required Review & Confirm items")
            self.assertIn("review_summary_checksum", review)
            self.assertIn("review_summary_artifact_id", review)
            self.assertTrue(review["review_summary_checksum"].startswith("sha256:"))

            artifacts_by_type = {artifact.type: artifact for artifact in plan.artifacts}
            self.assertIn("review_summary", artifacts_by_type)
            review_artifact = artifacts_by_type["review_summary"]
            self.assertEqual(review["review_summary_artifact_id"], review_artifact.artifact_id)
            self.assertEqual(review["review_summary_checksum"], review_artifact.checksum)
            self.assertTrue(review_artifact.path.startswith("db://job-artifacts/"))
            summary_payload = json.loads(read_artifact_text(review_artifact))
            for key in required_keys:
                self.assertIn(key, summary_payload)
            self.assertEqual(review["vm_name"], summary_payload["vm_name"])
            self.assertEqual("192.168.2.143", review["network"]["static_ip"])
            self.assertEqual("general-vm", review["profile_id"])
            self.assertEqual(500, review["profile_hardware_limits"]["disk_gb"]["max"])
            self.assertEqual(25, review["network"]["prefix"])
            self.assertEqual("192.168.2.254", review["network"]["gateway"])
            self.assertEqual("yoon", review["access"]["username"])
            self.assertFalse(review["access"]["password_login"])
            self.assertEqual(TEST_SSH_FINGERPRINT, review["access"]["fingerprint"])
            self.assertEqual("ubuntu-template", review["selected_template"]["template_id"])
            self.assertEqual("vmbr0", review["selected_bridge"]["bridge_id"])
            self.assertFalse(review["first_power_on_included"])
            self.assertFalse(summary_payload["first_power_on_included"])
            self.assertEqual("stopped", review["power_policy"])
            self.assertEqual("stopped", summary_payload["power_policy"])
            self.assertEqual(review["planned_git_diff_summary"], summary_payload["planned_git_diff_summary"])
            self.assertNotIn(TEST_SSH_PUBLIC_KEY.split()[1], repr(summary_payload))

    def test_approval_request_requires_plan_artifact_id_and_matching_review_checksum(self):
        try:
            from app.vm_create.approval import validate_approval_request
        except ModuleNotFoundError as exc:
            self.fail(f"Expected app.vm_create.approval.validate_approval_request for Set 7: {exc}")

        with tempfile.TemporaryDirectory() as run_dir:
            plan = self._green_plan(run_dir)
            review = plan.review_confirm

            missing_plan = validate_approval_request(
                plan,
                plan_artifact_id="",
                review_summary_checksum=review["review_summary_checksum"],
                yellow_risk_acknowledged=False,
            )
            self.assertFalse(missing_plan.can_approve)
            self.assertIn("plan_artifact_id", missing_plan.reason)

            wrong_checksum = validate_approval_request(
                plan,
                plan_artifact_id=review["plan_artifact_id"],
                review_summary_checksum="sha256:" + "0" * 64,
                yellow_risk_acknowledged=False,
            )
            self.assertFalse(wrong_checksum.can_approve)
            self.assertIn("checksum", wrong_checksum.reason.lower())

            approved = validate_approval_request(
                plan,
                plan_artifact_id=review["plan_artifact_id"],
                review_summary_checksum=review["review_summary_checksum"],
                yellow_risk_acknowledged=False,
            )
            self.assertTrue(approved.can_approve)
            self.assertTrue(approved.can_execute)
            self.assertEqual([], approved.side_effects)
            self.assertEqual("approved", approved.approval_record.decision)

    def test_approval_module_exposes_no_live_execution_methods(self):
        try:
            from app.vm_create import approval
        except (ImportError, ModuleNotFoundError) as exc:
            self.fail(f"Expected app.vm_create.approval for Set 7 no-side-effect guard: {exc}")
        forbidden = {
            "apply",
            "clone_vm",
            "commit",
            "create_vm",
            "delete_vm",
            "execute",
            "power_on",
            "push",
            "terraform_apply",
        }
        offenders = sorted(name for name in forbidden if hasattr(approval, name))
        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()
