"""RED tests for Set 6 /api/v1 create-VM route surface."""

import contextlib
import io
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

TEST_SSH_PUBLIC_KEY = (
    "ssh-ed25519 "
    "AAAAC3NzaC1lZDI1NTE5AAAAIAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8g "
    "gjallar@test"
)
TEST_SSH_FINGERPRINT = "SHA256:mKqU+0K8OhKmA8bBQi9Rz0Q5l7/g160hIP+rJYSTNj4"


class ApiV1VmCreateRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp_dir = tempfile.TemporaryDirectory()
        cls.shared_root = Path(cls._temp_dir.name) / "nfs"
        (cls.shared_root / "IaC" / ".git").mkdir(parents=True)
        (cls.shared_root / "IaC" / "manifests" / "vms").mkdir(parents=True)
        (cls.shared_root / "IaC" / "manifests" / "networks").mkdir(parents=True)
        (cls.shared_root / "IaC" / "generated").mkdir(parents=True)
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
                "GJALLAR_DEFAULT_SSH_PUBLIC_KEY": TEST_SSH_PUBLIC_KEY,
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

    def test_profiles_route_returns_three_active_db_seed_profiles_without_forbidden_fields(self):
        response = asyncio.run(self.api_v1_router.list_profiles())

        self.assertTrue(response["ok"])
        profiles = response["data"]
        self.assertEqual(["general-vm", "runtime-server", "development-vm"], [item["profile_id"] for item in profiles])
        self.assertEqual(
            ["범용 VM", "서비스 실행용 VM", "개발/테스트용 VM"],
            [item["display_name_ko"] for item in profiles],
        )
        forbidden = {
            "network",
            "network_id",
            "bridge",
            "bridge_id",
            "static_ip",
            "target_node_id",
            "target_node_candidates",
            "storage_id",
            "template_family",
            "template_id",
            "template_vmid",
            "default_ip_mode",
            "power_policy",
            "profile_version",
        }
        for profile in profiles:
            self.assertTrue(profile["enabled"])
            self.assertTrue(profile["create_enabled"])
            self.assertEqual(profile["profile_id"], profile["id"])
            self.assertEqual("db_seed", profile["source"])
            self.assertEqual("read_only", profile["management"])
            self.assertEqual({"default", "min", "max"}, set(profile["hardware"]["cpu"]))
            self.assertTrue(profile["template_requirements"]["require_cloud_init"])
            self.assertTrue(profile["template_requirements"]["require_qemu_guest_agent"])
            self.assertEqual("yoon", profile["access_recommendations"]["default_user"])
            self.assertEqual(set(), forbidden & set(profile))
            rendered = repr(profile)
            self.assertNotIn("server-net", rendered)
            self.assertNotIn("network_id", rendered)

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
                    "network_id": "evil-net",
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
                rendered = repr(response["data"])
                self.assertNotIn("network_id", rendered)
                self.assertNotIn("networkId", rendered)
                self.assertNotIn("evil-net", rendered)
                self.assertNotIn("server-net", rendered)

    def test_nested_access_payload_is_preserved_safely_in_plan_review(self):
        from app.jobs.artifacts import read_artifact_text

        for suffix, access in {
            "camel": {"username": "ubuntu", "sshPublicKey": TEST_SSH_PUBLIC_KEY, "passwordLogin": True},
            "snake": {"cloud_init_user": "debian", "ssh_public_key": TEST_SSH_PUBLIC_KEY, "password_login": True},
        }.items():
            with self.subTest(suffix=suffix):
                payload = {
                    "operator_id": "api-access-test",
                    "job_id": f"job-api-access-{suffix}",
                    "target_node_id": "yoonmanserver2",
                    "bridge_id": "vmbr0",
                    "static_ip": "192.168.2.150",
                    "prefix": 24,
                    "gateway": "192.168.2.1",
                    "access": access,
                }

                draft_response = asyncio.run(self.api_v1_router.create_vm_draft(payload))
                preflight_response = asyncio.run(self.api_v1_router.preflight_vm_draft(f"draft-job-api-access-{suffix}", payload))
                plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(f"draft-job-api-access-{suffix}", payload))

                username = access.get("username") or access.get("cloud_init_user")
                self.assertTrue(draft_response["ok"])
                self.assertEqual(username, draft_response["data"]["access"]["username"])
                self.assertFalse(draft_response["data"]["access"]["password_login"])
                self.assertTrue(preflight_response["ok"])
                self.assertEqual(username, preflight_response["data"]["access"]["username"])
                self.assertFalse(preflight_response["data"]["access"]["password_login"])
                self.assertEqual(TEST_SSH_FINGERPRINT, preflight_response["data"]["access"]["fingerprint"])
                self.assertTrue(plan_response["ok"])
                self.assertEqual(username, plan_response["data"]["review_confirm"]["access"]["username"])
                self.assertFalse(plan_response["data"]["review_confirm"]["access"]["password_login"])
                self.assertEqual(TEST_SSH_FINGERPRINT, plan_response["data"]["access"]["fingerprint"])
                artifacts_by_type = {artifact["type"]: artifact for artifact in plan_response["data"]["artifacts"]}
                manifest = yaml.safe_load(read_artifact_text(artifacts_by_type["vm_instance_manifest"]))
                self.assertFalse(manifest["spec"]["access"]["password_login"])
                rendered = repr(plan_response["data"])
                self.assertNotIn(TEST_SSH_PUBLIC_KEY.split()[1], rendered)
                self.assertNotIn("ssh_public_key", rendered)

    def test_selected_profile_and_hardware_overrides_are_preserved_in_active_api_outputs(self):
        payload = {
            "operator_id": "api-profile-test",
            "job_id": "job-api-profile",
            "profileId": "runtime-server",
            "target_node_id": "yoonmanserver2",
            "bridge_id": "vmbr0",
            "static_ip": "192.168.2.150",
            "prefix": 24,
            "gateway": "192.168.2.1",
            "hardware": {"cpu": 6, "memoryMb": 12288, "diskGb": 120},
            "network_id": "evil-net",
        }

        draft_response = asyncio.run(self.api_v1_router.create_vm_draft(payload))
        preflight_response = asyncio.run(self.api_v1_router.preflight_vm_draft("draft-job-api-profile", payload))
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft("draft-job-api-profile", payload))

        self.assertTrue(draft_response["ok"])
        self.assertEqual("runtime-server", draft_response["data"]["profile_id"])
        self.assertEqual({"cpu": 6, "memory_mb": 12288, "disk_gb": 120}, draft_response["data"]["hardware"])
        self.assertTrue(preflight_response["ok"])
        self.assertEqual("runtime-server", preflight_response["data"]["profile_id"])
        self.assertEqual(16, preflight_response["data"]["profile_hardware_limits"]["cpu"]["max"])
        self.assertTrue(plan_response["ok"])
        self.assertEqual("runtime-server", plan_response["data"]["profile_id"])
        self.assertEqual("runtime-server", plan_response["data"]["review_confirm"]["profile_id"])
        self.assertEqual(1000, plan_response["data"]["profile_hardware_limits"]["disk_gb"]["max"])
        rendered = repr(plan_response["data"])
        self.assertNotIn("network_id", rendered)
        self.assertNotIn("networkId", rendered)
        self.assertNotIn("evil-net", rendered)

    def test_preflight_api_returns_red_for_selected_live_template_missing_required_capability(self):
        from app.proxmox.inventory import FakeProxmoxInventoryAdapter
        from app.proxmox.models import TemplateInventory

        class MissingCapabilityAdapter(FakeProxmoxInventoryAdapter):
            def __init__(self):
                super().__init__()
                self._templates = (
                    TemplateInventory(
                        template_id="ubuntu-api-no-agent",
                        vmid=9006,
                        name="ubuntu-api-no-agent",
                        node_id="yoonmanserver2",
                        storage_id="local-lvm",
                        family="ubuntu",
                        cloud_init_ready=True,
                        guest_agent_ready=False,
                        disk_gb=50,
                    ),
                )

        payload = {
            "operator_id": "api-template-test",
            "job_id": "job-api-template-requirements",
            "profile_id": "general-vm",
            "target_node_id": "yoonmanserver2",
            "bridge_id": "vmbr0",
            "static_ip": "192.168.2.150",
            "prefix": 24,
            "gateway": "192.168.2.1",
            "template_id": "ubuntu-api-no-agent",
            "template_vmid": 9006,
            "template_node_id": "yoonmanserver2",
        }

        with patch.object(self.api_v1_router, "_inventory_adapter", return_value=MissingCapabilityAdapter()):
            preflight_response = asyncio.run(
                self.api_v1_router.preflight_vm_draft("draft-job-api-template-requirements", payload)
            )

        self.assertTrue(preflight_response["ok"])
        self.assertEqual("red", preflight_response["data"]["risk_level"])
        red_codes = {risk["code"] for risk in preflight_response["data"]["risks"] if risk["level"] == "red"}
        self.assertIn("template_guest_agent_unverified", red_codes)

    def test_unknown_profile_red_blocks_preflight_without_rewriting_profile_id(self):
        payload = {
            "operator_id": "api-profile-test",
            "job_id": "job-api-unknown-profile",
            "profile_id": "unknown-profile",
            "target_node_id": "yoonmanserver2",
            "bridge_id": "vmbr0",
            "static_ip": "192.168.2.150",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }

        draft_response = asyncio.run(self.api_v1_router.create_vm_draft(payload))
        preflight_response = asyncio.run(self.api_v1_router.preflight_vm_draft("draft-job-api-unknown-profile", payload))

        self.assertTrue(draft_response["ok"])
        self.assertEqual("unknown-profile", draft_response["data"]["profile_id"])
        self.assertTrue(preflight_response["ok"])
        self.assertEqual("red", preflight_response["data"]["risk_level"])
        self.assertEqual("unknown-profile", preflight_response["data"]["profile_id"])
        red_codes = {risk["code"] for risk in preflight_response["data"]["risks"] if risk["level"] == "red"}
        self.assertIn("unknown_profile", red_codes)


if __name__ == "__main__":
    unittest.main()
