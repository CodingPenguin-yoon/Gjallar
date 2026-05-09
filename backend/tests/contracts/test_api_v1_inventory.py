"""RED tests for /api/v1 inventory payloads backed by the Set 5 adapter."""

import asyncio
import contextlib
import io
import unittest


class ApiV1InventoryPayloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            from app.main import app
        cls.paths = {getattr(route, "path", "") for route in app.routes}

    def _run(self, awaitable):
        return asyncio.run(awaitable)

    def test_storage_route_exists_under_api_v1(self):
        self.assertIn(
            "/api/v1/storage",
            self.paths,
            "Set 5 read-only inventory must expose storage candidates under /api/v1.",
        )

    def test_nodes_vms_templates_networks_use_read_only_inventory_payloads(self):
        try:
            from app.api.v1 import router as v1_router
        except ModuleNotFoundError as exc:
            self.fail(f"Expected app.api.v1.router for Set 5 inventory API: {exc}")

        nodes_response = self._run(v1_router.list_nodes())
        vms_response = self._run(v1_router.list_vms())
        vm_response = self._run(v1_router.get_vm(101))
        templates_response = self._run(v1_router.list_templates())
        networks_response = self._run(v1_router.list_networks())

        for response in (nodes_response, vms_response, vm_response, templates_response, networks_response):
            self.assertTrue(response["ok"])
            self.assertIn("meta", response)
            self.assertEqual("fake_read_only", response["meta"]["source"])

        self.assertIn("yoonmanserver2", {node["node_id"] for node in nodes_response["data"]})
        vm = vm_response["data"]
        self.assertEqual(101, vm["vmid"])
        self.assertIn("192.168.2.141", vm["ip_addresses"])
        self.assertTrue(vm["guest_agent"]["available"])
        self.assertIn("ubuntu-template", {template["template_id"] for template in templates_response["data"]})
        self.assertIn("vmbr0", {network["bridge_id"] for network in networks_response["data"]})


if __name__ == "__main__":
    unittest.main()
