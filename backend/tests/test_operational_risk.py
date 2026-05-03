import time
import unittest

from app.domains.proxmox.risk import build_operational_risk_dashboard
from app.domains.proxmox.service import ProxmoxService, VMInventorySnapshot


class OperationalRiskDashboardTest(unittest.TestCase):
    def _set_cluster_snapshot(self, service, vms, *, complete=True):
        service._get_all_vms_inventory_snapshot = lambda: VMInventorySnapshot(
            items=vms,
            complete=complete,
            scope="cluster",
        )

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

    def test_backup_schedule_coverage_replaces_recency_warning_for_uncovered_vm(self):
        now = 1_700_000_000

        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 101,
                    "name": "app-01",
                    "status": "running",
                    "tags": ["owner:yoon"],
                    "guest_agent_ipv4_addresses": ["192.0.2.10"],
                }
            ],
            [],
            backup_tasks_by_vm={"node-a/101": []},
            backup_not_backed_up_by_vmid={
                101: {"vmid": 101, "name": "app-01", "type": "qemu"},
            },
            backup_jobs=[],
            now=now,
        )

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertIn("vm:node-a/101:backup-coverage", risk_ids)
        self.assertNotIn("vm:node-a/101:backup-recency", risk_ids)
        coverage = next(item for item in dashboard["risk_items"] if item["id"] == "vm:node-a/101:backup-coverage")
        self.assertEqual(coverage["category"], "backup_coverage")
        self.assertEqual(coverage["evidence"]["source"], "/cluster/backup-info/not-backed-up")
        self.assertEqual(dashboard["evidence"]["backup_jobs_count"], 0)
        self.assertEqual(dashboard["evidence"]["backup_uncovered_vms"], 1)

    def test_service_risk_dashboard_uses_read_only_evidence_helpers(self):
        service = ProxmoxService()
        service.get_all_nodes_monitoring = lambda: [
            {"node": "node-a", "status": "online", "storages": []}
        ]
        self._set_cluster_snapshot(service, [
            {
                "node": "node-a",
                "vmid": 101,
                "name": "vm-101",
                "status": "running",
                "tags": ["owner:yoon"],
                "guest_agent_ipv4_addresses": ["192.0.2.101"],
            }
        ])
        service.get_vm_snapshots = lambda node, vmid: []
        service.get_node_tasks = lambda node, limit=200, vmid=None: [
            {"type": "vzdump", "status": "OK", "endtime": time.time()}
        ]
        service.get_backup_jobs = lambda: []
        service.get_vms_without_backup_jobs = lambda: []

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

    def test_service_collects_backup_schedule_evidence_read_only(self):
        service = ProxmoxService()
        calls = []
        service.get_all_nodes_monitoring = lambda: []
        self._set_cluster_snapshot(service, [
            {
                "node": "node-a",
                "vmid": 101,
                "name": "app-01",
                "status": "running",
                "tags": ["owner:yoon"],
                "guest_agent_ipv4_addresses": ["192.0.2.10"],
            }
        ])
        service.get_vm_snapshots = lambda node, vmid: []
        service.get_node_tasks = lambda node, limit=200, vmid=None: []

        def fake_make_request(endpoint, method="GET", params=None):
            calls.append((endpoint, method))
            if endpoint == "/cluster/backup":
                return {"data": []}
            if endpoint == "/cluster/backup-info/not-backed-up":
                return {"data": [{"vmid": 101, "name": "app-01", "type": "qemu"}]}
            return {"data": []}

        service._make_request = fake_make_request

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

        self.assertIn(("/cluster/backup", "GET"), calls)
        self.assertIn(("/cluster/backup-info/not-backed-up", "GET"), calls)
        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertIn("vm:node-a/101:backup-coverage", risk_ids)
        self.assertEqual(dashboard["evidence"]["backup_schedule_collected"], True)

    def test_service_marks_backup_schedule_uncollected_when_evidence_requests_fail(self):
        service = ProxmoxService()
        service.get_all_nodes_monitoring = lambda: []
        self._set_cluster_snapshot(service, [
            {
                "node": "node-a",
                "vmid": 101,
                "name": "app-01",
                "status": "running",
                "tags": ["owner:yoon"],
                "guest_agent_ipv4_addresses": ["192.0.2.10"],
            }
        ])
        service.get_vm_snapshots = lambda node, vmid: []
        service.get_node_tasks = lambda node, limit=200, vmid=None: []
        service._make_request = lambda endpoint, method="GET", params=None: {
            "data": [],
            "error": "permission denied" if endpoint.startswith("/cluster/backup") else None,
        }

        dashboard = service.get_operational_risk_dashboard()

        self.assertEqual(dashboard["evidence"]["backup_schedule_collected"], False)
        self.assertIsNone(dashboard["evidence"]["backup_uncovered_vms"])
        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertNotIn("vm:node-a/101:backup-coverage", risk_ids)
        self.assertIn("vm:node-a/101:backup-recency", risk_ids)

    def test_service_marks_backup_schedule_uncollected_when_api_url_is_missing(self):
        service = ProxmoxService()
        service.api_url = ""
        service.get_all_nodes_monitoring = lambda: []
        self._set_cluster_snapshot(service, [
            {
                "node": "node-a",
                "vmid": 101,
                "name": "app-01",
                "status": "running",
                "tags": ["owner:yoon"],
                "guest_agent_ipv4_addresses": ["192.0.2.10"],
            }
        ])
        service.get_vm_snapshots = lambda node, vmid: []
        service.get_node_tasks = lambda node, limit=200, vmid=None: []

        dashboard = service.get_operational_risk_dashboard()

        self.assertEqual(dashboard["evidence"]["backup_schedule_collected"], False)
        self.assertIsNone(dashboard["evidence"]["backup_uncovered_vms"])
        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertNotIn("vm:node-a/101:backup-coverage", risk_ids)
        self.assertIn("vm:node-a/101:backup-recency", risk_ids)


    def test_long_stopped_vm_uses_persisted_state_history(self):
        now = 1_700_000_000
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 101,
                    "name": "old-stopped",
                    "status": "stopped",
                    "tags": ["owner:yoon"],
                }
            ],
            [],
            vm_state_history={
                "node-a/101": {
                    "status": "stopped",
                    "status_since": now - 31 * 86400,
                    "stopped_since": now - 31 * 86400,
                    "stopped_days": 31.0,
                    "source": "gjallar_db",
                }
            },
            now=now,
        )

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertIn("vm:node-a/101:long-stopped", risk_ids)
        long_stopped = next(item for item in dashboard["risk_items"] if item["id"] == "vm:node-a/101:long-stopped")
        self.assertEqual(long_stopped["category"], "long_stopped")
        self.assertEqual(long_stopped["severity"], "warning")
        self.assertEqual(long_stopped["evidence"]["stopped_days"], 31.0)
        self.assertEqual(dashboard["summary"]["categories"]["long_stopped"], 1)
        self.assertEqual(dashboard["evidence"]["vm_state_history_collected"], True)

    def test_recently_observed_stopped_vm_is_not_long_stopped_without_history(self):
        now = 1_700_000_000
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 101,
                    "name": "newly-stopped",
                    "status": "stopped",
                    "tags": ["owner:yoon"],
                }
            ],
            [],
            vm_state_history={
                "node-a/101": {
                    "status": "stopped",
                    "status_since": now,
                    "stopped_since": now,
                    "stopped_days": 0.0,
                    "source": "gjallar_db",
                }
            },
            now=now,
        )

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertNotIn("vm:node-a/101:long-stopped", risk_ids)
        self.assertEqual(dashboard["evidence"]["vm_state_history_collected"], True)


    def test_service_dashboard_uses_configured_thresholds(self):
        service = ProxmoxService()
        service.get_all_nodes_monitoring = lambda: [
            {
                "node": "node-a",
                "status": "online",
                "storages": [
                    {"name": "vm-storage", "usage_percent": 92.0, "available_gb": 80, "total_gb": 1000}
                ],
            }
        ]
        self._set_cluster_snapshot(service, [])
        service.get_vm_state_history = lambda vms, **kwargs: {}
        service.get_backup_jobs = lambda: []
        service.get_vms_without_backup_jobs = lambda: []
        service.get_operational_risk_thresholds = lambda: {
            "thresholds": {
                "storage_warning_percent": 95.0,
                "storage_critical_percent": 98.0,
                "snapshot_warning_days": 14.0,
                "snapshot_critical_days": 30.0,
                "backup_warning_days": 7.0,
                "stopped_warning_days": 30.0,
                "stopped_critical_days": 90.0,
            },
            "source": "database",
        }

        dashboard = service.get_operational_risk_dashboard()

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertNotIn("storage:node-a:vm-storage:capacity", risk_ids)
        self.assertEqual(dashboard["thresholds"]["storage_warning_percent"], 95.0)
        self.assertEqual(dashboard["threshold_config"]["source"], "database")
        self.assertEqual(dashboard["threshold_config"]["thresholds"]["storage_warning_percent"], 95.0)




if __name__ == "__main__":
    unittest.main()
