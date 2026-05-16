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
