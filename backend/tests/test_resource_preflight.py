import unittest

from app.domains.deploy.resource_preflight import ProvisioningResourcePreflightService


class FakeProxmoxService:
    def __init__(self):
        self.nodes = [{"id": "pve1", "status": "online"}]
        self.templates = [{"id": "pve1/9000", "template_id": "pve1/9000", "vmid": 9000, "node": "pve1"}]
        self.storages = [{"id": "local-lvm", "storage_id": "local-lvm", "content": ["images"], "available_gb": 128}]
        self.networks = [{"id": "vmbr0", "network_id": "vmbr0", "type": "bridge"}]

    def get_nodes(self):
        return self.nodes

    def get_templates(self, node=None):
        return self.templates

    def get_storages(self, node=None):
        return self.storages if node == "pve1" else []

    def get_networks(self, node=None):
        return self.networks if node == "pve1" else []


class CountingFakeProxmoxService(FakeProxmoxService):
    def __init__(self):
        super().__init__()
        self.storage_calls = 0
        self.network_calls = 0

    def get_storages(self, node=None):
        self.storage_calls += 1
        return super().get_storages(node)

    def get_networks(self, node=None):
        self.network_calls += 1
        return super().get_networks(node)


class ProvisioningResourcePreflightServiceTest(unittest.TestCase):
    def test_ready_when_selected_resources_exist(self):
        service = ProvisioningResourcePreflightService(FakeProxmoxService())

        result = service.check({
            "server_id": "pve1",
            "template_id": "pve1/9000",
            "storage_id": "local-lvm",
            "network_ids": ["vmbr0"],
        })

        self.assertEqual(result["status"], "ready")
        self.assertEqual([check["status"] for check in result["checks"]], ["ok", "ok", "ok", "ok"])
        self.assertEqual(result["next_actions"], [])

    def test_error_when_template_is_missing(self):
        fake = FakeProxmoxService()
        fake.templates = []
        service = ProvisioningResourcePreflightService(fake)

        result = service.check({
            "server_id": "pve1",
            "template_id": "pve1/9999",
            "storage_id": "local-lvm",
            "network_ids": ["vmbr0"],
        })

        self.assertEqual(result["status"], "error")
        template_check = next(check for check in result["checks"] if check["id"] == "template")
        self.assertEqual(template_check["status"], "error")
        self.assertIn("was not found", template_check["message"])

    def test_error_when_storage_is_not_available_on_target_node(self):
        fake = FakeProxmoxService()
        fake.storages = []
        service = ProvisioningResourcePreflightService(fake)

        result = service.check({
            "server_id": "pve1",
            "template_id": "pve1/9000",
            "storage_id": "missing-storage",
            "network_ids": ["vmbr0"],
        })

        self.assertEqual(result["status"], "error")
        storage_check = next(check for check in result["checks"] if check["id"] == "storage")
        self.assertEqual(storage_check["status"], "error")
        self.assertIn("not available", storage_check["message"])

    def test_error_when_network_bridge_is_missing(self):
        service = ProvisioningResourcePreflightService(FakeProxmoxService())

        result = service.check({
            "server_id": "pve1",
            "template_id": "pve1/9000",
            "storage_id": "local-lvm",
            "network_ids": ["vmbr9"],
        })

        self.assertEqual(result["status"], "error")
        network_check = next(check for check in result["checks"] if check["id"] == "networks")
        self.assertEqual(network_check["status"], "error")
        self.assertIn("vmbr9", network_check["message"])

    def test_storage_without_images_content_is_warning(self):
        fake = FakeProxmoxService()
        fake.storages = [{"id": "backup", "content": "backup,iso"}]
        service = ProvisioningResourcePreflightService(fake)

        result = service.check({
            "server_id": "pve1",
            "template_id": "pve1/9000",
            "storage_id": "backup",
            "network_ids": ["vmbr0"],
        })

        self.assertEqual(result["status"], "warning")
        storage_check = next(check for check in result["checks"] if check["id"] == "storage")
        self.assertEqual(storage_check["status"], "warning")

    def test_invalid_node_does_not_query_node_scoped_resources(self):
        fake = CountingFakeProxmoxService()
        service = ProvisioningResourcePreflightService(fake)

        result = service.check({
            "server_id": "missing-node",
            "template_id": "pve1/9000",
            "storage_id": "local-lvm",
            "network_ids": ["vmbr0"],
        })

        self.assertEqual(result["status"], "error")
        self.assertEqual(fake.storage_calls, 0)
        self.assertEqual(fake.network_calls, 0)
        node_check = next(check for check in result["checks"] if check["id"] == "target_node")
        self.assertEqual(node_check["status"], "error")


if __name__ == "__main__":
    unittest.main()
