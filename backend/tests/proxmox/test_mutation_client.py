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

    def test_shutdown_vm_uses_only_graceful_qemu_shutdown_endpoint(self):
        from app.proxmox.client import ProxmoxMutationClient

        calls = []

        def record_request(method, path, *, data=None, timeout=None):
            calls.append((method, path, data, timeout))
            return "UPID:node-a:0002:qmshutdown"

        client = ProxmoxMutationClient(
            api_url="https://pve.example.test/api2/json",
            token_id="root@pam!gjallar",
            token_secret="secret",
            request=record_request,
        )

        result = client.shutdown_vm(node="node-a", vmid=306)

        self.assertEqual("UPID:node-a:0002:qmshutdown", result)
        self.assertEqual(
            [("POST", "/nodes/node-a/qemu/306/status/shutdown", None, None)],
            calls,
        )

    def test_shutdown_vm_requires_non_empty_upid(self):
        from app.proxmox.client import ProxmoxMutationClient, ProxmoxMutationError

        client = ProxmoxMutationClient(
            api_url="https://pve.example.test/api2/json",
            token_id="root@pam!gjallar",
            token_secret="secret",
            request=lambda *args, **kwargs: "",
        )

        with self.assertRaises(ProxmoxMutationError):
            client.shutdown_vm(node="node-a", vmid=306)

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



if __name__ == "__main__":
    unittest.main()
