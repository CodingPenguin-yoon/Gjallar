"""RED tests for Set 6 create draft/preflight/plan contract."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class VmCreatePreflightPlanContractTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.shared_root = Path(self._temp_dir.name) / "nfs"
        (self.shared_root / "IaC" / ".git").mkdir(parents=True)
        (self.shared_root / "IaC" / "manifests" / "vms").mkdir(parents=True)
        (self.shared_root / "IaC" / "manifests" / "networks").mkdir(parents=True)
        (self.shared_root / "IaC" / "generated").mkdir(parents=True)
        (self.shared_root / "IaC-state" / "gjallar").mkdir(parents=True)
        self._write_default_network_policy()
        self._env = patch.dict("os.environ", {"GJALLAR_SHARED_ROOT": str(self.shared_root)}, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._temp_dir.cleanup()

    def _default_draft(self, **kwargs):
        try:
            from app.vm_create.drafts import build_default_vm_draft
        except ModuleNotFoundError as exc:
            self.fail(f"Expected app.vm_create.drafts for Set 6 draft contract: {exc}")
        draft_kwargs = {
            "target_node_id": "yoonmanserver2",
            "bridge_id": "vmbr0",
            "static_ip": "192.168.2.142",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }
        draft_kwargs.update(kwargs)
        return build_default_vm_draft(operator_id="test-operator", job_id="job-set6-test", **draft_kwargs)

    def _write_default_network_policy(self):
        policy_path = self.shared_root / "IaC" / "manifests" / "networks" / "network-profiles.yaml"
        policy_path.write_text(
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
      - node_id: yoonmanserver3
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

    def _preflight(self, draft):
        try:
            from app.proxmox.inventory import FakeProxmoxInventoryAdapter
            from app.vm_create.preflight import run_preflight
        except ModuleNotFoundError as exc:
            self.fail(f"Expected app.vm_create.preflight for Set 6 preflight contract: {exc}")
        return run_preflight(draft, inventory_adapter=FakeProxmoxInventoryAdapter())

    def _preflight_with_adapter(self, draft, adapter):
        try:
            from app.vm_create.preflight import run_preflight
        except ModuleNotFoundError as exc:
            self.fail(f"Expected app.vm_create.preflight for Set 6 preflight contract: {exc}")
        return run_preflight(draft, inventory_adapter=adapter)

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
            "profile_enabled",
            "profile_cpu_range",
            "profile_memory_mb_range",
            "profile_disk_gb_range",
            "template_available",
            "template_cloud_init_ready",
            "template_guest_agent_ready",
            "template_disk_floor",
            "target_node_online",
            "storage_available",
            "bridge_selection",
            "bridge_exists",
            "static_ip_present",
            "static_ip_valid",
            "static_prefix_present",
            "static_prefix_valid",
            "static_gateway_present",
            "static_gateway_valid",
            "vmid_available",
            "name_available",
            "static_ip_available",
            "iac_root_available",
            "iac_git_repo_available",
            "terraform_state_root_available",
            "terraform_state_lock_available",
            "destroy_delete_plan_absent",
            "credential_scope_read_only",
        }:
            self.assertIn(code, check_codes)

    def test_preflight_uses_explicit_node_storage_selection(self):
        draft = self._default_draft(
            target_node_id="yoonmanserver2",
            static_ip="192.168.2.142",
            storage_id="local-lvm",
        )

        result = self._preflight(draft)

        self.assertEqual("green", result.risk_level)
        self.assertEqual("local-lvm", result.selected_storage_id)

    def test_preflight_rejects_storage_not_attached_to_selected_node(self):
        draft = self._default_draft(
            target_node_id="yoonmanserver2",
            static_ip="192.168.2.142",
            storage_id="missing-storage",
        )

        result = self._preflight(draft)

        self.assertEqual("red", result.risk_level)
        red_codes = {risk.code for risk in result.risks if risk.level == "red"}
        self.assertIn("storage_unavailable", red_codes)

    def test_preflight_rejects_disk_smaller_than_selected_template(self):
        undersized = self._default_draft(
            target_node_id="yoonmanserver2",
            static_ip="192.168.2.142",
            hardware_overrides={"disk_gb": 40},
        )

        result = self._preflight(undersized)

        self.assertEqual("red", result.risk_level)
        red_codes = {risk.code for risk in result.risks if risk.level == "red"}
        self.assertIn("template_disk_larger_than_requested", red_codes)

    def test_preflight_red_blocks_unknown_profile_without_fallback(self):
        draft = self._default_draft(profile_id="unknown-profile", static_ip="192.168.2.142")

        result = self._preflight(draft)

        self.assertEqual("red", result.risk_level)
        red_codes = {risk.code for risk in result.risks if risk.level == "red"}
        self.assertIn("unknown_profile", red_codes)
        self.assertIn("disabled_profile", red_codes)
        self.assertEqual("unknown-profile", result.profile_id)

    def test_preflight_red_blocks_profile_hardware_outside_limits(self):
        cases = {
            "cpu": ({"cpu": 9}, "profile_cpu_out_of_range"),
            "memory": ({"memory_mb": 512}, "profile_memory_mb_out_of_range"),
            "disk": ({"disk_gb": 501}, "profile_disk_gb_out_of_range"),
        }
        for name, (hardware_overrides, expected_code) in cases.items():
            with self.subTest(name=name):
                draft = self._default_draft(
                    static_ip="192.168.2.142",
                    hardware_overrides=hardware_overrides,
                )

                result = self._preflight(draft)

                self.assertEqual("red", result.risk_level)
                red_codes = {risk.code for risk in result.risks if risk.level == "red"}
                self.assertIn(expected_code, red_codes)

    def test_preflight_red_blocks_template_disk_above_profile_max(self):
        from app.proxmox.inventory import FakeProxmoxInventoryAdapter
        from app.proxmox.models import TemplateInventory

        class LargeTemplateAdapter(FakeProxmoxInventoryAdapter):
            def __init__(self):
                super().__init__()
                self._templates = (
                    TemplateInventory(
                        template_id="huge-template",
                        vmid=9001,
                        name="ubuntu-huge-template",
                        node_id="yoonmanserver2",
                        storage_id="local-lvm",
                        family="ubuntu",
                        cloud_init_ready=True,
                        guest_agent_ready=True,
                        disk_gb=600,
                    ),
                )

        draft = self._default_draft(
            static_ip="192.168.2.142",
            template_id="huge-template",
            hardware_overrides={"disk_gb": 600},
        )

        result = self._preflight_with_adapter(draft, LargeTemplateAdapter())

        self.assertEqual("red", result.risk_level)
        red_codes = {risk.code for risk in result.risks if risk.level == "red"}
        self.assertIn("profile_disk_gb_out_of_range", red_codes)
        self.assertIn("template_disk_exceeds_profile_max", red_codes)

    def test_missing_bridge_id_is_red_without_server_net_fallback_or_live_mutation(self):
        draft = self._default_draft(bridge_id=None, static_ip="192.168.2.142")

        result = self._preflight(draft)

        self.assertEqual("red", result.risk_level)
        red_codes = {risk.code for risk in result.risks if risk.level == "red"}
        self.assertIn("bridge_id_missing", red_codes)
        self.assertIn("bridge_missing_or_inactive", red_codes)
        self.assertIsNone(result.selected_bridge_id)
        self.assertNotIn("server-net", repr(result.to_dict()))
        self.assertEqual([], result.side_effects)

    def test_missing_inactive_or_wrong_node_bridge_is_red(self):
        from app.proxmox.inventory import FakeProxmoxInventoryAdapter
        from app.proxmox.models import NetworkInventory

        class BridgeAdapter(FakeProxmoxInventoryAdapter):
            def __init__(self, networks):
                super().__init__()
                self._networks = tuple(networks)

        cases = {
            "missing": ("vmbr9", []),
            "inactive": ("vmbr0", [NetworkInventory(bridge_id="vmbr0", node_id="yoonmanserver2", active=False)]),
            "wrong-node": ("vmbr9", [NetworkInventory(bridge_id="vmbr9", node_id="yoonmanserver3", active=True)]),
        }
        for name, (bridge_id, networks) in cases.items():
            with self.subTest(name=name):
                draft = self._default_draft(bridge_id=bridge_id)
                result = self._preflight_with_adapter(draft, BridgeAdapter(networks))

                self.assertEqual("red", result.risk_level)
                red_codes = {risk.code for risk in result.risks if risk.level == "red"}
                self.assertIn("bridge_missing_or_inactive", red_codes)
                self.assertEqual(bridge_id, result.selected_bridge_id)

    def test_live_read_only_inventory_source_is_allowed(self):
        from app.proxmox.inventory import FakeProxmoxInventoryAdapter
        from app.vm_create.preflight import run_preflight

        class LiveReadOnlyAdapter(FakeProxmoxInventoryAdapter):
            source = "live_read_only"

        draft = self._default_draft(target_node_id="yoonmanserver2", static_ip="192.168.2.142")

        result = run_preflight(draft, inventory_adapter=LiveReadOnlyAdapter())

        red_codes = {risk.code for risk in result.risks if risk.level == "red"}
        self.assertNotIn("inventory_adapter_not_read_only", red_codes)
        self.assertEqual([], result.side_effects)

    def test_explicit_active_bridge_passes_without_network_policy_file(self):
        policy_path = self.shared_root / "IaC" / "manifests" / "networks" / "network-profiles.yaml"
        policy_path.unlink()
        draft = self._default_draft(target_node_id="yoonmanserver2", static_ip="192.168.2.142")

        result = self._preflight(draft)

        self.assertEqual("green", result.risk_level)
        red_codes = {risk.code for risk in result.risks if risk.level == "red"}
        self.assertNotIn("network_policy_missing", red_codes)
        self.assertNotIn("network_policy_unreadable", red_codes)

    def test_network_policy_out_of_range_is_not_red(self):
        draft = self._default_draft(target_node_id="yoonmanserver2", static_ip="192.168.2.200")

        result = self._preflight(draft)

        self.assertEqual("green", result.risk_level)
        red_codes = {risk.code for risk in result.risks if risk.level == "red"}
        self.assertNotIn("static_ip_out_of_range", red_codes)
        self.assertNotIn("static_ip_unavailable", red_codes)

    def test_observed_static_ip_conflict_remains_red(self):
        draft = self._default_draft(target_node_id="yoonmanserver2", static_ip="192.168.2.141")

        result = self._preflight(draft)

        self.assertEqual("red", result.risk_level)
        red_codes = {risk.code for risk in result.risks if risk.level == "red"}
        self.assertIn("static_ip_unavailable", red_codes)

    def test_static_mode_missing_static_ip_is_red(self):
        draft = self._default_draft(static_ip=None)

        result = self._preflight(draft)

        self.assertEqual("red", result.risk_level)
        red_codes = {risk.code for risk in result.risks if risk.level == "red"}
        self.assertIn("static_ip_missing", red_codes)

    def test_static_mode_missing_prefix_is_red(self):
        draft = self._default_draft(prefix=None)

        result = self._preflight(draft)

        self.assertEqual("red", result.risk_level)
        red_codes = {risk.code for risk in result.risks if risk.level == "red"}
        self.assertIn("static_prefix_missing", red_codes)

    def test_static_mode_missing_gateway_is_red(self):
        draft = self._default_draft(gateway=None)

        result = self._preflight(draft)

        self.assertEqual("red", result.risk_level)
        red_codes = {risk.code for risk in result.risks if risk.level == "red"}
        self.assertIn("static_gateway_missing", red_codes)

    def test_static_mode_invalid_prefix_is_red(self):
        draft = self._default_draft(prefix=33)

        result = self._preflight(draft)

        self.assertEqual("red", result.risk_level)
        red_codes = {risk.code for risk in result.risks if risk.level == "red"}
        self.assertIn("static_prefix_invalid", red_codes)

    def test_static_mode_invalid_gateway_is_red(self):
        draft = self._default_draft(gateway="192.168.2.999")

        result = self._preflight(draft)

        self.assertEqual("red", result.risk_level)
        red_codes = {risk.code for risk in result.risks if risk.level == "red"}
        self.assertIn("static_gateway_invalid", red_codes)

    def test_plan_response_contains_review_ready_fields_and_real_artifacts(self):
        try:
            from app.vm_create.planner import build_vm_create_plan
        except ModuleNotFoundError as exc:
            self.fail(f"Expected app.vm_create.planner for Set 6 plan contract: {exc}")
        draft = self._default_draft(
            target_node_id="yoonmanserver2",
            static_ip="192.168.2.142",
            prefix=25,
            gateway="192.168.2.254",
        )
        preflight = self._preflight(draft)
        self.assertEqual("green", preflight.risk_level)

        with tempfile.TemporaryDirectory() as run_dir:
            plan = build_vm_create_plan(draft, preflight, run_dir=run_dir)
            rendered = repr(plan.to_dict())
            artifacts_by_type = {artifact.type: artifact for artifact in plan.artifacts}
            manifest_text = Path(artifacts_by_type["vm_instance_manifest"].path).read_text(encoding="utf-8")

        self.assertEqual("dry_run_plan_only", plan.execution_intent)
        self.assertEqual("general-vm", plan.profile_id)
        self.assertEqual([], plan.side_effects)
        self.assertTrue(plan.vm_name.startswith("gjallar-vm-"))
        self.assertIsInstance(plan.vmid, int)
        self.assertNotIn(plan.vmid, {101, 9000})
        self.assertEqual("yoonmanserver2", plan.target_node_id)
        self.assertEqual("local-lvm", plan.storage_id)
        self.assertEqual("ubuntu-template", plan.template_id)
        self.assertEqual({"cpu": 2, "memory_mb": 4096, "disk_gb": 50}, plan.hardware)
        self.assertEqual(2, plan.profile_hardware_limits["cpu"]["default"])
        self.assertEqual(8, plan.profile_hardware_limits["cpu"]["max"])
        self.assertEqual("vmbr0", plan.network["bridge_id"])
        self.assertEqual("192.168.2.142", plan.network["static_ip"])
        self.assertEqual(25, plan.network["prefix"])
        self.assertEqual("192.168.2.254", plan.network["gateway"])
        self.assertEqual("192.168.2.142", plan.network["ip_address"])
        self.assertEqual(plan.network, plan.review_confirm["network"])
        self.assertEqual("general-vm", plan.review_confirm["profile_id"])
        self.assertEqual(plan.profile_hardware_limits, plan.review_confirm["profile_hardware_limits"])
        self.assertNotIn("network_id", plan.network)
        self.assertNotIn("networkId", rendered)
        self.assertNotIn("network_id", rendered)
        self.assertNotIn("server-net", rendered)
        self.assertNotIn("profile_id:", manifest_text.split("network:", 1)[1])
        self.assertIn("/IaC-state/gjallar/", plan.terraform_state_path)
        self.assertEqual(str(self.shared_root / "IaC"), plan.review_confirm["iac_root"])
        self.assertEqual(str(self.shared_root / "IaC-state" / "gjallar"), plan.review_confirm["terraform_state_root"])
        self.assertTrue(plan.review_confirm["iac_ready_for_plan"])
        self.assertTrue(plan.review_confirm["iac_ready_for_execute"])
        self.assertFalse(plan.first_power_on_included)
        self.assertFalse(plan.review_confirm["first_power_on_included"])
        self.assertEqual(15, plan.smoke_timeout_summary["cloud_init_minutes"])
        self.assertEqual("green", plan.risk_summary["level"])
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
