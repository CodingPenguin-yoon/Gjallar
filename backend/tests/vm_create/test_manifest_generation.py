"""Tests for VMInstance manifest generation used by Create VM review plans."""

from app.db import create_vm_profiles as profile_repository

import tempfile
import unittest

TEST_SSH_PUBLIC_KEY = (
    "ssh-ed25519 "
    "AAAAC3NzaC1lZDI1NTE5AAAAIAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8g "
    "gjallar@test"
)
TEST_SSH_FINGERPRINT = "SHA256:mKqU+0K8OhKmA8bBQi9Rz0Q5l7/g160hIP+rJYSTNj4"


class VmCreateManifestGenerationTests(unittest.TestCase):
    def test_vm_instance_manifest_contains_reviewed_desired_state_without_secrets(self):
        from app.proxmox.inventory import FakeProxmoxInventoryAdapter
        from app.vm_create.drafts import build_default_vm_draft
        from app.vm_create.manifest import build_vm_instance_manifest, render_vm_instance_manifest_yaml
        from app.vm_create.preflight import run_preflight

        draft = build_default_vm_draft(
            profiles=profile_repository.get_active_create_vm_profiles_by_id(),
            operator_id="test-operator",
            job_id="job-manifest",
            target_node_id="yoonmanserver2",
            bridge_id="vmbr0",
            static_ip="192.168.2.142",
            prefix=25,
            gateway="192.168.2.254",
            proposed_vmid=303,
        )
        preflight = run_preflight(draft, profiles=profile_repository.get_active_create_vm_profiles_by_id(), inventory_adapter=FakeProxmoxInventoryAdapter())

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
        self.assertEqual("stopped", manifest["spec"]["lifecycle"]["power_policy"])
        self.assertNotIn("state_" + "backend", manifest["spec"])
        self.assertNotIn("raw-token-secret", rendered)
        self.assertNotIn("operator:raw-url-password", rendered)
        self.assertNotIn(TEST_SSH_PUBLIC_KEY.split()[1], rendered)

    def test_plan_writes_manifest_artifact_and_git_diff_summary(self):
        from app.jobs.artifacts import read_artifact_text
        from app.proxmox.inventory import FakeProxmoxInventoryAdapter
        from app.vm_create.drafts import build_default_vm_draft
        from app.vm_create.planner import calculate_vm_create_plan
        from app.vm_create.plan_persistence import persist_vm_create_plan
        from app.vm_create.preflight import run_preflight

        draft = build_default_vm_draft(
            profiles=profile_repository.get_active_create_vm_profiles_by_id(),
            operator_id="test-operator",
            job_id="job-manifest-plan",
            target_node_id="yoonmanserver2",
            bridge_id="vmbr0",
            static_ip="192.168.2.142",
            prefix=24,
            gateway="192.168.2.1",
            proposed_vmid=304,
        )
        preflight = run_preflight(draft, profiles=profile_repository.get_active_create_vm_profiles_by_id(), inventory_adapter=FakeProxmoxInventoryAdapter())

        with tempfile.TemporaryDirectory() as run_dir:
            plan = persist_vm_create_plan(calculate_vm_create_plan(draft, preflight), run_dir=run_dir)
            artifacts_by_type = {artifact.type: artifact for artifact in plan.artifacts}

            self.assertTrue(artifacts_by_type["vm_instance_manifest"].path.startswith("db://job-artifacts/"))
            self.assertIn("kind: VMInstance", read_artifact_text(artifacts_by_type["vm_instance_manifest"]))
            self.assertIn("manifests/vms/vm-job-manifest-plan.yaml", read_artifact_text(artifacts_by_type["planned_git_diff"]))

        self.assertIn("manifests/vms/vm-job-manifest-plan.yaml", plan.review_confirm["planned_git_diff_summary"])


if __name__ == "__main__":
    unittest.main()
