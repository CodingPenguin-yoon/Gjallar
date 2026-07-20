"""Tests for explicit Proxmox mutation client API wrappers."""

import unittest
from unittest.mock import patch


class ProxmoxMutationClientTests(unittest.TestCase):
    def test_start_vm_uses_qemu_status_start_endpoint_and_returns_upid(self):
        from app.proxmox.client import ProxmoxMutationClient

        calls = []

        def record_request(method, path, *, data=None, timeout=None):
            calls.append((method, path, data, timeout))
            return "UPID:node-a:0001:start"

        client = ProxmoxMutationClient(
            api_url="https://pve.example.test/api2/json",
            token_id="root@pam!gjallar",
            token_secret="secret",
            request=record_request,
        )

        result = client.start_vm(node="node-a", vmid=306)

        self.assertEqual("UPID:node-a:0001:start", result)
        self.assertEqual(
            [("POST", "/nodes/node-a/qemu/306/status/start", None, None)],
            calls,
        )

    def test_start_vm_requires_non_empty_upid(self):
        from app.proxmox.client import ProxmoxMutationClient, ProxmoxMutationError

        client = ProxmoxMutationClient(
            api_url="https://pve.example.test/api2/json",
            token_id="root@pam!gjallar",
            token_secret="secret",
            request=lambda *args, **kwargs: "",
        )

        with self.assertRaises(ProxmoxMutationError):
            client.start_vm(node="node-a", vmid=306)

    def test_list_active_vm_tasks_uses_node_task_filter(self):
        from app.proxmox.client import ProxmoxMutationClient

        calls = []

        def record_request(method, path, *, data=None, timeout=None):
            calls.append((method, path, data, timeout))
            return [{"upid": "UPID:node-a:0001:vzdump", "status": "RUNNING"}, "ignored"]

        client = ProxmoxMutationClient(
            api_url="https://pve.example.test/api2/json",
            token_id="root@pam!gjallar",
            token_secret="secret",
            request=record_request,
        )

        result = client.list_active_vm_tasks(node="node-a", vmid=306)

        self.assertEqual([{"upid": "UPID:node-a:0001:vzdump", "status": "RUNNING"}], result)
        self.assertEqual(
            [("GET", "/nodes/node-a/tasks?source=active&vmid=306", None, None)],
            calls,
        )

    def test_node_task_audit_requires_sys_audit_in_effective_permissions(self):
        from app.proxmox.client import ProxmoxMutationClient

        responses = [
            {"/nodes/node-a": {"Sys.Audit": 0, "VM.Audit": 1}},
            {"/nodes/node-a": {"VM.Audit": 1}},
        ]
        calls = []

        def record_request(method, path, *, data=None, timeout=None):
            calls.append((method, path, data, timeout))
            return responses.pop(0)

        client = ProxmoxMutationClient(
            api_url="https://pve.example.test/api2/json",
            token_id="root@pam!gjallar",
            token_secret="secret",
            request=record_request,
        )

        self.assertTrue(client.has_node_task_audit(node="node-a"))
        self.assertFalse(client.has_node_task_audit(node="node-a"))
        self.assertEqual(
            [
                ("GET", "/access/permissions?path=/nodes/node-a", None, None),
                ("GET", "/access/permissions?path=/nodes/node-a", None, None),
            ],
            calls,
        )

    def test_resize_vm_disk_uses_qemu_resize_endpoint_payload(self):
        from app.proxmox.client import ProxmoxMutationClient

        calls = []

        def record_request(method, path, *, data=None, timeout=None):
            calls.append((method, path, data, timeout))
            return None

        client = ProxmoxMutationClient(
            api_url="https://pve.example.test/api2/json",
            token_id="root@pam!gjallar",
            token_secret="secret",
            request=record_request,
        )

        result = client.resize_vm_disk(node="node-a", vmid=306, disk="scsi0", size=80)

        self.assertIsNone(result)
        self.assertEqual(
            [("PUT", "/nodes/node-a/qemu/306/resize", {"disk": "scsi0", "size": "80G"}, None)],
            calls,
        )

    def test_guest_agent_network_uses_qemu_agent_endpoint(self):
        from app.proxmox.client import ProxmoxMutationClient

        calls = []

        def record_request(method, path, *, data=None, timeout=None):
            calls.append((method, path, data, timeout))
            return {"result": [{"name": "ens18", "ip-addresses": []}]}

        client = ProxmoxMutationClient(
            api_url="https://pve.example.test/api2/json",
            token_id="root@pam!gjallar",
            token_secret="secret",
            request=record_request,
        )

        result = client.get_guest_network_interfaces(node="node-a", vmid=306)

        self.assertEqual({"result": [{"name": "ens18", "ip-addresses": []}]}, result)
        self.assertEqual(
            [("GET", "/nodes/node-a/qemu/306/agent/network-get-interfaces", None, None)],
            calls,
        )

    def test_guest_exec_runs_command_and_polls_status(self):
        from app.proxmox.client import ProxmoxMutationClient

        calls = []

        def record_request(method, path, *, data=None, timeout=None):
            calls.append((method, path, data, timeout))
            if path.endswith("/agent/exec"):
                return {"pid": 77}
            return {"exited": True, "exitcode": 0, "out-data": "status: done\n"}

        client = ProxmoxMutationClient(
            api_url="https://pve.example.test/api2/json",
            token_id="root@pam!gjallar",
            token_secret="secret",
            request=record_request,
        )

        pid = client.exec_guest_command(node="node-a", vmid=306, command=("cloud-init", "status", "--wait"))
        result = client.wait_guest_exec(node="node-a", vmid=306, pid=pid)

        self.assertEqual(77, pid)
        self.assertEqual(0, result["exitcode"])
        self.assertEqual(
            [
                (
                    "POST",
                    "/nodes/node-a/qemu/306/agent/exec",
                    [("command", "cloud-init"), ("command", "status"), ("command", "--wait")],
                    None,
                ),
                ("GET", "/nodes/node-a/qemu/306/agent/exec-status?pid=77", None, None),
            ],
            calls,
        )

    def test_http_error_details_include_proxmox_response_body(self):
        import requests

        from app.proxmox.client import ProxmoxMutationClient, ProxmoxMutationError

        response = requests.Response()
        response.status_code = 400
        response.reason = "Bad Request"
        response.url = "https://pve.example.test/api2/json/nodes/node-a/qemu/306/config"
        response._content = b'{"data":null,"errors":{"sshkeys":"invalid urlencoded string"},"message":"Parameter verification failed.\\n"}'

        client = ProxmoxMutationClient(
            api_url="https://pve.example.test/api2/json",
            token_id="root@pam!gjallar",
            token_secret="secret",
        )

        with patch("app.proxmox.client.requests.request", return_value=response):
            with self.assertRaises(ProxmoxMutationError) as raised:
                client.set_vm_config(node="node-a", vmid=306, config={"sshkeys": "ssh-ed25519 AAAA"})

        details = raised.exception.details
        self.assertEqual(400, details["status_code"])
        self.assertEqual("PUT", details["method"])
        self.assertEqual("/nodes/node-a/qemu/306/config", details["path"])
        self.assertEqual("invalid urlencoded string", details["response_json"]["errors"]["sshkeys"])


class DrsProxmoxMigrationClientTests(unittest.TestCase):
    def test_migrate_vm_uses_dedicated_qemu_migrate_endpoint_payload(self):
        from app.proxmox.drs_migration import DrsProxmoxMigrationClient

        calls = []

        def record_request(method, path, *, data=None, timeout=None):
            calls.append((method, path, data, timeout))
            return "UPID:node-a:0001:migrate"

        client = DrsProxmoxMigrationClient(
            api_url="https://pve.example.test/api2/json",
            token_id="root@pam!drs",
            token_secret="secret",
            request=record_request,
        )

        result = client.migrate_vm(source_node="node-a", target_node="node-b", vmid=101)

        self.assertEqual("UPID:node-a:0001:migrate", result)
        self.assertEqual(
            [("POST", "/nodes/node-a/qemu/101/migrate", {"target": "node-b", "online": 1}, None)],
            calls,
        )

    def test_migrate_vm_requires_non_empty_upid(self):
        from app.proxmox.drs_migration import DrsProxmoxMigrationClient, DrsProxmoxMigrationError

        client = DrsProxmoxMigrationClient(
            api_url="https://pve.example.test/api2/json",
            token_id="root@pam!drs",
            token_secret="secret",
            request=lambda *args, **kwargs: "",
        )

        with self.assertRaises(DrsProxmoxMigrationError):
            client.migrate_vm(source_node="node-a", target_node="node-b", vmid=101)

    def test_collect_live_precheck_reads_active_tasks_quorum_ha_and_migration_preconditions(self):
        from app.proxmox.drs_migration import DrsProxmoxMigrationClient

        calls = []

        def record_request(method, path, *, data=None, timeout=None):
            calls.append((method, path, data, timeout))
            if path == "/nodes/node-a/tasks?source=active&vmid=101":
                return []
            if path == "/cluster/status":
                return [{"type": "cluster", "name": "cluster-a", "quorate": 1}]
            if path == "/cluster/ha/resources?type=vm":
                return [{"sid": "vm:101", "state": "started", "group": "ha"}]
            if path == "/nodes/node-a/qemu/101/migrate?target=node-b":
                return {
                    "running": True,
                    "allowed_nodes": ["node-b"],
                    "not_allowed_nodes": {},
                    "local_disks": [],
                    "local_resources": [],
                    "dependent-ha-resources": [],
                }
            self.fail(f"unexpected call: {method} {path}")

        client = DrsProxmoxMigrationClient(
            api_url="https://pve.example.test/api2/json",
            token_id="root@pam!drs",
            token_secret="secret",
            request=record_request,
        )

        result = client.collect_live_precheck(source_node="node-a", target_node="node-b", vmid=101)

        self.assertEqual("pass", result["status"])
        self.assertEqual([], result["blockers"])
        self.assertEqual("pass", result["checks"]["proxmox_active_task"]["status"])
        self.assertEqual("pass", result["checks"]["proxmox_cluster_quorum"]["status"])
        self.assertEqual("pass", result["checks"]["proxmox_ha_state"]["status"])
        self.assertEqual("pass", result["checks"]["proxmox_migration_preconditions"]["status"])
        self.assertEqual(
            [
                ("GET", "/nodes/node-a/tasks?source=active&vmid=101", None, None),
                ("GET", "/cluster/status", None, None),
                ("GET", "/cluster/ha/resources?type=vm", None, None),
                ("GET", "/nodes/node-a/qemu/101/migrate?target=node-b", None, None),
            ],
            calls,
        )

    def test_collect_live_precheck_does_not_block_empty_not_allowed_node_details(self):
        from app.proxmox.drs_migration import DrsProxmoxMigrationClient

        empty_values = ({}, [], None, "")
        for empty_value in empty_values:
            with self.subTest(empty_value=empty_value):
                def record_request(method, path, *, data=None, timeout=None):
                    if path == "/nodes/node-a/tasks?source=active&vmid=140":
                        return []
                    if path == "/cluster/status":
                        return [{"type": "cluster", "name": "cluster-a", "quorate": 1}]
                    if path == "/cluster/ha/resources?type=vm":
                        return []
                    if path == "/nodes/node-a/qemu/140/migrate?target=node-b":
                        return {
                            "running": 1,
                            "allowed_nodes": ["node-b", "node-c"],
                            "not_allowed_nodes": {"node-b": empty_value, "node-c": {}},
                            "local_disks": [],
                            "local_resources": [],
                            "dependent-ha-resources": [],
                        }
                    self.fail(f"unexpected call: {method} {path}")

                client = DrsProxmoxMigrationClient(
                    api_url="https://pve.example.test/api2/json",
                    token_id="root@pam!drs",
                    token_secret="secret",
                    request=record_request,
                )

                result = client.collect_live_precheck(source_node="node-a", target_node="node-b", vmid=140)

                migration_check = result["checks"]["proxmox_migration_preconditions"]
                evidence = migration_check["evidence"]
                self.assertEqual("pass", result["status"])
                self.assertEqual([], result["blockers"])
                self.assertEqual("pass", migration_check["status"])
                self.assertEqual(["node-b", "node-c"], evidence["not_allowed_nodes"])
                self.assertEqual([], evidence["not_allowed_nodes_with_blocking_details"])
                self.assertEqual({}, evidence["not_allowed_node_blocking_details"])
                self.assertEqual("object", evidence["not_allowed_nodes_shape"])

    def test_collect_live_precheck_blocks_non_empty_not_allowed_node_details(self):
        from app.proxmox.drs_migration import DrsProxmoxMigrationClient

        def record_request(method, path, *, data=None, timeout=None):
            if path == "/nodes/node-a/tasks?source=active&vmid=140":
                return []
            if path == "/cluster/status":
                return [{"type": "cluster", "name": "cluster-a", "quorate": 1}]
            if path == "/cluster/ha/resources?type=vm":
                return []
            if path == "/nodes/node-a/qemu/140/migrate?target=node-b":
                return {
                    "running": 1,
                    "allowed_nodes": ["node-b"],
                    "not_allowed_nodes": {"node-b": {"reason": "storage mismatch"}},
                    "local_disks": [],
                    "local_resources": [],
                }
            self.fail(f"unexpected call: {method} {path}")

        client = DrsProxmoxMigrationClient(
            api_url="https://pve.example.test/api2/json",
            token_id="root@pam!drs",
            token_secret="secret",
            request=record_request,
        )

        result = client.collect_live_precheck(source_node="node-a", target_node="node-b", vmid=140)

        migration_check = result["checks"]["proxmox_migration_preconditions"]
        evidence = migration_check["evidence"]
        self.assertEqual("blocked", result["status"])
        self.assertIn("proxmox_target_not_allowed", result["blockers"])
        self.assertEqual("failed", migration_check["status"])
        self.assertEqual(["node-b"], evidence["not_allowed_nodes"])
        self.assertEqual(["node-b"], evidence["not_allowed_nodes_with_blocking_details"])
        self.assertEqual({"node-b": {"reason": "storage mismatch"}}, evidence["not_allowed_node_blocking_details"])

    def test_collect_live_precheck_preserves_list_style_not_allowed_nodes_as_blocking(self):
        from app.proxmox.drs_migration import DrsProxmoxMigrationClient

        def record_request(method, path, *, data=None, timeout=None):
            if path == "/nodes/node-a/tasks?source=active&vmid=140":
                return []
            if path == "/cluster/status":
                return [{"type": "cluster", "name": "cluster-a", "quorate": 1}]
            if path == "/cluster/ha/resources?type=vm":
                return []
            if path == "/nodes/node-a/qemu/140/migrate?target=node-b":
                return {
                    "running": 1,
                    "allowed_nodes": ["node-b"],
                    "not_allowed_nodes": ["node-b"],
                    "local_disks": [],
                    "local_resources": [],
                }
            self.fail(f"unexpected call: {method} {path}")

        client = DrsProxmoxMigrationClient(
            api_url="https://pve.example.test/api2/json",
            token_id="root@pam!drs",
            token_secret="secret",
            request=record_request,
        )

        result = client.collect_live_precheck(source_node="node-a", target_node="node-b", vmid=140)

        evidence = result["checks"]["proxmox_migration_preconditions"]["evidence"]
        self.assertEqual("blocked", result["status"])
        self.assertIn("proxmox_target_not_allowed", result["blockers"])
        self.assertEqual(["node-b"], evidence["not_allowed_nodes"])
        self.assertEqual(["node-b"], evidence["not_allowed_nodes_with_blocking_details"])
        self.assertEqual("list", evidence["not_allowed_nodes_shape"])

    def test_collect_live_precheck_blocks_active_task_before_migration(self):
        from app.proxmox.drs_migration import DrsProxmoxMigrationClient

        def record_request(method, path, *, data=None, timeout=None):
            if path == "/nodes/node-a/tasks?source=active&vmid=101":
                return [{"upid": "UPID:node-a:busy", "type": "qmigrate", "status": "running"}]
            if path == "/cluster/status":
                return [{"type": "cluster", "name": "cluster-a", "quorate": 1}]
            if path == "/cluster/ha/resources?type=vm":
                return []
            if path == "/nodes/node-a/qemu/101/migrate?target=node-b":
                return {"running": True, "allowed_nodes": ["node-b"], "not_allowed_nodes": {}}
            self.fail(f"unexpected call: {method} {path}")

        client = DrsProxmoxMigrationClient(
            api_url="https://pve.example.test/api2/json",
            token_id="root@pam!drs",
            token_secret="secret",
            request=record_request,
        )

        result = client.collect_live_precheck(source_node="node-a", target_node="node-b", vmid=101)

        self.assertEqual("blocked", result["status"])
        self.assertIn("proxmox_active_task_conflict", result["blockers"])


if __name__ == "__main__":
    unittest.main()
