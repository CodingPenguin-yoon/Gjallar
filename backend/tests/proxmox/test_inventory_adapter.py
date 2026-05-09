"""RED tests for the Set 5 read-only Proxmox inventory adapter."""

import unittest


class ProxmoxInventoryAdapterTests(unittest.TestCase):
    def _adapter(self, **kwargs):
        try:
            from app.proxmox.inventory import FakeProxmoxInventoryAdapter
        except ModuleNotFoundError as exc:
            self.fail(
                "Expected app.proxmox.inventory.FakeProxmoxInventoryAdapter before "
                f"Set 5 production code is trusted: {exc}"
            )
        return FakeProxmoxInventoryAdapter(**kwargs)

    def test_fake_adapter_returns_read_only_inventory_snapshot_shape(self):
        adapter = self._adapter()

        snapshot = adapter.snapshot().to_dict()

        self.assertEqual("fake_read_only", snapshot["source"])
        self.assertEqual(
            {"yoonmanserver2", "yoonmanserver3"},
            {node["node_id"] for node in snapshot["nodes"]},
        )
        node = next(item for item in snapshot["nodes"] if item["node_id"] == "yoonmanserver2")
        self.assertEqual("online", node["status"])
        self.assertIn("vmbr0", {network["bridge_id"] for network in node["networks"]})
        self.assertTrue(node["storage"], "node inventory must include storage candidates")

        templates = {template["template_id"]: template for template in snapshot["templates"]}
        ubuntu = templates.get("ubuntu-template")
        self.assertIsNotNone(ubuntu, "MVP read-only inventory must expose an Ubuntu template candidate")
        self.assertTrue(ubuntu["cloud_init_ready"])
        self.assertTrue(ubuntu["guest_agent_ready"])

        vm = adapter.get_vm(101).to_dict()
        self.assertEqual(101, vm["vmid"])
        self.assertEqual("yoonmanserver2", vm["node_id"])
        self.assertIn("192.168.2.141", vm["ip_addresses"])
        self.assertTrue(vm["guest_agent"]["available"])
        self.assertFalse(vm["template"])

    def test_adapter_exposes_no_mutating_proxmox_methods(self):
        adapter = self._adapter()
        forbidden_methods = {
            "apply",
            "clone_vm",
            "create_vm",
            "delete_vm",
            "perform_vm_action",
            "power_off",
            "power_on",
            "reboot_vm",
            "reset_vm",
            "shutdown_vm",
            "snapshot_vm",
            "terminate_vm",
            "update_vm_resources",
        }
        offenders = sorted(name for name in forbidden_methods if hasattr(adapter, name))
        self.assertEqual([], offenders, f"Set 5 adapter must be read-only only: {offenders}")

    def test_connection_context_and_snapshot_are_secret_safe(self):
        adapter = self._adapter(
            source_config={
                "api_url": "https://operator:raw-url-password@pve.example.invalid:8006/api2/json",
                "token_id": "root@pam!raw-token-id",
                "token_secret": "raw-token-secret",
            }
        )

        connection = adapter.redacted_connection_context()
        rendered = repr(connection) + repr(adapter.snapshot().to_dict())

        self.assertNotIn("\x01", connection["api_url"])
        self.assertNotIn("\x02", connection["api_url"])
        self.assertIn("https://operator:[REDACTED]@pve.example.invalid", connection["api_url"])
        self.assertNotIn("raw-url-password", rendered)
        self.assertNotIn("raw-token-id", rendered)
        self.assertNotIn("raw-token-secret", rendered)
        self.assertNotIn("operator:raw-url-password", rendered)
        self.assertIn("[REDACTED]", rendered)


if __name__ == "__main__":
    unittest.main()
