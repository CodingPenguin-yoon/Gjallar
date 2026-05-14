"""RED tests for Set 6 /api/v1 create-VM route surface."""

import contextlib
import io
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ApiV1VmCreateRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp_dir = tempfile.TemporaryDirectory()
        cls.shared_root = Path(cls._temp_dir.name) / "nfs"
        (cls.shared_root / "IaC" / ".git").mkdir(parents=True)
        (cls.shared_root / "IaC" / "manifests" / "vms").mkdir(parents=True)
        (cls.shared_root / "IaC" / "manifests" / "networks").mkdir(parents=True)
        (cls.shared_root / "IaC" / "generated").mkdir(parents=True)
        (cls.shared_root / "IaC-state" / "gjallar").mkdir(parents=True)
        (cls.shared_root / "IaC" / "manifests" / "networks" / "network-profiles.yaml").write_text(
            """apiVersion: gjallar/v1
kind: NetworkPolicySet
networks:
  - network_id: server-net
    display_name: Server network
    nodes:
      - node_id: yoonmanserver2
        bridge_id: vmbr0
        subnet: 192.168.2.0/24
        gateway: 192.168.2.1
        dns: [192.168.2.1]
        static_ip_ranges:
          - start: 192.168.2.142
            end: 192.168.2.150
""",
            encoding="utf-8",
        )
        cls._env = patch.dict(
            "os.environ",
            {
                "GJALLAR_SHARED_ROOT": str(cls.shared_root),
                "GJALLAR_RUNS_ROOT": str(Path(cls._temp_dir.name) / "runs"),
            },
            clear=False,
        )
        cls._env.start()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            from app.main import app
            from app.api.v1 import router as api_v1_router
        cls.paths = {getattr(route, "path", "") for route in app.routes}
        cls.api_v1_router = api_v1_router

    @classmethod
    def tearDownClass(cls):
        cls._env.stop()
        cls._temp_dir.cleanup()

    def test_create_draft_preflight_plan_routes_exist_under_api_v1(self):
        expected = {
            "/api/v1/vm-create/readiness",
            "/api/v1/vm-create/drafts",
            "/api/v1/vm-create/{draft_id}/preflight",
            "/api/v1/vm-create/{draft_id}/plan",
        }
        missing = sorted(expected - self.paths)
        self.assertEqual([], missing, f"Missing Set 6 create-VM API routes: {missing}")

    def test_create_flow_uses_inventory_next_vmid(self):
        from app.proxmox.inventory import FakeProxmoxInventoryAdapter

        class NextIdAdapter(FakeProxmoxInventoryAdapter):
            def suggest_next_vmid(self):
                return 303

        with patch.object(self.api_v1_router, "_inventory_adapter", return_value=NextIdAdapter()):
            draft_response = asyncio.run(
                self.api_v1_router.create_vm_draft(
                    {"operator_id": "api-nextid-test", "job_id": "job-api-nextid"}
                )
            )
            plan_response = asyncio.run(
                self.api_v1_router.plan_vm_draft(
                    "draft-job-api-nextid",
                    {"operator_id": "api-nextid-test", "job_id": "job-api-nextid"},
                )
            )

        self.assertTrue(draft_response["ok"])
        self.assertEqual(303, draft_response["data"]["proposed_vmid"])
        self.assertTrue(plan_response["ok"])
        self.assertEqual(303, plan_response["data"]["vmid"])

    def test_create_flow_publishes_job_run_progress(self):
        job_id = "job-api-progress-contract"
        payload = {
            "operator_id": "api-progress-test",
            "job_id": job_id,
            "static_ip": "192.168.2.150",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }

        asyncio.run(self.api_v1_router.create_vm_draft(payload))
        asyncio.run(self.api_v1_router.preflight_vm_draft("draft-api-progress-contract", payload))
        asyncio.run(self.api_v1_router.plan_vm_draft("draft-api-progress-contract", payload))

        jobs_response = asyncio.run(self.api_v1_router.list_jobs())
        jobs = {job["job_id"]: job for job in jobs_response["data"]}
        self.assertIn(job_id, jobs)
        job = jobs[job_id]
        self.assertEqual("vm_create", job["job_type"])
        self.assertIn(job["status"], {"in_progress", "blocked"})
        self.assertGreaterEqual(job["progress_percent"], 1)
        self.assertTrue(any(step["id"] == "plan" for step in job["steps"]))

        detail_response = asyncio.run(self.api_v1_router.get_job(job_id))
        artifact_response = asyncio.run(self.api_v1_router.list_job_artifacts(job_id))
        self.assertEqual(job_id, detail_response["data"]["job_id"])
        self.assertTrue(any(artifact["type"] == "plan" for artifact in artifact_response["data"]))

    def test_nested_network_payload_is_preserved_in_plan_review(self):
        for suffix, network in {
            "camel": {
                "bridgeId": "vmbr0",
                "staticIp": "192.168.2.150",
                "prefix": 25,
                "gateway": "192.168.2.254",
                "ipMode": "static",
            },
            "snake": {
                "bridge_id": "vmbr0",
                "static_ip": "192.168.2.149",
                "prefix": 25,
                "gateway": "192.168.2.254",
                "ip_mode": "static",
            },
        }.items():
            with self.subTest(suffix=suffix):
                payload = {
                    "operator_id": "api-nested-network-test",
                    "job_id": f"job-api-nested-network-{suffix}",
                    "target_node_id": "yoonmanserver2",
                    "network_id": "server-net",
                    "network": network,
                }

                response = asyncio.run(self.api_v1_router.plan_vm_draft(f"draft-api-nested-network-{suffix}", payload))

                self.assertTrue(response["ok"])
                plan_network = response["data"]["network"]
                review_network = response["data"]["review_confirm"]["network"]
                expected_static_ip = network.get("staticIp") or network.get("static_ip")
                self.assertEqual("vmbr0", plan_network["bridge_id"])
                self.assertEqual(expected_static_ip, plan_network["static_ip"])
                self.assertEqual(25, plan_network["prefix"])
                self.assertEqual("192.168.2.254", plan_network["gateway"])
                self.assertEqual(plan_network, review_network)


if __name__ == "__main__":
    unittest.main()
