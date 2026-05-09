
import time
import unittest

from app.domains.proxmox.service import ProxmoxService


class ProxmoxServicePerformanceTest(unittest.TestCase):
    def test_get_vms_fetches_per_vm_details_concurrently(self):
        service = ProxmoxService()
        service.api_url = "https://proxmox.example/api2/json"

        vmids = [101, 102, 103, 104]

        def fake_make_request(endpoint, method="GET", params=None):
            if endpoint == "/nodes":
                return {"data": [{"node": "node-a"}]}
            if endpoint == "/nodes/node-a/qemu":
                return {
                    "data": [
                        {"vmid": vmid, "name": f"vm-{vmid}", "status": "running", "cpus": 2, "maxmem": 4 * 1024**3}
                        for vmid in vmids
                    ]
                }
            if endpoint.endswith("/config"):
                time.sleep(0.15)
                return {"data": {"scsi0": "local:vm-disk,size=10G"}}
            raise AssertionError(f"unexpected endpoint: {endpoint}")

        def fake_guest_ips(node, vmid):
            time.sleep(0.15)
            return [f"192.0.2.{vmid % 100}"]

        service._make_request = fake_make_request
        service.get_vm_ip_addresses = fake_guest_ips

        started = time.perf_counter()
        vms = service.get_vms()
        elapsed = time.perf_counter() - started

        self.assertEqual([vm["vmid"] for vm in vms], vmids)
        # Sequential behavior takes roughly 4 * (0.15 config + 0.15 guest-agent) = 1.2s.
        # Optimized behavior should finish near one VM latency plus overhead.
        self.assertLess(elapsed, 0.75, f"get_vms was still effectively sequential: {elapsed:.3f}s")


class ProxmoxServiceCacheTest(unittest.TestCase):
    def test_get_vms_reuses_fresh_inventory_cache_for_repeated_dashboard_calls(self):
        service = ProxmoxService()
        service.api_url = "https://proxmox.example/api2/json"
        service.vm_inventory_cache_ttl_seconds = 30.0

        detail_calls = {"count": 0}

        def fake_make_request(endpoint, method="GET", params=None):
            if endpoint == "/nodes":
                return {"data": [{"node": "node-a"}]}
            if endpoint == "/nodes/node-a/qemu":
                return {"data": [{"vmid": 101, "name": "vm-101", "status": "running", "cpus": 2, "maxmem": 4 * 1024**3}]}
            if endpoint.endswith("/config"):
                detail_calls["count"] += 1
                time.sleep(0.2)
                return {"data": {"scsi0": "local:vm-disk,size=10G"}}
            raise AssertionError(f"unexpected endpoint: {endpoint}")

        def fake_guest_ips(node, vmid):
            detail_calls["count"] += 1
            time.sleep(0.2)
            return ["192.0.2.101"]

        service._make_request = fake_make_request
        service.get_vm_ip_addresses = fake_guest_ips

        first = service.get_vms()
        started = time.perf_counter()
        second = service.get_vms()
        cached_elapsed = time.perf_counter() - started

        self.assertEqual(first, second)
        self.assertEqual(detail_calls["count"], 2)
        self.assertLess(cached_elapsed, 0.05, f"fresh repeated get_vms call did not use cache: {cached_elapsed:.3f}s")


if __name__ == "__main__":
    unittest.main()
