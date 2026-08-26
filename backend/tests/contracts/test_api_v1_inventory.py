"""RED tests for /api/v1 inventory payloads backed by the Set 5 adapter."""

import asyncio
import contextlib
import io
import inspect
import unittest
from unittest.mock import patch

import requests
from fastapi import HTTPException


class ApiV1InventoryPayloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            from app.main import app
        cls.paths = {getattr(route, "path", "") for route in app.routes}

    def _run(self, awaitable):
        if inspect.isawaitable(awaitable):
            return asyncio.run(awaitable)
        return awaitable

    def test_storage_route_exists_under_api_v1(self):
        self.assertIn(
            "/api/v1/storage",
            self.paths,
            "Set 5 read-only inventory must expose storage candidates under /api/v1.",
        )
        self.assertIn("/api/v1/setup/proxmox/connection", self.paths)

    def test_connection_status_reports_unconfigured_without_returning_fixture_inventory(self):
        from app.proxmox.inventory import UnavailableProxmoxInventoryAdapter
        from app.workloads.inventory import WorkloadInventoryQuery
        from app.api.v1 import inventory as v1_router

        query = WorkloadInventoryQuery(
            UnavailableProxmoxInventoryAdapter(
                reason="proxmox_inventory_configuration_missing",
                requested_mode="live",
                missing_configuration=("PROXMOX_API_TOKEN_SECRET",),
            )
        )
        with patch.object(v1_router.inventory_context, "inventory_query", return_value=query):
            status_response = self._run(v1_router.get_proxmox_connection_status())
            with self.assertRaises(HTTPException) as raised:
                self._run(v1_router.list_nodes())

        self.assertEqual("unconfigured", status_response["data"]["state"])
        self.assertFalse(status_response["data"]["inventory_available"])
        self.assertEqual(["PROXMOX_API_TOKEN_SECRET"], status_response["data"]["missing_configuration"])
        self.assertEqual(503, raised.exception.status_code)
        self.assertEqual("PROXMOX_INVENTORY_UNCONFIGURED", raised.exception.detail["code"])
        self.assertEqual([], raised.exception.detail["side_effects"])

    def test_connection_status_reports_degraded_with_safe_reason(self):
        from app.workloads.inventory import WorkloadInventoryQuery
        from app.api.v1 import inventory as v1_router

        class BrokenLiveAdapter:
            source = "live_read_only"
            cluster_id = "cluster-a"
            is_test_fixture = False

            def snapshot(self):
                raise requests.exceptions.ConnectionError("secret-bearing upstream detail")

        with patch.object(
            v1_router.inventory_context,
            "inventory_query",
            return_value=WorkloadInventoryQuery(BrokenLiveAdapter()),
        ):
            status_response = self._run(v1_router.get_proxmox_connection_status())
            with self.assertRaises(HTTPException) as raised:
                self._run(v1_router.list_vms())

        self.assertEqual("degraded", status_response["data"]["state"])
        self.assertEqual("proxmox_connection_unreachable", status_response["data"]["reason"])
        self.assertNotIn("secret-bearing", str(status_response))
        self.assertEqual("PROXMOX_INVENTORY_DEGRADED", raised.exception.detail["code"])

    def test_jobs_and_risks_remain_available_when_proxmox_is_unconfigured(self):
        from app.proxmox.inventory import UnavailableProxmoxInventoryAdapter
        from app.workloads.inventory import WorkloadInventoryQuery
        from app.api.v1 import inventory as inventory_api
        from app.api.v1 import jobs_compat as jobs_api

        query = WorkloadInventoryQuery(
            UnavailableProxmoxInventoryAdapter(
                reason="proxmox_inventory_configuration_missing",
                requested_mode="live",
            )
        )
        with patch.object(inventory_api.inventory_context, "inventory_query", return_value=query):
            jobs_response = self._run(jobs_api.list_jobs())
            risks_response = self._run(jobs_api.list_risks())

        self.assertTrue(jobs_response["ok"])
        self.assertTrue(risks_response["ok"])
        self.assertEqual("unavailable", jobs_response["meta"]["source"])
        self.assertEqual("unavailable", risks_response["meta"]["source"])

    def test_nodes_vms_templates_networks_use_read_only_inventory_payloads(self):
        try:
            from app.api.v1 import inventory as v1_router
        except ModuleNotFoundError as exc:
            self.fail(f"Expected app.api.v1.inventory for Set 5 inventory API: {exc}")

        nodes_response = self._run(v1_router.list_nodes())
        vms_response = self._run(v1_router.list_vms())
        vm_response = self._run(v1_router.get_vm(101))
        templates_response = self._run(v1_router.list_templates())
        storage_response = self._run(v1_router.list_storage())
        networks_response = self._run(v1_router.list_networks())
        cluster_response = self._run(v1_router.cluster_summary())

        for response in (
            nodes_response,
            vms_response,
            vm_response,
            templates_response,
            storage_response,
            networks_response,
            cluster_response,
        ):
            self.assertTrue(response["ok"])
            self.assertIn("meta", response)
            self.assertEqual("fake_read_only", response["meta"]["source"])
            self.assertEqual("test_fixture", response["meta"]["connection"]["state"])
            self.assertTrue(response["meta"]["availability"]["available"])
            self.assertTrue(response["meta"]["availability"]["complete"])

        self.assertIn("yoonmanserver2", {node["node_id"] for node in nodes_response["data"]})
        vm = vm_response["data"]
        self.assertEqual(101, vm["vmid"])
        self.assertIn("192.168.2.141", vm["ip_addresses"])
        self.assertTrue(vm["guest_agent"]["available"])
        self.assertIn("ip_evidence", vm)
        self.assertEqual("192.168.2.141", vm["ip_evidence"][0]["ip_address"])
        self.assertEqual("primary", vm["ip_evidence"][0]["scope"])
        self.assertTrue(vm["ip_evidence"][0]["duplicate_warning_eligible"])
        self.assertIn("nic_bridge_evidence", vm)
        self.assertEqual("net0", vm["nic_bridge_evidence"][0]["interface_name"])
        self.assertEqual("vmbr0", vm["nic_bridge_evidence"][0]["bridge_id"])
        self.assertEqual("config", vm["nic_bridge_evidence"][0]["source"])
        self.assertEqual("proxmox_net_config", vm["nic_bridge_evidence"][0]["interface_type"])
        list_vm = next(item for item in vms_response["data"] if item["vmid"] == 101)
        self.assertIn("ip_evidence", list_vm)
        self.assertIn("nic_bridge_evidence", list_vm)
        self.assertEqual("vmbr0", list_vm["nic_bridge_evidence"][0]["bridge_id"])
        self.assertIn("ubuntu-template", {template["template_id"] for template in templates_response["data"]})
        self.assertIn("vmbr0", {network["bridge_id"] for network in networks_response["data"]})
        network = next(item for item in networks_response["data"] if item["bridge_id"] == "vmbr0")
        self.assertEqual("192.168.2.0/24", network["cidr"])
        self.assertEqual("192.168.2.1", network["gateway"])
        self.assertEqual(["eno1"], network["bridge_ports"])
        self.assertIn("prefix", network)
        self.assertIn("vlan_aware", network)

    def test_inventory_routes_accept_live_read_only_adapter_without_mutating_controls(self):
        from app.proxmox.models import (
            GuestAgentInventory,
            IpEvidenceInventory,
            InventorySnapshot,
            NetworkInventory,
            NodeInventory,
            StorageInventory,
            TemplateInventory,
            VmInventory,
        )

        try:
            from app.api.v1 import inventory as v1_router
        except ModuleNotFoundError as exc:
            self.fail(f"Expected app.api.v1.inventory for Set 5 inventory API: {exc}")

        class StubLiveAdapter:
            source = "live_read_only"
            cluster_id = "runtime-cluster-a"

            def __init__(self):
                self.snapshot_calls = 0
                storage = StorageInventory(
                    storage_id="local-lvm",
                    node_id="node-a",
                    type="lvmthin",
                    total_gb=512,
                    free_gb=256,
                    content=("images", "rootdir"),
                )
                network = NetworkInventory(
                    bridge_id="vmbr0",
                    node_id="node-a",
                    address="192.168.2.10",
                    prefix=24,
                    cidr="192.168.2.0/24",
                    gateway="192.168.2.1",
                    bridge_ports=("eno1",),
                )
                self._nodes = [
                    NodeInventory(
                        node_id="node-a",
                        display_name="node-a",
                        status="online",
                        cpu_total=16,
                        memory_total_mb=65536,
                        storage=(storage,),
                        networks=(network,),
                    )
                ]
                self._vms = [
                    VmInventory(
                        vmid=301,
                        name="live-app-01",
                        node_id="node-a",
                        status="running",
                        template=False,
                        cpu=2,
                        memory_mb=4096,
                        disk_gb=40,
                        ip_addresses=("192.168.2.301",),
                        ip_evidence=(
                            IpEvidenceInventory(
                                ip_address="192.168.2.301",
                                source="guest_agent",
                                interface_name="ens18",
                                interface_type="linux_nic",
                                scope="primary",
                                primary_candidate=True,
                                duplicate_warning_eligible=True,
                            ),
                        ),
                        guest_agent=GuestAgentInventory(available=True, ip_addresses=("192.168.2.301",)),
                        storage_id="local-lvm",
                    )
                ]
                self._templates = [
                    TemplateInventory(
                        template_id="ubuntu-template",
                        vmid=9000,
                        name="ubuntu-template",
                        node_id="node-a",
                        storage_id="local-lvm",
                        family="ubuntu",
                        cloud_init_ready=True,
                        guest_agent_ready=True,
                    )
                ]

            def redacted_connection_context(self):
                return {"source": self.source, "api_url": "https://root:[REDACTED]@pve.example.invalid:8006/api2/json"}

            def snapshot(self):
                self.snapshot_calls += 1
                return InventorySnapshot(
                    source=self.source,
                    observed_at="2026-05-09T10:00:00+09:00",
                    nodes=tuple(self._nodes),
                    vms=tuple(self._vms),
                    templates=tuple(self._templates),
                    connection=self.redacted_connection_context(),
                )

            def list_nodes(self):
                return list(self._nodes)

            def list_vms(self):
                return list(self._vms)

            def get_vm(self, vmid):
                return self._vms[0] if vmid == 301 else None

            def list_templates(self):
                return list(self._templates)

            def list_storage(self, node_id=None):
                items = list(self._nodes[0].storage)
                return [item for item in items if node_id is None or item.node_id == node_id]

            def list_networks(self, node_id=None):
                items = list(self._nodes[0].networks)
                return [item for item in items if node_id is None or item.node_id == node_id]

        from app.workloads.inventory import WorkloadInventoryQuery

        adapter = StubLiveAdapter()
        query = WorkloadInventoryQuery(adapter)
        with patch.object(v1_router.inventory_context, "inventory_query", return_value=query):
            cluster_response = self._run(v1_router.cluster_summary())
            vms_response = self._run(v1_router.list_vms())
            vm_response = self._run(v1_router.get_vm(301))

        self.assertTrue(cluster_response["ok"])
        self.assertEqual("live_read_only", cluster_response["meta"]["source"])
        self.assertEqual("live", cluster_response["meta"]["connection"]["state"])
        self.assertEqual("2026-05-09T10:00:00+09:00", cluster_response["meta"]["observed_at"])
        self.assertEqual("fresh", cluster_response["meta"]["freshness"])
        self.assertEqual("runtime-cluster-a", cluster_response["data"]["cluster_id"])
        self.assertEqual(1, cluster_response["data"]["vm_count"])
        self.assertEqual("live-app-01", vm_response["data"]["name"])
        self.assertEqual(["192.168.2.301"], vm_response["data"]["ip_addresses"])
        self.assertEqual("ens18", vm_response["data"]["ip_evidence"][0]["interface_name"])
        self.assertTrue(vm_response["data"]["ip_evidence"][0]["duplicate_warning_eligible"])
        self.assertEqual([], vm_response["data"]["nic_bridge_evidence"])
        self.assertIn("disks", vm_response["data"])
        self.assertEqual("local-lvm", vm_response["data"]["storage_id"])
        self.assertEqual(
            [],
            [
                name
                for name in ("delete_vm", "perform_vm_action", "update_vm_resources")
                if hasattr(adapter, name)
            ],
        )
        self.assertEqual([301], [vm["vmid"] for vm in vms_response["data"]])
        self.assertIn("ip_evidence", vms_response["data"][0])
        self.assertEqual([], vms_response["data"][0]["nic_bridge_evidence"])
        self.assertEqual(3, adapter.snapshot_calls, "each inventory response must project data and meta from one snapshot")

    def test_partial_inventory_remains_readable_but_is_rejected_by_mutation_provider(self):
        from app.api.v1 import inventory as v1_router
        from app.proxmox.models import (
            InventoryAvailability,
            InventorySnapshot,
            InventorySourceAvailability,
            VmInventory,
        )
        from app.workloads.inventory import WorkloadInventoryQuery

        class PartialLiveAdapter:
            source = "live_read_only"
            cluster_id = "runtime-cluster-a"
            is_test_fixture = False

            def snapshot(self):
                return InventorySnapshot(
                    source=self.source,
                    observed_at="2026-08-26T12:00:00+09:00",
                    nodes=(),
                    vms=(
                        VmInventory(
                            vmid=301,
                            name="partial-app",
                            node_id="node-a",
                            status="running",
                            template=False,
                            cpu=2,
                            memory_mb=4096,
                            disk_gb=40,
                        ),
                    ),
                    templates=(),
                    availability=InventoryAvailability(
                        sources=(
                            InventorySourceAvailability(
                                source="vm_config",
                                expected_targets=1,
                                observed_targets=0,
                                failed_targets=("node-a:301",),
                            ),
                        )
                    ),
                )

        adapter = PartialLiveAdapter()
        query = WorkloadInventoryQuery(adapter)
        with patch.object(v1_router.inventory_context, "inventory_query", return_value=query):
            read_response = self._run(v1_router.list_vms())
            with self.assertRaises(HTTPException) as raised:
                v1_router.inventory_context.mutation_inventory_adapter()

        self.assertTrue(read_response["ok"])
        self.assertEqual([301], [vm["vmid"] for vm in read_response["data"]])
        self.assertEqual("partial", read_response["meta"]["freshness"])
        self.assertFalse(read_response["meta"]["availability"]["complete"])
        self.assertEqual(503, raised.exception.status_code)
        self.assertEqual("PROXMOX_INVENTORY_DEGRADED", raised.exception.detail["code"])
        self.assertEqual([], raised.exception.detail["side_effects"])
        self.assertFalse(raised.exception.detail["proxmox_mutation_enabled"])


if __name__ == "__main__":
    unittest.main()
