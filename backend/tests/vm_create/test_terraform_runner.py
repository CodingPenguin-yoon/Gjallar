"""Tests for safe Terraform workspace generation from approved Create VM plans."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TerraformRunnerTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self._temp_dir.name)
        self.shared_root = self.root / "nfs"
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
        self._env = patch.dict(
            "os.environ",
            {
                "GJALLAR_SHARED_ROOT": str(self.shared_root),
                "GJALLAR_DEFAULT_SSH_PUBLIC_KEY": "ssh-ed25519 AAAATEST gjallar@test",
                "PROXMOX_API_URL": "https://pve.example.invalid:8006/api2/json",
                "PROXMOX_API_TOKEN_ID": "root@pam!terraform",
                "PROXMOX_API_TOKEN_SECRET": "token-secret",
            },
            clear=False,
        )
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._temp_dir.cleanup()

    def _plan(self):
        from app.proxmox.inventory import FakeProxmoxInventoryAdapter
        from app.vm_create.drafts import build_default_vm_draft
        from app.vm_create.planner import build_vm_create_plan
        from app.vm_create.preflight import run_preflight

        draft = build_default_vm_draft(
            operator_id="terraform-test",
            job_id="job-terraform-runner",
            target_node_id="yoonmanserver2",
            static_ip="192.168.2.142",
            proposed_vmid=306,
        )
        preflight = run_preflight(draft, inventory_adapter=FakeProxmoxInventoryAdapter())
        self.assertEqual("green", preflight.risk_level)
        return build_vm_create_plan(draft, preflight, run_dir=self.root / "run")

    def test_terraform_vars_use_plan_review_values_and_safe_power_defaults(self):
        from app.vm_create.terraform_runner import terraform_vars_from_plan

        vars_payload = terraform_vars_from_plan(self._plan())

        self.assertEqual(306, vars_payload["vm_id"])
        self.assertEqual("gjallar-vm-job-terraform-runner", vars_payload["vm_name"])
        self.assertEqual("yoonmanserver2", vars_payload["target_node"])
        self.assertEqual("yoonmanserver2/9000", vars_payload["template_id"])
        self.assertEqual(2, vars_payload["cpu_cores"])
        self.assertEqual(4, vars_payload["memory_gb"])
        self.assertEqual(40, vars_payload["disk_size_gb"])
        self.assertEqual("local-lvm", vars_payload["storage_id"])
        self.assertEqual(["vmbr0"], vars_payload["network_ids"])
        self.assertEqual("192.168.2.142/24", vars_payload["vm_ip"])
        self.assertEqual("192.168.2.1", vars_payload["vm_gateway"])
        self.assertEqual("ssh-ed25519 AAAATEST gjallar@test", vars_payload["ssh_public_key"])
        self.assertFalse(vars_payload["start_on_create"])
        self.assertFalse(vars_payload["on_boot"])
        self.assertNotIn("proxmox_api_token_secret", vars_payload)

    def test_build_workspace_writes_backend_tfvars_and_copied_module(self):
        from app.vm_create.terraform_runner import build_terraform_workspace, terraform_plan_commands

        plan = self._plan()
        workspace = build_terraform_workspace(plan, workspace_root=self.root / "workspace")
        terraform_dir = Path(workspace.terraform_dir)

        self.assertEqual(plan.job_id, workspace.job_id)
        self.assertEqual(plan.manifest_id, workspace.manifest_id)
        self.assertEqual(["terraform_workspace_created"], workspace.side_effects)
        self.assertTrue((terraform_dir / "main.tf").is_file())
        self.assertTrue((terraform_dir / "backend.tf").is_file())
        self.assertTrue((terraform_dir / "backend.hcl").is_file())
        self.assertTrue((terraform_dir / "terraform.auto.tfvars.json").is_file())
        self.assertTrue(Path(workspace.state_path).parent.is_dir())
        self.assertIn(plan.terraform_state_path, (terraform_dir / "backend.hcl").read_text(encoding="utf-8"))
        self.assertIn("started = var.start_on_create", (terraform_dir / "main.tf").read_text(encoding="utf-8"))

        tfvars = json.loads((terraform_dir / "terraform.auto.tfvars.json").read_text(encoding="utf-8"))
        self.assertEqual(306, tfvars["vm_id"])
        self.assertEqual("yoonmanserver2/9000", tfvars["template_id"])
        self.assertFalse(tfvars["start_on_create"])
        self.assertFalse(tfvars["on_boot"])

        self.assertEqual(
            [
                ["terraform", "init", "-input=false", "-backend-config=backend.hcl"],
                ["terraform", "plan", "-input=false", "-out=tfplan", "-var-file=terraform.auto.tfvars.json"],
            ],
            terraform_plan_commands(workspace),
        )

    def test_run_terraform_plan_uses_workspace_dir_and_raises_on_failure(self):
        from app.vm_create.terraform_runner import (
            TerraformRunnerError,
            build_terraform_workspace,
            run_terraform_plan,
        )

        workspace = build_terraform_workspace(self._plan(), workspace_root=self.root / "workspace")
        calls = []

        def ok_runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

        results = run_terraform_plan(workspace, command_runner=ok_runner)

        self.assertEqual(2, len(results))
        self.assertEqual("ok", results[0]["stdout"])
        self.assertEqual(str(Path(workspace.terraform_dir)), calls[0][1]["cwd"])
        self.assertFalse(calls[0][1]["check"])
        self.assertTrue(calls[0][1]["capture_output"])
        self.assertTrue(calls[0][1]["text"])
        self.assertEqual("https://pve.example.invalid:8006/api2/json", calls[0][1]["env"]["TF_VAR_proxmox_api_url"])
        self.assertEqual("root@pam!terraform", calls[0][1]["env"]["TF_VAR_proxmox_api_token_id"])
        self.assertEqual("token-secret", calls[0][1]["env"]["TF_VAR_proxmox_api_token_secret"])

        def fail_runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="provider error")

        with self.assertRaises(TerraformRunnerError) as raised:
            run_terraform_plan(workspace, command_runner=fail_runner)
        self.assertEqual("provider error", raised.exception.results[0]["stderr"])

    def test_run_terraform_apply_requires_existing_plan_file_and_uses_workspace_dir(self):
        from app.vm_create.terraform_runner import (
            TerraformRunnerError,
            build_terraform_workspace,
            run_terraform_apply,
            terraform_apply_commands,
        )

        workspace = build_terraform_workspace(self._plan(), workspace_root=self.root / "workspace")
        self.assertEqual(
            [["terraform", "apply", "-input=false", "-auto-approve", "tfplan"]],
            terraform_apply_commands(workspace),
        )

        with self.assertRaises(TerraformRunnerError):
            run_terraform_apply(workspace)

        Path(workspace.plan_path).write_text("fake binary plan\n", encoding="utf-8")
        calls = []

        def ok_runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, stdout="apply ok", stderr="")

        results = run_terraform_apply(workspace, command_runner=ok_runner)

        self.assertEqual(1, len(results))
        self.assertEqual("apply ok", results[0]["stdout"])
        self.assertEqual(str(Path(workspace.terraform_dir)), calls[0][1]["cwd"])
        self.assertFalse(calls[0][1]["check"])
        self.assertTrue(calls[0][1]["capture_output"])
        self.assertTrue(calls[0][1]["text"])


if __name__ == "__main__":
    unittest.main()
