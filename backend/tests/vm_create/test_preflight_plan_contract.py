"""RED tests for Set 6 create draft/preflight/plan contract."""

import tempfile
import unittest


class VmCreatePreflightPlanContractTests(unittest.TestCase):
    def _default_draft(self, **kwargs):
        try:
            from app.vm_create.drafts import build_default_vm_draft
        except ModuleNotFoundError as exc:
            self.fail(f"Expected app.vm_create.drafts for Set 6 draft contract: {exc}")
        return build_default_vm_draft(operator_id="test-operator", job_id="job-set6-test", **kwargs)

    def _preflight(self, draft):
        try:
            from app.proxmox.inventory import FakeProxmoxInventoryAdapter
            from app.vm_create.preflight import run_preflight
        except ModuleNotFoundError as exc:
            self.fail(f"Expected app.vm_create.preflight for Set 6 preflight contract: {exc}")
        return run_preflight(draft, inventory_adapter=FakeProxmoxInventoryAdapter())

    def test_preflight_uses_read_only_inventory_and_returns_green_for_prd_defaults(self):
        draft = self._default_draft(target_node_id="yoonmanserver2", static_ip="192.168.2.142")

        result = self._preflight(draft)

        self.assertEqual("green", result.risk_level)
        self.assertEqual([], [risk.code for risk in result.risks if risk.level == "red"])
        self.assertEqual("fake_read_only", result.inventory_source)
        self.assertEqual("local-lvm", result.selected_storage_id)
        self.assertEqual("ubuntu-template", result.selected_template_id)
        check_codes = {check.code for check in result.checks}
        for code in {
            "profile_schema",
            "template_available",
            "target_node_online",
            "storage_available",
            "bridge_mapping",
            "bridge_exists",
            "vmid_available",
            "name_available",
            "static_ip_available",
            "terraform_state_lock_available",
            "destroy_delete_plan_absent",
            "credential_scope_read_only",
        }:
            self.assertIn(code, check_codes)

    def test_missing_bridge_mapping_is_red_without_live_mutation(self):
        draft = self._default_draft(target_node_id="unknown-node", static_ip="192.168.2.142")

        result = self._preflight(draft)

        self.assertEqual("red", result.risk_level)
        red_codes = {risk.code for risk in result.risks if risk.level == "red"}
        self.assertIn("bridge_mapping_missing", red_codes)
        self.assertEqual([], result.side_effects)

    def test_plan_response_contains_review_ready_fields_and_real_artifacts(self):
        try:
            from app.vm_create.planner import build_vm_create_plan
        except ModuleNotFoundError as exc:
            self.fail(f"Expected app.vm_create.planner for Set 6 plan contract: {exc}")
        draft = self._default_draft(target_node_id="yoonmanserver2", static_ip="192.168.2.142")
        preflight = self._preflight(draft)
        self.assertEqual("green", preflight.risk_level)

        with tempfile.TemporaryDirectory() as run_dir:
            plan = build_vm_create_plan(draft, preflight, run_dir=run_dir)
            rendered = repr(plan.to_dict())

        self.assertEqual("dry_run_plan_only", plan.execution_intent)
        self.assertEqual([], plan.side_effects)
        self.assertTrue(plan.vm_name.startswith("gjallar-vm-"))
        self.assertIsInstance(plan.vmid, int)
        self.assertNotIn(plan.vmid, {101, 9000})
        self.assertEqual("yoonmanserver2", plan.target_node_id)
        self.assertEqual("local-lvm", plan.storage_id)
        self.assertEqual("ubuntu-template", plan.template_id)
        self.assertEqual({"cpu": 2, "memory_mb": 4096, "disk_gb": 40}, plan.hardware)
        self.assertEqual("vmbr0", plan.network["bridge_id"])
        self.assertEqual("192.168.2.142", plan.network["ip_address"])
        self.assertIn("/mnt/hermes_data/공통/iac-state/gjallar/", plan.terraform_state_path)
        self.assertTrue(plan.first_power_on_included)
        self.assertEqual(15, plan.smoke_timeout_summary["cloud_init_minutes"])
        self.assertEqual("green", plan.risk_summary["level"])
        artifacts_by_type = {artifact.type: artifact for artifact in plan.artifacts}
        self.assertIn("preflight_report", artifacts_by_type)
        self.assertIn("plan", artifacts_by_type)
        for artifact in artifacts_by_type.values():
            self.assertTrue(artifact.checksum.startswith("sha256:"))
        self.assertIn("planned_git_diff_summary", plan.review_confirm)
        self.assertNotIn("raw-token-secret", rendered)
        self.assertNotIn("operator:raw-url-password", rendered)

    def test_set6_modules_expose_no_live_side_effect_operations(self):
        try:
            from app.vm_create import drafts, planner, preflight
        except ModuleNotFoundError as exc:
            self.fail(f"Expected app.vm_create modules for Set 6 no-side-effect guard: {exc}")
        forbidden = {
            "apply",
            "clone_vm",
            "commit",
            "create_vm",
            "delete_vm",
            "power_on",
            "push",
            "terraform_apply",
        }
        offenders = []
        for module in (drafts, preflight, planner):
            offenders.extend(f"{module.__name__}.{name}" for name in forbidden if hasattr(module, name))
        self.assertEqual([], sorted(offenders))


if __name__ == "__main__":
    unittest.main()
