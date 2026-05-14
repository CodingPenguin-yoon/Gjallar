"""Tests for VMInstance manifest generation used by Create VM review plans."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TEST_SSH_PUBLIC_KEY = (
    "ssh-ed25519 "
    "AAAAC3NzaC1lZDI1NTE5AAAAIAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8g "
    "gjallar@test"
)
TEST_SSH_FINGERPRINT = "SHA256:mKqU+0K8OhKmA8bBQi9Rz0Q5l7/g160hIP+rJYSTNj4"


class VmCreateManifestGenerationTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.shared_root = Path(self._temp_dir.name) / "nfs"
        (self.shared_root / "IaC" / ".git").mkdir(parents=True)
        (self.shared_root / "IaC" / "manifests" / "vms").mkdir(parents=True)
        (self.shared_root / "IaC" / "manifests" / "networks").mkdir(parents=True)
        (self.shared_root / "IaC" / "generated").mkdir(parents=True)
        (self.shared_root / "IaC-state" / "gjallar").mkdir(parents=True)
        (self.shared_root / "IaC" / "manifests" / "networks" / "network-profiles.yaml").write_text(
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
        self._env = patch.dict("os.environ", {"GJALLAR_SHARED_ROOT": str(self.shared_root)}, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._temp_dir.cleanup()

    def test_vm_instance_manifest_contains_reviewed_desired_state_without_secrets(self):
        from app.proxmox.inventory import FakeProxmoxInventoryAdapter
        from app.vm_create.drafts import build_default_vm_draft
        from app.vm_create.manifest import build_vm_instance_manifest, render_vm_instance_manifest_yaml
        from app.vm_create.preflight import run_preflight

        draft = build_default_vm_draft(
            operator_id="test-operator",
            job_id="job-manifest",
            target_node_id="yoonmanserver2",
            bridge_id="vmbr0",
            static_ip="192.168.2.142",
            prefix=25,
            gateway="192.168.2.254",
            proposed_vmid=303,
        )
        preflight = run_preflight(draft, inventory_adapter=FakeProxmoxInventoryAdapter())

        manifest = build_vm_instance_manifest(draft, preflight)
        rendered = render_vm_instance_manifest_yaml(manifest)

        self.assertEqual("gjallar/v1", manifest["apiVersion"])
        self.assertEqual("VMInstance", manifest["kind"])
        self.assertEqual("vm-job-manifest", manifest["metadata"]["id"])
        self.assertEqual("job-manifest", manifest["metadata"]["request_id"])
        self.assertEqual("pending", manifest["status"]["phase"])
        self.assertEqual(303, manifest["spec"]["proxmox_vmid"])
        self.assertEqual("proxmox_nextid", manifest["spec"]["proxmox_vmid_allocation"]["mode"])
        self.assertEqual("yoonmanserver2", manifest["spec"]["node"])
        self.assertEqual("general-vm", manifest["spec"]["profile_id"])
        self.assertEqual("ubuntu-template", manifest["spec"]["template_id"])
        self.assertEqual("yoonmanserver2", manifest["spec"]["template_source"]["node"])
        self.assertEqual(9000, manifest["spec"]["template_source"]["vmid"])
        self.assertEqual("local-lvm", manifest["spec"]["storage"])
        self.assertEqual("yoon", manifest["spec"]["access"]["username"])
        self.assertFalse(manifest["spec"]["access"]["password_login"])
        self.assertTrue(manifest["spec"]["access"]["ssh_key_present"])
        self.assertEqual(TEST_SSH_FINGERPRINT, manifest["spec"]["access"]["fingerprint"])
        self.assertEqual("vmbr0", manifest["spec"]["network"]["bridge_id"])
        self.assertNotIn("profile_id", manifest["spec"]["network"])
        self.assertEqual("192.168.2.142", manifest["spec"]["network"]["static_ip"])
        self.assertEqual(25, manifest["spec"]["network"]["prefix"])
        self.assertEqual("192.168.2.254", manifest["spec"]["network"]["gateway"])
        self.assertEqual("192.168.2.142", manifest["spec"]["network"]["ip"])
        self.assertEqual("stopped", manifest["spec"]["lifecycle"]["desired_power_state"])
        self.assertIn("/IaC-state/gjallar/vm-job-manifest/terraform.tfstate", manifest["spec"]["state_backend"]["path"])
        self.assertNotIn("raw-token-secret", rendered)
        self.assertNotIn("operator:raw-url-password", rendered)
        self.assertNotIn(TEST_SSH_PUBLIC_KEY.split()[1], rendered)

    def test_plan_writes_manifest_artifact_and_git_diff_summary(self):
        from app.proxmox.inventory import FakeProxmoxInventoryAdapter
        from app.vm_create.drafts import build_default_vm_draft
        from app.vm_create.planner import build_vm_create_plan
        from app.vm_create.preflight import run_preflight

        draft = build_default_vm_draft(
            operator_id="test-operator",
            job_id="job-manifest-plan",
            target_node_id="yoonmanserver2",
            bridge_id="vmbr0",
            static_ip="192.168.2.142",
            prefix=24,
            gateway="192.168.2.1",
            proposed_vmid=304,
        )
        preflight = run_preflight(draft, inventory_adapter=FakeProxmoxInventoryAdapter())

        with tempfile.TemporaryDirectory() as run_dir:
            plan = build_vm_create_plan(draft, preflight, run_dir=run_dir)
            artifacts_by_type = {artifact.type: artifact for artifact in plan.artifacts}
            manifest_path = Path(artifacts_by_type["vm_instance_manifest"].path)
            diff_path = Path(artifacts_by_type["planned_git_diff"].path)

            self.assertTrue(manifest_path.exists())
            self.assertIn("kind: VMInstance", manifest_path.read_text())
            self.assertIn("manifests/vms/vm-job-manifest-plan.yaml", diff_path.read_text())

        self.assertIn("manifests/vms/vm-job-manifest-plan.yaml", plan.review_confirm["planned_git_diff_summary"])


if __name__ == "__main__":
    unittest.main()
