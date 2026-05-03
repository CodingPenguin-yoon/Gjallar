import unittest

from app.domains.deploy.resource_preflight import ProvisioningResourcePreflightService


class FakeProxmoxService:
    def __init__(self):
        self.nodes = [{"id": "pve1", "status": "online"}]
        self.templates = [{"id": "pve1/9000", "template_id": "pve1/9000", "vmid": 9000, "node": "pve1"}]
        self.storages = [{"id": "local-lvm", "storage_id": "local-lvm", "content": ["images"], "available_gb": 128}]
        self.networks = [{"id": "vmbr0", "network_id": "vmbr0", "type": "bridge", "cidr": "192.168.2.0/24", "gateway": "192.168.2.1"}]
        self.vms = [{"name": "existing-vm", "server_name": "existing-vm", "vmid": 101, "node": "pve1"}]
        self.template_configs = {
            ("pve1", 9000): {
                "agent": "enabled=1",
                "scsi0": "local-lvm:base-9000-disk-0,size=40G",
                "ide2": "local-lvm:cloudinit,media=cdrom",
                "ipconfig0": "ip=dhcp",
            }
        }

    def get_nodes(self):
        return self.nodes

    def get_templates(self, node=None):
        return self.templates

    def get_storages(self, node=None):
        return self.storages if node == "pve1" else []

    def get_networks(self, node=None):
        return self.networks if node == "pve1" else []

    def get_vm_config(self, node, vmid):
        return self.template_configs.get((node, int(vmid)), {})

    def get_vms(self, node=None):
        if node is None:
            return self.vms
        return [vm for vm in self.vms if vm.get("node") == node]


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
            "server_name": "new-vm",
            "disk_size_gb": 50,
        })

        self.assertEqual(result["status"], "ready")
        check_status = {check["id"]: check["status"] for check in result["checks"]}
        self.assertEqual(check_status["target_node"], "ok")
        self.assertEqual(check_status["template"], "ok")
        self.assertEqual(check_status["template_readiness"], "ok")
        self.assertEqual(check_status["template_disk_size"], "ok")
        self.assertEqual(check_status["storage"], "ok")
        self.assertEqual(check_status["storage_capacity"], "ok")
        self.assertEqual(check_status["networks"], "ok")
        self.assertEqual(check_status["vm_identity"], "ok")
        self.assertEqual(check_status["static_network"], "ok")
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

    def test_template_readiness_warns_when_guest_agent_or_cloud_init_is_missing(self):
        fake = FakeProxmoxService()
        fake.template_configs = {("pve1", 9000): {"agent": "0"}}
        service = ProvisioningResourcePreflightService(fake)

        result = service.check({
            "server_id": "pve1",
            "template_id": "pve1/9000",
            "storage_id": "local-lvm",
            "network_ids": ["vmbr0"],
        })

        self.assertEqual(result["status"], "warning")
        readiness_check = next(check for check in result["checks"] if check["id"] == "template_readiness")
        self.assertEqual(readiness_check["status"], "warning")
        self.assertIn("guest agent", readiness_check["message"])
        self.assertIn("cloud-init", readiness_check["message"])

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

    def test_error_when_requested_vm_name_already_exists_on_target_node(self):
        service = ProvisioningResourcePreflightService(FakeProxmoxService())

        result = service.check({
            "server_id": "pve1",
            "template_id": "pve1/9000",
            "storage_id": "local-lvm",
            "network_ids": ["vmbr0"],
            "server_name": "existing-vm",
        })

        self.assertEqual(result["status"], "error")
        identity_check = next(check for check in result["checks"] if check["id"] == "vm_identity")
        self.assertEqual(identity_check["status"], "error")
        self.assertIn("already exists", identity_check["message"])

    def test_error_when_requested_vmid_already_exists_on_target_node(self):
        service = ProvisioningResourcePreflightService(FakeProxmoxService())

        result = service.check({
            "server_id": "pve1",
            "template_id": "pve1/9000",
            "storage_id": "local-lvm",
            "network_ids": ["vmbr0"],
            "server_name": "new-vm",
            "vmid": 101,
        })

        self.assertEqual(result["status"], "error")
        identity_check = next(check for check in result["checks"] if check["id"] == "vm_identity")
        self.assertEqual(identity_check["status"], "error")
        self.assertIn("VMID 101", identity_check["message"])


    def test_error_when_requested_vmid_exists_on_another_node_cluster_wide(self):
        fake = FakeProxmoxService()
        fake.vms = [
            {"name": "other-node-vm", "server_name": "other-node-vm", "vmid": 202, "node": "pve2"},
        ]
        service = ProvisioningResourcePreflightService(fake)

        result = service.check({
            "server_id": "pve1",
            "template_id": "pve1/9000",
            "storage_id": "local-lvm",
            "network_ids": ["vmbr0"],
            "server_name": "new-vm",
            "vmid": 202,
        })

        self.assertEqual(result["status"], "error")
        identity_check = next(check for check in result["checks"] if check["id"] == "vm_identity")
        self.assertEqual(identity_check["status"], "error")
        self.assertIn("Proxmox cluster", identity_check["message"])
        self.assertIn("existing_node=pve2", identity_check["detail"])


    def test_error_when_requested_disk_size_is_smaller_than_template_disk(self):
        fake = FakeProxmoxService()
        fake.template_configs[("pve1", 9000)]["scsi0"] = "local-lvm:base-9000-disk-0,size=200G"
        service = ProvisioningResourcePreflightService(fake)

        result = service.check({
            "server_id": "pve1",
            "template_id": "pve1/9000",
            "storage_id": "local-lvm",
            "network_ids": ["vmbr0"],
            "server_name": "new-vm",
            "disk_size_gb": 50,
        })

        self.assertEqual(result["status"], "error")
        disk_check = next(check for check in result["checks"] if check["id"] == "template_disk_size")
        self.assertEqual(disk_check["status"], "error")
        self.assertIn("cannot shrink", disk_check["message"])
        self.assertIn("template_disk_gb=200", disk_check["detail"])

    def test_error_when_default_disk_size_is_smaller_than_template_disk(self):
        fake = FakeProxmoxService()
        fake.template_configs[("pve1", 9000)]["scsi0"] = "local-lvm:base-9000-disk-0,size=200G"
        service = ProvisioningResourcePreflightService(fake)

        result = service.check({
            "server_id": "pve1",
            "template_id": "pve1/9000",
            "storage_id": "local-lvm",
            "network_ids": ["vmbr0"],
            "server_name": "new-vm",
        })

        self.assertEqual(result["target"]["disk_size_gb"], 50)
        self.assertEqual(result["status"], "error")
        disk_check = next(check for check in result["checks"] if check["id"] == "template_disk_size")
        self.assertEqual(disk_check["status"], "error")
        self.assertIn("Requested disk size 50GB", disk_check["message"])
        self.assertIn("template_disk_gb=200", disk_check["detail"])

    def test_error_when_requested_disk_size_exceeds_storage_free_space(self):
        service = ProvisioningResourcePreflightService(FakeProxmoxService())

        result = service.check({
            "server_id": "pve1",
            "template_id": "pve1/9000",
            "storage_id": "local-lvm",
            "network_ids": ["vmbr0"],
            "server_name": "new-vm",
            "disk_size_gb": 256,
        })

        self.assertEqual(result["status"], "error")
        capacity_check = next(check for check in result["checks"] if check["id"] == "storage_capacity")
        self.assertEqual(capacity_check["status"], "error")
        self.assertIn("exceeds", capacity_check["message"])

    def test_error_when_default_disk_size_exceeds_storage_free_space(self):
        fake = FakeProxmoxService()
        fake.storages[0]["available_gb"] = 40
        service = ProvisioningResourcePreflightService(fake)

        result = service.check({
            "server_id": "pve1",
            "template_id": "pve1/9000",
            "storage_id": "local-lvm",
            "network_ids": ["vmbr0"],
            "server_name": "new-vm",
        })

        self.assertEqual(result["target"]["disk_size_gb"], 50)
        self.assertEqual(result["status"], "error")
        capacity_check = next(check for check in result["checks"] if check["id"] == "storage_capacity")
        self.assertEqual(capacity_check["status"], "error")
        self.assertIn("50GB", capacity_check["message"])

    def test_warning_when_storage_free_space_is_unknown(self):
        fake = FakeProxmoxService()
        fake.storages = [{"id": "local-lvm", "storage_id": "local-lvm", "content": ["images"]}]
        service = ProvisioningResourcePreflightService(fake)

        result = service.check({
            "server_id": "pve1",
            "template_id": "pve1/9000",
            "storage_id": "local-lvm",
            "network_ids": ["vmbr0"],
            "server_name": "new-vm",
            "disk_size_gb": 50,
        })

        self.assertEqual(result["status"], "warning")
        capacity_check = next(check for check in result["checks"] if check["id"] == "storage_capacity")
        self.assertEqual(capacity_check["status"], "warning")

    def test_error_when_static_gateway_is_outside_vm_ip_subnet(self):
        service = ProvisioningResourcePreflightService(FakeProxmoxService())

        result = service.check({
            "server_id": "pve1",
            "template_id": "pve1/9000",
            "storage_id": "local-lvm",
            "network_ids": ["vmbr0"],
            "server_name": "new-vm",
            "vm_ip": "192.168.2.50/24",
            "vm_gateway": "192.168.3.1",
        })

        self.assertEqual(result["status"], "error")
        static_check = next(check for check in result["checks"] if check["id"] == "static_network")
        self.assertEqual(static_check["status"], "error")
        self.assertIn("same subnet", static_check["message"])


    def test_error_when_static_ip_is_network_address(self):
        service = ProvisioningResourcePreflightService(FakeProxmoxService())

        result = service.check({
            "server_id": "pve1",
            "template_id": "pve1/9000",
            "storage_id": "local-lvm",
            "network_ids": ["vmbr0"],
            "server_name": "new-vm",
            "vm_ip": "192.168.2.0/24",
            "vm_gateway": "192.168.2.1",
        })

        self.assertEqual(result["status"], "error")
        static_check = next(check for check in result["checks"] if check["id"] == "static_network")
        self.assertIn("network or broadcast", static_check["message"])

    def test_ready_when_static_network_is_valid(self):
        service = ProvisioningResourcePreflightService(FakeProxmoxService())

        result = service.check({
            "server_id": "pve1",
            "template_id": "pve1/9000",
            "storage_id": "local-lvm",
            "network_ids": ["vmbr0"],
            "server_name": "new-vm",
            "disk_size_gb": 50,
            "vm_ip": "192.168.2.50/24",
            "vm_gateway": "192.168.2.1",
        })

        self.assertEqual(result["status"], "ready")
        static_check = next(check for check in result["checks"] if check["id"] == "static_network")
        self.assertEqual(static_check["status"], "ok")


if __name__ == "__main__":
    unittest.main()
