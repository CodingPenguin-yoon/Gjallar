import time
import unittest

from app.domains.proxmox.risk import build_operational_risk_dashboard
from app.domains.proxmox.service import ProxmoxService


class OperationalRiskDashboardTest(unittest.TestCase):
    def test_builds_read_only_operational_risk_summary(self):
        now = 1_700_000_000
        vms = [
            {
                "node": "node-a",
                "vmid": 101,
                "name": "app-01",
                "status": "running",
                "tags": [],
                "description": "",
                "configured_ipv4_addresses": ["192.0.2.10"],
                "guest_agent_ipv4_addresses": [],
            },
            {
                "node": "node-a",
                "vmid": 102,
                "name": "db-01",
                "status": "running",
                "tags": ["owner:yoon"],
                "guest_agent_ipv4_addresses": ["192.0.2.11"],
            },
        ]
        nodes = [
            {
                "node": "node-a",
                "status": "online",
                "storages": [
                    {"name": "vm-storage", "usage_percent": 92.5, "available_gb": 80, "total_gb": 1000}
                ],
            }
        ]
        snapshots = {
            "node-a/101": [
                {"name": "current"},
                {"name": "before-upgrade", "snaptime": now - 31 * 86400},
            ],
            "node-a/102": [],
        }
        backups = {
            "node-a/101": [],
            "node-a/102": [{"type": "vzdump", "status": "OK", "endtime": now - 2 * 86400}],
        }

        dashboard = build_operational_risk_dashboard(
            vms,
            nodes,
            snapshots_by_vm=snapshots,
            backup_tasks_by_vm=backups,
            now=now,
        )

        self.assertEqual(dashboard["status"], "critical")
        self.assertEqual(dashboard["summary"]["critical"], 2)
        self.assertEqual(dashboard["summary"]["warning"], 2)
        self.assertEqual(dashboard["summary"]["info"], 1)
        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertIn("storage:node-a:vm-storage:capacity", risk_ids)
        self.assertIn("vm:node-a/101:guest-agent", risk_ids)
        self.assertIn("vm:node-a/101:owner-tag", risk_ids)
        self.assertIn("vm:node-a/101:snapshot:before-upgrade", risk_ids)
        self.assertIn("vm:node-a/101:backup-recency", risk_ids)
        self.assertNotIn("vm:node-a/102:backup-recency", risk_ids)

    def test_backup_risk_is_skipped_when_backup_evidence_not_collected(self):
        dashboard = build_operational_risk_dashboard(
            [{"node": "node-a", "vmid": 101, "name": "vm-101", "status": "stopped", "tags": ["owner:yoon"]}],
            [],
            now=time.time(),
        )
        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertNotIn("vm:node-a/101:backup-recency", risk_ids)

    def test_service_risk_dashboard_uses_read_only_evidence_helpers(self):
        service = ProxmoxService()
        service.get_all_nodes_monitoring = lambda: [
            {"node": "node-a", "status": "online", "storages": []}
        ]
        service.get_vms = lambda: [
            {
                "node": "node-a",
                "vmid": 101,
                "name": "vm-101",
                "status": "running",
                "tags": ["owner:yoon"],
                "guest_agent_ipv4_addresses": ["192.0.2.101"],
            }
        ]
        service.get_vm_snapshots = lambda node, vmid: []
        service.get_node_tasks = lambda node, limit=200, vmid=None: [
            {"type": "vzdump", "status": "OK", "endtime": time.time()}
        ]

        def forbidden_mutation(*args, **kwargs):
            raise AssertionError("risk dashboard must not call mutation helpers")

        for name in [
            "shutdown_vm",
            "stop_vm",
            "start_vm",
            "reboot_vm",
            "delete_vm",
            "terminate_vm",
            "perform_vm_action",
            "update_vm_resources",
            "_make_write_request",
        ]:
            setattr(service, name, forbidden_mutation)

        dashboard = service.get_operational_risk_dashboard()

        self.assertEqual(dashboard["summary"]["total_vms"], 1)
        self.assertEqual(dashboard["summary"]["total_nodes"], 1)


if __name__ == "__main__":
    unittest.main()
