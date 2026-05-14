"""Tests for explicit Proxmox mutation client API wrappers."""

import unittest


class ProxmoxMutationClientTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
