"""Tests for approval-gated Create VM GitOps manifest commits."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_AUTHOR_NAME": "Test Gjallar",
            "GIT_AUTHOR_EMAIL": "gjallar-test@example.invalid",
            "GIT_COMMITTER_NAME": "Test Gjallar",
            "GIT_COMMITTER_EMAIL": "gjallar-test@example.invalid",
        },
    )
    return completed.stdout.strip()


class VmCreateGitOpsCommitTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.shared_root = Path(self._temp_dir.name) / "nfs"
        self.iac_root = self.shared_root / "IaC"
        (self.iac_root / "manifests" / "vms").mkdir(parents=True)
        (self.iac_root / "manifests" / "networks").mkdir(parents=True)
        (self.iac_root / "generated").mkdir(parents=True)
        (self.shared_root / "IaC-state" / "gjallar").mkdir(parents=True)
        _git(self.iac_root, "init")
        (self.iac_root / ".gitignore").write_text("*.tfstate\n", encoding="utf-8")
        (self.iac_root / "manifests" / "vms" / ".gitkeep").write_text("", encoding="utf-8")
        (self.iac_root / "manifests" / "networks" / "network-profiles.yaml").write_text(
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
        (self.iac_root / "generated" / ".gitkeep").write_text("", encoding="utf-8")
        _git(self.iac_root, "add", ".")
        _git(self.iac_root, "commit", "-m", "chore: init test iac")
        self._env = patch.dict("os.environ", {"GJALLAR_SHARED_ROOT": str(self.shared_root)}, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._temp_dir.cleanup()

    def _approved_plan(self, *, job_id="job-gitops"):
        from app.proxmox.inventory import FakeProxmoxInventoryAdapter
        from app.vm_create.drafts import build_default_vm_draft
        from app.vm_create.planner import build_vm_create_plan
        from app.vm_create.preflight import run_preflight

        draft = build_default_vm_draft(
            operator_id="test-operator",
            job_id=job_id,
            target_node_id="yoonmanserver2",
            bridge_id="vmbr0",
            static_ip="192.168.2.142",
            prefix=24,
            gateway="192.168.2.1",
            proposed_vmid=305,
        )
        preflight = run_preflight(draft, inventory_adapter=FakeProxmoxInventoryAdapter())
        self.assertEqual("green", preflight.risk_level)
        return build_vm_create_plan(draft, preflight, run_dir=Path(self._temp_dir.name) / "run" / job_id)

    def test_commit_plan_manifest_writes_allowlisted_manifest_and_creates_commit_only(self):
        from app.vm_create.gitops import commit_plan_manifest

        plan = self._approved_plan()
        before = _git(self.iac_root, "rev-parse", "HEAD")

        result = commit_plan_manifest(plan)

        target = self.iac_root / "manifests" / "vms" / "vm-job-gitops.yaml"
        after = _git(self.iac_root, "rev-parse", "HEAD")
        self.assertTrue(target.is_file())
        self.assertNotEqual(before, after)
        self.assertEqual(after, result.commit_sha)
        self.assertEqual("gitops_commit_only", result.execution_intent)
        self.assertFalse(result.apply_enabled)
        self.assertEqual("proxmox_create_pending", result.next_stage)
        self.assertEqual(["iac_manifest_written", "iac_git_commit_created"], result.side_effects)
        self.assertIn("kind: VMInstance", target.read_text(encoding="utf-8"))
        self.assertEqual("pending", result.manifest_status["phase"])
        self.assertEqual("", _git(self.iac_root, "status", "--porcelain"))

    def test_commit_plan_manifest_is_idempotent_when_manifest_matches(self):
        from app.vm_create.gitops import commit_plan_manifest

        plan = self._approved_plan(job_id="job-idempotent")
        first = commit_plan_manifest(plan)
        before = _git(self.iac_root, "rev-parse", "HEAD")

        second = commit_plan_manifest(plan)

        after = _git(self.iac_root, "rev-parse", "HEAD")
        self.assertEqual(before, after)
        self.assertEqual(first.commit_sha, second.commit_sha)
        self.assertEqual(["iac_manifest_already_present"], second.side_effects)
        self.assertEqual("", _git(self.iac_root, "status", "--porcelain"))

    def test_commit_plan_manifest_is_idempotent_after_status_updates(self):
        from app.vm_create.gitops import commit_plan_manifest, update_plan_manifest_status

        plan = self._approved_plan(job_id="job-status-idempotent")
        first = commit_plan_manifest(plan)
        status_result = update_plan_manifest_status(plan, "apply_failed", last_error="provider timeout")

        second = commit_plan_manifest(plan)

        self.assertNotEqual(first.commit_sha, status_result.commit_sha)
        self.assertEqual(status_result.commit_sha, second.commit_sha)
        self.assertEqual(["iac_manifest_already_present"], second.side_effects)
        self.assertEqual("apply_failed", second.manifest_status["phase"])
        self.assertEqual("", _git(self.iac_root, "status", "--porcelain"))

    def test_update_plan_manifest_status_commits_phase_change(self):
        from app.vm_create.gitops import commit_plan_manifest, update_plan_manifest_status

        plan = self._approved_plan(job_id="job-status-update")
        commit_plan_manifest(plan)

        result = update_plan_manifest_status(plan, "apply_failed", last_error="apply failed")

        target = self.iac_root / "manifests" / "vms" / "vm-job-status-update.yaml"
        manifest = yaml.safe_load(target.read_text(encoding="utf-8"))
        self.assertEqual("apply_failed", manifest["status"]["phase"])
        self.assertEqual("apply failed", manifest["status"]["last_error"])
        self.assertTrue(manifest["status"]["updated_at"])
        self.assertEqual("apply_failed", result.manifest_status["phase"])
        self.assertEqual(["iac_manifest_status_apply_failed", "iac_git_commit_created"], result.side_effects)
        self.assertEqual("", _git(self.iac_root, "status", "--porcelain"))

    def test_archive_plan_manifest_moves_unapplied_manifest_out_of_active_folder(self):
        from app.vm_create.gitops import archive_plan_manifest, commit_plan_manifest, update_plan_manifest_status

        plan = self._approved_plan(job_id="job-archive")
        commit_plan_manifest(plan)
        update_plan_manifest_status(plan, "apply_failed", last_error="apply failed")

        result = archive_plan_manifest(plan, reason="operator cleanup", operator_id="tester")

        active = self.iac_root / "manifests" / "vms" / "vm-job-archive.yaml"
        archived = self.iac_root / "manifests" / "archive" / "vms" / "vm-job-archive.yaml"
        manifest = yaml.safe_load(archived.read_text(encoding="utf-8"))
        self.assertFalse(active.exists())
        self.assertTrue(archived.is_file())
        self.assertEqual("archived", manifest["status"]["phase"])
        self.assertEqual("operator cleanup", manifest["status"]["last_error"])
        self.assertEqual("tester", manifest["status"]["archived_by"])
        self.assertEqual("gitops_archive_only", result.execution_intent)
        self.assertEqual(["iac_manifest_archived", "iac_git_commit_created"], result.side_effects)
        self.assertEqual("", _git(self.iac_root, "status", "--porcelain"))

    def test_commit_plan_manifest_refuses_dirty_iac_repo(self):
        from app.vm_create.gitops import GitOpsCommitError, commit_plan_manifest

        plan = self._approved_plan(job_id="job-dirty")
        (self.iac_root / "generated" / "dirty.txt").write_text("dirty\n", encoding="utf-8")

        with self.assertRaises(GitOpsCommitError):
            commit_plan_manifest(plan)

    def test_commit_plan_manifest_refuses_existing_manifest(self):
        from app.vm_create.gitops import GitOpsCommitError, commit_plan_manifest

        plan = self._approved_plan(job_id="job-existing")
        target = self.iac_root / "manifests" / "vms" / "vm-job-existing.yaml"
        target.write_text("already here\n", encoding="utf-8")
        _git(self.iac_root, "add", "manifests/vms/vm-job-existing.yaml")
        _git(self.iac_root, "commit", "-m", "test: existing manifest")

        with self.assertRaises(GitOpsCommitError):
            commit_plan_manifest(plan)


if __name__ == "__main__":
    unittest.main()
