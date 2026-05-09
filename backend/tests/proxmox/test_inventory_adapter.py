"""RED tests for the read-only Proxmox inventory adapters."""

import unittest
from unittest.mock import patch

import pytest


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
        self.assertEqual("local-lvm", vm["storage_id"])
        self.assertEqual("scsi0", vm["disks"][0]["device"])
        self.assertEqual(40, vm["disks"][0]["size_gb"])

    def test_default_adapter_stays_fake_without_live_config_or_in_fake_mode(self):
        from app.proxmox.inventory import FakeProxmoxInventoryAdapter, get_default_inventory_adapter

        with patch.dict(
            "os.environ",
            {
                "GJALLAR_INVENTORY_MODE": "fake",
                "PROXMOX_API_URL": "https://pve.example.invalid:8006/api2/json",
                "PROXMOX_API_TOKEN_ID": "root@pam!token",
                "PROXMOX_API_TOKEN_SECRET": "token-secret",
            },
            clear=False,
        ):
            adapter = get_default_inventory_adapter()

        self.assertIsInstance(adapter, FakeProxmoxInventoryAdapter)
        self.assertEqual("fake_read_only", adapter.source)

        with patch.dict("os.environ", {"GJALLAR_INVENTORY_MODE": "", "PROXMOX_API_URL": ""}, clear=False):
            adapter = get_default_inventory_adapter()

        self.assertIsInstance(adapter, FakeProxmoxInventoryAdapter)
        self.assertEqual("fake_read_only", adapter.source)

    def test_live_adapter_aggregates_multi_node_inventory_and_caches_details(self):
        try:
            from app.proxmox.inventory import LiveProxmoxInventoryAdapter
        except ModuleNotFoundError as exc:
            self.fail(f"Expected live adapter implementation for read-only inventory: {exc}")
        except ImportError as exc:
            self.fail(f"Expected LiveProxmoxInventoryAdapter export for read-only inventory: {exc}")

        payloads = {
            "/nodes": [
                {"node": "node2", "status": "online", "maxcpu": 24, "maxmem": 137438953472},
                {"node": "node10", "status": "online", "maxcpu": 16, "maxmem": 68719476736},
            ],
            "/nodes/node2/qemu": [
                {"vmid": 202, "name": "db-02", "status": "running", "template": 0, "cpus": 4, "maxmem": 8589934592},
                {"vmid": 9000, "name": "ubuntu-template", "status": "stopped", "template": 1, "cpus": 2, "maxmem": 2147483648},
            ],
            "/nodes/node10/qemu": [
                {"vmid": 101, "name": "app-01", "status": "running", "template": 0, "cpus": 2, "maxmem": 4294967296},
                {"vmid": 150, "name": "worker-01", "status": "stopped", "template": 0, "cpus": 1, "maxmem": 2147483648},
            ],
            "/nodes/node2/storage": [
                {"storage": "local-lvm", "type": "lvmthin", "total": 536870912000, "avail": 322122547200, "content": "images,rootdir"}
            ],
            "/nodes/node10/storage": [
                {"storage": "fast-nvme", "type": "dir", "total": 268435456000, "avail": 134217728000, "content": "images,iso"}
            ],
            "/nodes/node2/network": [{"iface": "vmbr0", "type": "bridge", "active": 1}],
            "/nodes/node10/network": [{"iface": "vmbr1", "type": "bridge", "active": 1}],
            "/nodes/node2/qemu/202/config": {
                "boot": "order=scsi0;net0",
                "scsi0": "local-lvm:vm-202-disk-0,size=80G,format=raw,discard=on,iothread=1",
                "ide2": "local:iso/debian.iso,media=cdrom",
                "ipconfig0": "ip=192.168.2.202/24,gw=192.168.2.1",
                "tags": "db;critical",
            },
            "/nodes/node10/qemu/101/config": {
                "scsi0": "fast-nvme:vm-101-disk-0,size=40G",
                "ipconfig0": "ip=dhcp",
            },
            "/nodes/node10/qemu/150/config": {
                "virtio0": "fast-nvme:vm-150-disk-0,size=20G",
                "ipconfig0": "ip=192.168.2.150/24",
                "agent": "0",
            },
            "/nodes/node2/qemu/9000/config": {
                "scsi0": "local-lvm:vm-9000-disk-0,size=8G",
                "ipconfig0": "ip=192.168.2.9/24",
            },
            "/nodes/node2/qemu/202/agent/network-get-interfaces": {
                "result": [
                    {
                        "name": "eth0",
                        "ip-addresses": [
                            {"ip-address-type": "ipv4", "ip-address": "192.168.2.202"},
                            {"ip-address-type": "ipv4", "ip-address": "169.254.1.10"},
                        ],
                    }
                ]
            },
            "/nodes/node10/qemu/101/agent/network-get-interfaces": {
                "result": [
                    {
                        "name": "ens18",
                        "ip-addresses": [
                            {"ip-address-type": "ipv4", "ip-address": "192.168.2.101"},
                            {"ip-address-type": "ipv6", "ip-address": "fe80::101"},
                        ],
                    }
                ]
            },
        }
        call_counts = {}

        def fake_get(path, *, timeout=None):
            call_counts[path] = call_counts.get(path, 0) + 1
            if path not in payloads:
                raise AssertionError(f"unexpected path requested: {path}")
            return payloads[path]

        adapter = LiveProxmoxInventoryAdapter(
            api_url="https://root:password@pve.example.invalid:8006/api2/json",
            token_id="root@pam!inventory",
            token_secret="top-secret",
            tls_insecure=True,
            request_get=fake_get,
            cache_ttl_seconds=60.0,
            detail_workers=4,
        )

        first_vms = [vm.to_dict() for vm in adapter.list_vms()]
        second_vms = [vm.to_dict() for vm in adapter.list_vms()]
        snapshot = adapter.snapshot().to_dict()

        self.assertEqual(first_vms, second_vms, "live inventory cache should keep repeat reads stable")
        self.assertEqual(["node2", "node10"], [node["node_id"] for node in snapshot["nodes"]])
        self.assertEqual([202, 101, 150], [vm["vmid"] for vm in first_vms])
        self.assertEqual(["192.168.2.202"], first_vms[0]["ip_addresses"])
        self.assertEqual(["192.168.2.101"], first_vms[1]["ip_addresses"])
        self.assertEqual(["192.168.2.150"], first_vms[2]["ip_addresses"])
        self.assertEqual(80, first_vms[0]["disk_gb"])
        self.assertEqual(40, first_vms[1]["disk_gb"])
        self.assertEqual(20, first_vms[2]["disk_gb"])
        self.assertEqual(1, len(first_vms[0]["disks"]))
        self.assertEqual("scsi0", first_vms[0]["disks"][0]["device"])
        self.assertEqual("local-lvm", first_vms[0]["disks"][0]["storage_id"])
        self.assertEqual("vm-202-disk-0", first_vms[0]["disks"][0]["volume"])
        self.assertTrue(first_vms[0]["disks"][0]["boot"])
        self.assertEqual("raw", first_vms[0]["disks"][0]["format"])
        self.assertEqual("on", first_vms[0]["disks"][0]["discard"])
        self.assertEqual("1", first_vms[0]["disks"][0]["iothread"])
        self.assertEqual("local-lvm", first_vms[0]["storage_id"])
        self.assertTrue(first_vms[0]["guest_agent"]["available"])
        self.assertFalse(first_vms[2]["guest_agent"]["available"])
        self.assertEqual(["db", "critical"], first_vms[0]["tags"])
        self.assertEqual(1, call_counts["/nodes/node2/qemu/202/config"])
        self.assertEqual(1, call_counts["/nodes/node10/qemu/101/config"])
        self.assertEqual(1, call_counts["/nodes/node10/qemu/150/config"])
        self.assertNotIn("top-secret", repr(snapshot))
        self.assertNotIn("root@pam!inventory", repr(snapshot))
        self.assertIn("[REDACTED]", repr(snapshot["connection"]))

        templates = [template.to_dict() for template in adapter.list_templates()]
        self.assertEqual([9000], [template["vmid"] for template in templates])
        self.assertEqual("ubuntu-template", templates[0]["template_id"])

    @pytest.mark.live_inventory
    def test_adapter_exposes_no_mutating_proxmox_methods(self):
        from app.proxmox.inventory import get_default_inventory_adapter

        adapter = get_default_inventory_adapter()
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
