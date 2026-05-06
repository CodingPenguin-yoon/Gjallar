import unittest

from app.domains.proxmox.risk import build_operational_risk_dashboard
from app.domains.proxmox.service import ProxmoxService, VMInventorySnapshot
from app.domains.proxmox.ssh_collector import (
    ReadOnlySSHCollector,
    SSHCollectorConfig,
)


class OptionalReadOnlySSHCollectorTest(unittest.TestCase):
    def _vm(self):
        return {
            "node": "node-a",
            "vmid": 101,
            "name": "guest-a",
            "status": "running",
            "tags": ["owner:yoon", "env:lab"],
            "guest_agent_ipv4_addresses": ["192.0.2.10"],
        }

    def test_disabled_collector_returns_uncollected_without_running_executor(self):
        def executor(*_args, **_kwargs):
            raise AssertionError("disabled SSH collector must not run commands")

        collector = ReadOnlySSHCollector(
            SSHCollectorConfig(enabled=False),
            executor=executor,
        )

        self.assertIsNone(collector.collect_for_vms([self._vm()], now_epoch=1_700_000_000))

    def test_enabled_but_unconfigured_collector_returns_uncollected_without_executor(self):
        def executor(*_args, **_kwargs):
            raise AssertionError("unconfigured SSH collector must not run commands")

        collector = ReadOnlySSHCollector(
            SSHCollectorConfig(enabled=True, targets={}),
            executor=executor,
        )

        self.assertIsNone(collector.collect_for_vms([self._vm()], now_epoch=1_700_000_000))

    def test_non_allowlisted_command_is_blocked_and_never_executed(self):
        calls = []

        def executor(argv, *, timeout_seconds):
            calls.append((argv, timeout_seconds))
            return {"returncode": 0, "stdout": "unexpected", "stderr": ""}

        collector = ReadOnlySSHCollector(
            SSHCollectorConfig(
                enabled=True,
                targets={"node-a/101": {"host": "guest-a.invalid", "user": "ops"}},
                command_ids=["restart_service"],
            ),
            executor=executor,
        )

        evidence = collector.collect_for_vms([self._vm()], now_epoch=1_700_000_000)

        self.assertEqual(calls, [])
        record = evidence["node-a/101"]
        self.assertFalse(record["collected"])
        self.assertEqual(record["status"], "blocked")
        self.assertEqual(record["reason"], "command_not_allowlisted")
        self.assertIn("restart_service", record["blocked_commands"])

    def test_invalid_ssh_target_is_blocked_and_never_executed(self):
        calls = []

        def executor(argv, *, timeout_seconds):
            calls.append((argv, timeout_seconds))
            return {"returncode": 0, "stdout": "unexpected", "stderr": ""}

        collector = ReadOnlySSHCollector(
            SSHCollectorConfig(
                enabled=True,
                targets={"node-a/101": {"host": "-oProxyCommand=blocked", "user": "ops"}},
                command_ids=["os_release"],
            ),
            executor=executor,
        )

        evidence = collector.collect_for_vms([self._vm()], now_epoch=1_700_000_000)

        self.assertEqual(calls, [])
        record = evidence["node-a/101"]
        self.assertFalse(record["collected"])
        self.assertEqual(record["status"], "blocked")
        self.assertEqual(record["reason"], "invalid_target")
        self.assertIn("[REDACTED]", record["error"])
        self.assertNotIn("ProxyCommand", record["error"])

    def test_invalid_ssh_port_is_blocked_and_never_executed(self):
        calls = []

        def executor(argv, *, timeout_seconds):
            calls.append((argv, timeout_seconds))
            return {"returncode": 0, "stdout": "unexpected", "stderr": ""}

        collector = ReadOnlySSHCollector(
            SSHCollectorConfig(
                enabled=True,
                targets={"node-a/101": {"host": "guest-a.invalid", "port": "not-a-number"}},
                command_ids=["os_release"],
            ),
            executor=executor,
        )

        evidence = collector.collect_for_vms([self._vm()], now_epoch=1_700_000_000)

        self.assertEqual(calls, [])
        record = evidence["node-a/101"]
        self.assertFalse(record["collected"])
        self.assertEqual(record["status"], "blocked")
        self.assertEqual(record["reason"], "invalid_target")

    def test_sensitive_ssh_target_fields_are_blocked_and_redacted(self):
        calls = []
        raw_login_phrase = "ssh-test-login-phrase-never-log"
        raw_private_key = "BEGIN-SSH-PRIVATE-KEY-NEVER-LOG"
        raw_private_key_data = "raw-private-key-data-never-log"
        raw_key_path = "/tmp/gjallar-readonly-key"

        def executor(argv, *, timeout_seconds):
            calls.append((argv, timeout_seconds))
            return {"returncode": 0, "stdout": "unexpected", "stderr": ""}

        collector = ReadOnlySSHCollector(
            SSHCollectorConfig(
                enabled=True,
                targets={
                    "node-a/101": {
                        "host": "guest-a.invalid",
                        "user": "ops",
                        "key_path": raw_key_path,
                        "password": raw_login_phrase,
                        "private_key": raw_private_key,
                        "private_key_data": raw_private_key_data,
                    }
                },
                command_ids=["os_release"],
            ),
            executor=executor,
        )

        evidence = collector.collect_for_vms([self._vm()], now_epoch=1_700_000_000)

        self.assertEqual(calls, [])
        record = evidence["node-a/101"]
        self.assertFalse(record["collected"])
        self.assertEqual(record["status"], "blocked")
        self.assertEqual(record["reason"], "invalid_target")
        self.assertIn("[REDACTED]", record["error"])
        for raw_value in [raw_login_phrase, raw_private_key, raw_private_key_data, raw_key_path, "guest-a.invalid"]:
            self.assertNotIn(raw_value, record["error"])

    def test_ssh_execution_failure_is_redacted_and_recorded_as_uncollected(self):
        raw_host = "guest-a.invalid"
        raw_key_path = "/tmp/gjallar-readonly-key"
        raw_marker = "raw-redaction-marker"

        def executor(argv, *, timeout_seconds):
            raise RuntimeError(
                f"ssh to {raw_host} failed with marker {raw_marker} and key {raw_key_path}"
            )

        collector = ReadOnlySSHCollector(
            SSHCollectorConfig(
                enabled=True,
                targets={"node-a/101": {"host": raw_host, "user": "ops", "key_path": raw_key_path}},
                command_ids=["os_release"],
                extra_redactions=[raw_marker],
            ),
            executor=executor,
        )

        evidence = collector.collect_for_vms([self._vm()], now_epoch=1_700_000_000)
        record = evidence["node-a/101"]

        self.assertFalse(record["collected"])
        self.assertEqual(record["status"], "failed")
        self.assertIn("[REDACTED]", record["error"])
        self.assertNotIn(raw_host, record["error"])
        self.assertNotIn(raw_key_path, record["error"])
        self.assertNotIn(raw_marker, record["error"])


class OptionalReadOnlySSHRiskIntegrationTest(unittest.TestCase):
    def _vm(self):
        return {
            "node": "node-a",
            "vmid": 101,
            "name": "guest-a",
            "status": "running",
            "tags": ["owner:yoon", "env:lab"],
            "guest_agent_ipv4_addresses": ["192.0.2.10"],
        }

    def test_dashboard_marks_optional_ssh_evidence_uncollected_by_default(self):
        dashboard = build_operational_risk_dashboard(
            [self._vm()],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/101": []},
            backup_tasks_by_vm={"node-a/101": []},
            now=1_700_000_000,
        )

        self.assertFalse(dashboard["evidence"]["ssh_guest_collected"])
        self.assertIsNone(dashboard["evidence"]["ssh_guest_vms"])
        self.assertIsNone(dashboard["evidence"]["ssh_guest_failed_vms"])

    def test_failed_configured_ssh_evidence_is_visible_as_non_healthy_risk(self):
        dashboard = build_operational_risk_dashboard(
            [self._vm()],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/101": []},
            backup_tasks_by_vm={"node-a/101": []},
            ssh_guest_evidence_by_vm={
                "node-a/101": {
                    "source": "optional_readonly_ssh",
                    "node": "node-a",
                    "vmid": 101,
                    "collected": False,
                    "status": "failed",
                    "reason": "ssh_execution_failed",
                    "error": "[REDACTED]",
                    "command_ids": ["os_release"],
                }
            },
            now=1_700_000_000,
        )

        risk = next(
            item for item in dashboard["risk_items"]
            if item["id"] == "vm:node-a/101:ssh-guest-evidence"
        )
        self.assertEqual(risk["severity"], "info")
        self.assertEqual(risk["category"], "guest_ssh_evidence")
        self.assertEqual(risk["evidence"]["error"], "[REDACTED]")
        self.assertEqual(dashboard["evidence"]["ssh_guest_collected"], True)
        self.assertEqual(dashboard["evidence"]["ssh_guest_vms"], 1)
        self.assertEqual(dashboard["evidence"]["ssh_guest_failed_vms"], 1)


class OptionalReadOnlySSHServiceIntegrationTest(unittest.TestCase):
    def test_service_dashboard_exposes_uncollected_ssh_evidence_when_disabled(self):
        service = ProxmoxService()
        vms = [
            {
                "node": "node-a",
                "vmid": 101,
                "name": "guest-a",
                "status": "running",
                "tags": ["owner:yoon", "env:lab"],
                "guest_agent_ipv4_addresses": ["192.0.2.10"],
            }
        ]
        service.get_all_nodes_monitoring = lambda: [{"node": "node-a", "status": "online", "storages": []}]
        service._get_all_vms_inventory_snapshot = lambda: VMInventorySnapshot(
            items=vms,
            complete=True,
            scope="cluster",
        )
        service.get_vm_state_history = lambda *_args, **_kwargs: None
        service.get_operational_risk_thresholds = lambda: {"thresholds": {}, "source": "default"}
        service.get_backup_jobs = lambda: None
        service.get_vms_without_backup_jobs = lambda: None
        service.get_pbs_restore_readiness_evidence_by_vmid = lambda **_kwargs: None
        service.get_pbs_datastore_health_evidence_by_name = lambda **_kwargs: None
        service.get_restore_drill_evidence_by_vm = lambda *_args, **_kwargs: None
        service.get_vm_snapshots = lambda *_args, **_kwargs: []
        service.get_node_tasks = lambda *_args, **_kwargs: []
        service._get_active_risk_overrides = lambda **_kwargs: {}

        dashboard = service.get_operational_risk_dashboard()

        self.assertFalse(dashboard["evidence"]["ssh_guest_collected"])
        self.assertIsNone(dashboard["evidence"]["ssh_guest_vms"])
        self.assertIsNone(dashboard["evidence"]["ssh_guest_failed_vms"])


if __name__ == "__main__":
    unittest.main()
