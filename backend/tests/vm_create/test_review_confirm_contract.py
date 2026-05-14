"""RED tests for Set 7 Review & Confirm and approval request policy."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ReviewConfirmContractTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.shared_root = Path(self._temp_dir.name) / "nfs"
        (self.shared_root / "IaC" / ".git").mkdir(parents=True)
        (self.shared_root / "IaC" / "manifests" / "vms").mkdir(parents=True)
        (self.shared_root / "IaC" / "manifests" / "networks").mkdir(parents=True)
        (self.shared_root / "IaC" / "generated").mkdir(parents=True)
        (self.shared_root / "IaC-state" / "gjallar").mkdir(parents=True)
        (self.shared_root / "IaC" / "manifests" / "networks" / "network-profiles.yaml").write_text(
            """apiVersion: gjallar/v1
kind: NetworkPolicySet
networks:
  - network_id: server-net
    display_name: Server network
    nodes:
      - node_id: yoonmanserver2
        bridge_id: vmbr0
        subnet: 192.168.2.0/24
        gateway: 192.168.2.1
        dns: [192.168.2.1]
        static_ip_ranges:
          - start: 192.168.2.142
            end: 192.168.2.150
""",
            encoding="utf-8",
        )
        self._env = patch.dict("os.environ", {"GJALLAR_SHARED_ROOT": str(self.shared_root)}, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._temp_dir.cleanup()

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
        with tempfile.TemporaryDirectory() as run_dir:
            plan = self._green_plan(run_dir)
            review = plan.review_confirm

            required_keys = {
                "vm_name",
                "vmid",
                "target_node_id",
                "storage_id",
                "template_id",
                "hardware",
                "network",
                "terraform_state_path",
                "first_power_on_included",
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
            review_path = Path(review_artifact.path)
            self.assertTrue(review_path.exists())
            summary_payload = json.loads(review_path.read_text())
            for key in required_keys:
                self.assertIn(key, summary_payload)
            self.assertEqual(review["vm_name"], summary_payload["vm_name"])
            self.assertEqual("192.168.2.143", review["network"]["static_ip"])
            self.assertEqual(25, review["network"]["prefix"])
            self.assertEqual("192.168.2.254", review["network"]["gateway"])
            self.assertFalse(review["first_power_on_included"])
            self.assertFalse(summary_payload["first_power_on_included"])
            self.assertEqual(review["planned_git_diff_summary"], summary_payload["planned_git_diff_summary"])

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
