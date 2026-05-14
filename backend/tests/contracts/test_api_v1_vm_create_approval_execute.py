"""RED tests for /api/v1 VM create approval and safe execute boundary."""

import asyncio
import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from fastapi import HTTPException

from app.vm_create.terraform_runner import TerraformRunnerError


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


class ApiV1VmCreateApprovalExecuteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp_dir = tempfile.TemporaryDirectory()
        cls.shared_root = Path(cls._temp_dir.name) / "nfs"
        cls.iac_root = cls.shared_root / "IaC"
        (cls.iac_root / "manifests" / "vms").mkdir(parents=True)
        (cls.iac_root / "manifests" / "networks").mkdir(parents=True)
        (cls.iac_root / "generated").mkdir(parents=True)
        (cls.shared_root / "IaC-state" / "gjallar").mkdir(parents=True)
        _git(cls.iac_root, "init")
        (cls.iac_root / ".gitignore").write_text("*.tfstate\n", encoding="utf-8")
        (cls.iac_root / "manifests" / "vms" / ".gitkeep").write_text("", encoding="utf-8")
        (cls.iac_root / "manifests" / "networks" / "network-profiles.yaml").write_text(
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
        (cls.iac_root / "generated" / ".gitkeep").write_text("", encoding="utf-8")
        _git(cls.iac_root, "add", ".")
        _git(cls.iac_root, "commit", "-m", "chore: init api test iac")
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

    def test_approval_and_execute_routes_exist_under_api_v1(self):
        expected = {
            "/api/v1/vm-create/{draft_id}/approve",
            "/api/v1/vm-create/{draft_id}/proxmox-preview",
            "/api/v1/vm-create/{draft_id}/proxmox-create",
            "/api/v1/vm-create/{draft_id}/terraform-plan",
            "/api/v1/vm-create/{draft_id}/terraform-apply",
            "/api/v1/vm-create/{draft_id}/execute",
            "/api/v1/vm-create/{draft_id}/archive",
        }
        missing = sorted(expected - self.paths)
        self.assertEqual([], missing, f"Missing approval/execute safety routes: {missing}")

    def test_approve_validates_exact_plan_artifacts_without_side_effects(self):
        draft_id = "draft-api-approval-green"
        payload = {
            "operator_id": "api-approval-test",
            "job_id": draft_id,
            "static_ip": "192.168.2.144",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        review = plan_response["data"]["review_confirm"]

        approve_response = asyncio.run(
            self.api_v1_router.approve_vm_draft(
                draft_id,
                {
                    **payload,
                    "plan_artifact_id": review["plan_artifact_id"],
                    "review_summary_checksum": review["review_summary_checksum"],
                    "yellow_risk_acknowledged": False,
                },
            )
        )

        self.assertTrue(approve_response["ok"])
        decision = approve_response["data"]
        self.assertTrue(decision["can_approve"])
        self.assertTrue(decision["can_execute"])
        self.assertEqual([], decision["side_effects"])
        self.assertEqual("approved", decision["approval_record"]["decision"])
        self.assertEqual("approval_validation_only", approve_response["meta"]["mode"])

    def test_approve_rejects_wrong_review_checksum(self):
        draft_id = "draft-api-approval-wrong-checksum"
        payload = {
            "operator_id": "api-approval-test",
            "job_id": draft_id,
            "static_ip": "192.168.2.145",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        review = plan_response["data"]["review_confirm"]

        approve_response = asyncio.run(
            self.api_v1_router.approve_vm_draft(
                draft_id,
                {
                    **payload,
                    "plan_artifact_id": review["plan_artifact_id"],
                    "review_summary_checksum": "sha256:" + "0" * 64,
                    "yellow_risk_acknowledged": False,
                },
            )
        )

        self.assertTrue(approve_response["ok"])
        decision = approve_response["data"]
        self.assertFalse(decision["can_approve"])
        self.assertFalse(decision["can_execute"])
        self.assertEqual([], decision["side_effects"])
        self.assertIn("checksum", decision["reason"].lower())

    def test_proxmox_preview_after_approval_does_not_mutate(self):
        draft_id = "draft-api-proxmox-preview"
        payload = {
            "operator_id": "api-proxmox-test",
            "job_id": "job-api-proxmox-preview",
            "static_ip": "192.168.2.142",
            "prefix": 25,
            "gateway": "192.168.2.254",
        }
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        review = plan_response["data"]["review_confirm"]
        before = _git(self.iac_root, "rev-parse", "HEAD")

        with patch.object(self.api_v1_router, "run_proxmox_create") as mutation:
            response = asyncio.run(
                self.api_v1_router.preview_vm_draft_proxmox_create(
                    draft_id,
                    {
                        **payload,
                        "plan_artifact_id": review["plan_artifact_id"],
                        "review_summary_checksum": review["review_summary_checksum"],
                        "yellow_risk_acknowledged": False,
                    },
                )
            )

        after = _git(self.iac_root, "rev-parse", "HEAD")
        self.assertTrue(response["ok"])
        self.assertEqual("proxmox_native_preview_no_mutation", response["meta"]["mode"])
        self.assertFalse(response["data"]["proxmox_mutation_enabled"])
        self.assertFalse(response["data"]["terraform_apply_enabled"])
        self.assertEqual([], response["data"]["side_effects"])
        self.assertEqual("/nodes/yoonmanserver2/qemu/9000/clone", response["data"]["clone"]["endpoint"])
        self.assertEqual(before, after)
        mutation.assert_not_called()

    def test_proxmox_create_blocks_without_ack_or_manifest_commit(self):
        draft_id = "draft-api-proxmox-create-gates"
        payload = {
            "operator_id": "api-proxmox-test",
            "job_id": "job-api-proxmox-create-gates",
            "static_ip": "192.168.2.143",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        review = plan_response["data"]["review_confirm"]
        approved_payload = {
            **payload,
            "plan_artifact_id": review["plan_artifact_id"],
            "review_summary_checksum": review["review_summary_checksum"],
            "yellow_risk_acknowledged": False,
        }

        with self.assertRaises(HTTPException) as no_ack:
            asyncio.run(self.api_v1_router.create_vm_draft_proxmox_native(draft_id, approved_payload))
        self.assertEqual(409, no_ack.exception.status_code)
        self.assertEqual("PROXMOX_CREATE_ACK_REQUIRED", no_ack.exception.detail["code"])

        with self.assertRaises(HTTPException) as no_commit:
            asyncio.run(
                self.api_v1_router.create_vm_draft_proxmox_native(
                    draft_id,
                    {**approved_payload, "proxmox_mutation_acknowledged": True},
                )
            )
        self.assertEqual(409, no_commit.exception.status_code)
        self.assertEqual("PROXMOX_CREATE_MANIFEST_COMMIT_BLOCKED", no_commit.exception.detail["code"])

    def test_proxmox_create_success_marks_applied_only_with_observed_after_artifact(self):
        from app.jobs.artifacts import write_json_artifact

        draft_id = "draft-api-proxmox-create-success"
        payload = {
            "operator_id": "api-proxmox-test",
            "job_id": "job-api-proxmox-create-success",
            "static_ip": "192.168.2.144",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        review = plan_response["data"]["review_confirm"]
        approved_payload = {
            **payload,
            "plan_artifact_id": review["plan_artifact_id"],
            "review_summary_checksum": review["review_summary_checksum"],
            "yellow_risk_acknowledged": False,
        }
        execute_response = asyncio.run(self.api_v1_router.execute_vm_draft(draft_id, approved_payload))
        manifest_commit_sha = execute_response["data"]["commit_sha"]

        def fake_create(plan, *, run_dir, client):
            artifact = write_json_artifact(
                run_dir=run_dir,
                job_id=plan.job_id,
                artifact_type="observed_after",
                filename="observed_after.json",
                payload={
                    "vmid": plan.vmid,
                    "target_node_id": plan.target_node_id,
                    "exists": True,
                    "status": "stopped",
                    "fingerprint": {"hash": "sha256:" + "1" * 64},
                },
            )
            return {
                "job_id": plan.job_id,
                "manifest_id": plan.manifest_id,
                "vmid": plan.vmid,
                "target_node_id": plan.target_node_id,
                "success": True,
                "status": "completed",
                "message": "VM exists on target node and is stopped",
                "task": {"upid": "UPID:yoonmanserver2:0001:test", "exitstatus": "OK"},
                "observed_after": {"status": "stopped", "fingerprint": {"hash": "sha256:" + "1" * 64}},
                "observed_after_artifact": artifact.to_dict(),
                "artifacts": [artifact.to_dict()],
                "side_effects": ["proxmox_clone_invoked", "proxmox_task_polled", "proxmox_config_updated", "proxmox_post_check_observed"],
            }

        with patch.object(self.api_v1_router, "get_default_proxmox_mutation_client", return_value=object()):
            with patch.object(self.api_v1_router, "run_proxmox_create", side_effect=fake_create):
                response = asyncio.run(
                    self.api_v1_router.create_vm_draft_proxmox_native(
                        draft_id,
                        {
                            **approved_payload,
                            "manifest_commit_sha": manifest_commit_sha,
                            "proxmox_mutation_acknowledged": True,
                        },
                    )
                )

        manifest_path = self.iac_root / "manifests" / "vms" / "vm-job-api-proxmox-create-success.yaml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        self.assertTrue(response["ok"])
        self.assertEqual("proxmox_native_create_live_mutation", response["meta"]["mode"])
        self.assertTrue(response["data"]["proxmox_create_ran"])
        self.assertTrue(response["data"]["proxmox_mutation_enabled"])
        self.assertFalse(response["data"]["terraform_apply_enabled"])
        self.assertEqual("applied", response["data"]["manifest_status"]["phase"])
        self.assertEqual("applied", manifest["status"]["phase"])
        self.assertEqual("stopped", response["data"]["observed_after"]["status"])
        self.assertTrue(Path(response["data"]["observed_after_artifact"]["path"]).is_file())

    def test_proxmox_create_powered_on_post_check_needs_reconciliation_not_applied(self):
        from app.jobs.artifacts import write_json_artifact

        draft_id = "draft-api-proxmox-create-reconcile"
        payload = {
            "operator_id": "api-proxmox-test",
            "job_id": "job-api-proxmox-create-reconcile",
            "static_ip": "192.168.2.145",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        review = plan_response["data"]["review_confirm"]
        approved_payload = {
            **payload,
            "plan_artifact_id": review["plan_artifact_id"],
            "review_summary_checksum": review["review_summary_checksum"],
            "yellow_risk_acknowledged": False,
        }
        execute_response = asyncio.run(self.api_v1_router.execute_vm_draft(draft_id, approved_payload))
        manifest_commit_sha = execute_response["data"]["commit_sha"]

        def fake_create(plan, *, run_dir, client):
            artifact = write_json_artifact(
                run_dir=run_dir,
                job_id=plan.job_id,
                artifact_type="observed_after",
                filename="observed_after.json",
                payload={
                    "vmid": plan.vmid,
                    "target_node_id": plan.target_node_id,
                    "exists": True,
                    "status": "running",
                    "fingerprint": {"hash": "sha256:" + "2" * 64},
                },
            )
            return {
                "job_id": plan.job_id,
                "manifest_id": plan.manifest_id,
                "vmid": plan.vmid,
                "target_node_id": plan.target_node_id,
                "success": False,
                "status": "needs_reconciliation",
                "message": "VM post-check expected stopped, observed running",
                "observed_after": {"status": "running", "fingerprint": {"hash": "sha256:" + "2" * 64}},
                "observed_after_artifact": artifact.to_dict(),
                "artifacts": [artifact.to_dict()],
                "side_effects": ["proxmox_clone_invoked", "proxmox_task_polled", "proxmox_config_updated", "proxmox_post_check_observed"],
            }

        with patch.object(self.api_v1_router, "get_default_proxmox_mutation_client", return_value=object()):
            with patch.object(self.api_v1_router, "run_proxmox_create", side_effect=fake_create):
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(
                        self.api_v1_router.create_vm_draft_proxmox_native(
                            draft_id,
                            {
                                **approved_payload,
                                "manifest_commit_sha": manifest_commit_sha,
                                "proxmox_mutation_acknowledged": True,
                            },
                        )
                    )

        manifest_path = self.iac_root / "manifests" / "vms" / "vm-job-api-proxmox-create-reconcile.yaml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("PROXMOX_CREATE_NEEDS_RECONCILIATION", raised.exception.detail["code"])
        self.assertEqual("needs_reconciliation", raised.exception.detail["manifest_status"]["phase"])
        self.assertEqual("needs_reconciliation", manifest["status"]["phase"])
        self.assertNotEqual("applied", manifest["status"]["phase"])
        self.assertEqual("", _git(self.iac_root, "status", "--porcelain"))


    def test_string_false_does_not_acknowledge_yellow_risk(self):
        draft_id = "draft-api-approval-yellow"
        payload = {
            "operator_id": "api-approval-test",
            "job_id": draft_id,
            "ip_mode": "dhcp",
        }
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        self.assertEqual("yellow", plan_response["data"]["risk_summary"]["level"])
        review = plan_response["data"]["review_confirm"]

        approve_response = asyncio.run(
            self.api_v1_router.approve_vm_draft(
                draft_id,
                {
                    **payload,
                    "plan_artifact_id": review["plan_artifact_id"],
                    "review_summary_checksum": review["review_summary_checksum"],
                    "yellow_risk_acknowledged": "false",
                },
            )
        )

        decision = approve_response["data"]
        self.assertFalse(decision["can_approve"])
        self.assertFalse(decision["can_execute"])
        self.assertTrue(decision["requires_yellow_ack"])
        self.assertEqual([], decision["side_effects"])

    def test_artifact_paths_stay_under_preview_run_root_for_malicious_job_id(self):
        draft_id = "draft-api-path-containment"
        plan_response = asyncio.run(
            self.api_v1_router.plan_vm_draft(
                draft_id,
                {
                    "operator_id": "api-approval-test",
                    "job_id": "/tmp/gjallar-path-escape",
                    "static_ip": "192.168.2.146",
                    "prefix": 24,
                    "gateway": "192.168.2.1",
                },
            )
        )
        base = Path(self._temp_dir.name) / "runs"
        base_resolved = base.resolve()
        for artifact in plan_response["data"]["artifacts"]:
            artifact_path = Path(artifact["path"]).resolve()
            self.assertTrue(
                artifact_path.is_relative_to(base_resolved),
                f"artifact path escaped preview root: {artifact_path}",
            )

    def test_execute_route_blocks_without_exact_approval_metadata(self):
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                self.api_v1_router.execute_vm_draft(
                    "draft-api-execute-blocked",
                    {"confirm": True, "job_id": "draft-api-execute-blocked"},
                )
            )
        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("EXECUTE_APPROVAL_GATE_BLOCKED", raised.exception.detail["code"])
        self.assertEqual([], raised.exception.detail["side_effects"])

    def test_terraform_plan_route_prepares_workspace_after_approval_without_running(self):
        draft_id = "draft-api-terraform-plan"
        payload = {
            "operator_id": "api-terraform-test",
            "job_id": "job-api-terraform-plan",
            "static_ip": "192.168.2.148",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        review = plan_response["data"]["review_confirm"]
        before = _git(self.iac_root, "rev-parse", "HEAD")

        response = asyncio.run(
            self.api_v1_router.prepare_vm_draft_terraform_plan(
                draft_id,
                {
                    **payload,
                    "plan_artifact_id": review["plan_artifact_id"],
                    "review_summary_checksum": review["review_summary_checksum"],
                    "yellow_risk_acknowledged": False,
                },
            )
        )

        after = _git(self.iac_root, "rev-parse", "HEAD")
        data = response["data"]
        self.assertTrue(response["ok"])
        self.assertEqual("terraform_plan_prepare_only", response["meta"]["mode"])
        self.assertEqual(before, after)
        self.assertEqual("job-api-terraform-plan", data["job_id"])
        self.assertEqual("vm-job-api-terraform-plan", data["manifest_id"])
        self.assertEqual(["terraform_workspace_created"], data["side_effects"])
        self.assertFalse(data["terraform_plan_ran"])
        self.assertEqual([], data["terraform_plan_results"])
        self.assertFalse(data["terraform_apply_enabled"])
        self.assertFalse(data["proxmox_mutation_enabled"])
        self.assertTrue(Path(data["tfvars_path"]).is_file())
        self.assertTrue(Path(data["backend_config_path"]).is_file())
        self.assertEqual(
            [
                ["terraform", "init", "-input=false", "-backend-config=backend.hcl"],
                ["terraform", "plan", "-input=false", "-out=tfplan", "-var-file=terraform.auto.tfvars.json"],
            ],
            data["commands"],
        )
        self.assertEqual("", _git(self.iac_root, "status", "--porcelain"))

    def test_terraform_plan_route_requires_explicit_ack_before_live_read(self):
        draft_id = "draft-api-terraform-plan-ack"
        payload = {
            "operator_id": "api-terraform-test",
            "job_id": "job-api-terraform-plan-ack",
            "static_ip": "192.168.2.149",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        review = plan_response["data"]["review_confirm"]

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                self.api_v1_router.prepare_vm_draft_terraform_plan(
                    draft_id,
                    {
                        **payload,
                        "plan_artifact_id": review["plan_artifact_id"],
                        "review_summary_checksum": review["review_summary_checksum"],
                        "yellow_risk_acknowledged": False,
                        "run_terraform_plan": True,
                    },
                )
            )

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("TERRAFORM_PLAN_RUN_ACK_REQUIRED", raised.exception.detail["code"])
        self.assertEqual(["terraform_workspace_created"], raised.exception.detail["side_effects"])

    def test_terraform_plan_route_can_run_plan_when_acknowledged_and_runner_succeeds(self):
        draft_id = "draft-api-terraform-plan-run"
        payload = {
            "operator_id": "api-terraform-test",
            "job_id": "job-api-terraform-plan-run",
            "static_ip": "192.168.2.150",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        review = plan_response["data"]["review_confirm"]

        def fake_run(workspace):
            return [
                {
                    "command": ["terraform", "init", "-input=false", "-backend-config=backend.hcl"],
                    "returncode": 0,
                    "stdout": "init ok",
                    "stderr": "",
                },
                {
                    "command": ["terraform", "plan", "-input=false", "-out=tfplan", "-var-file=terraform.auto.tfvars.json"],
                    "returncode": 0,
                    "stdout": "plan ok",
                    "stderr": "",
                },
            ]

        with patch.object(self.api_v1_router, "run_terraform_plan", side_effect=fake_run):
            response = asyncio.run(
                self.api_v1_router.prepare_vm_draft_terraform_plan(
                    draft_id,
                    {
                        **payload,
                        "plan_artifact_id": review["plan_artifact_id"],
                        "review_summary_checksum": review["review_summary_checksum"],
                        "yellow_risk_acknowledged": False,
                        "run_terraform_plan": True,
                        "terraform_plan_acknowledged": True,
                    },
                )
            )

        self.assertTrue(response["ok"])
        self.assertEqual("terraform_plan_live_read_only", response["meta"]["mode"])
        self.assertTrue(response["data"]["terraform_plan_ran"])
        self.assertEqual("plan ok", response["data"]["terraform_plan_results"][1]["stdout"])
        self.assertFalse(response["data"]["terraform_apply_enabled"])
        self.assertFalse(response["data"]["proxmox_mutation_enabled"])

    def test_terraform_apply_route_requires_explicit_apply_ack(self):
        draft_id = "draft-api-terraform-apply-ack"
        payload = {
            "operator_id": "api-terraform-test",
            "job_id": "job-api-terraform-apply-ack",
            "static_ip": "192.168.2.149",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        review = plan_response["data"]["review_confirm"]

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                self.api_v1_router.apply_vm_draft_terraform_plan(
                    draft_id,
                    {
                        **payload,
                        "plan_artifact_id": review["plan_artifact_id"],
                        "review_summary_checksum": review["review_summary_checksum"],
                        "yellow_risk_acknowledged": False,
                        "terraform_plan_acknowledged": True,
                    },
                )
            )

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("TERRAFORM_APPLY_ACK_REQUIRED", raised.exception.detail["code"])
        self.assertEqual([], raised.exception.detail["side_effects"])

    def test_terraform_apply_route_runs_only_after_plan_and_manifest_commit_ack(self):
        draft_id = "draft-api-terraform-apply-run"
        payload = {
            "operator_id": "api-terraform-test",
            "job_id": "job-api-terraform-apply-run",
            "static_ip": "192.168.2.146",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        review = plan_response["data"]["review_confirm"]
        approved_payload = {
            **payload,
            "plan_artifact_id": review["plan_artifact_id"],
            "review_summary_checksum": review["review_summary_checksum"],
            "yellow_risk_acknowledged": False,
        }
        execute_response = asyncio.run(self.api_v1_router.execute_vm_draft(draft_id, approved_payload))
        manifest_commit_sha = execute_response["data"]["commit_sha"]

        def fake_plan(workspace):
            Path(workspace.plan_path).write_text("fake binary plan\n", encoding="utf-8")
            return [
                {
                    "command": ["terraform", "init", "-input=false", "-backend-config=backend.hcl"],
                    "returncode": 0,
                    "stdout": "init ok",
                    "stderr": "",
                },
                {
                    "command": ["terraform", "plan", "-input=false", "-out=tfplan", "-var-file=terraform.auto.tfvars.json"],
                    "returncode": 0,
                    "stdout": "plan ok",
                    "stderr": "",
                },
            ]

        with patch.object(self.api_v1_router, "run_terraform_plan", side_effect=fake_plan):
            plan_run_response = asyncio.run(
                self.api_v1_router.prepare_vm_draft_terraform_plan(
                    draft_id,
                    {
                        **approved_payload,
                        "run_terraform_plan": True,
                        "terraform_plan_acknowledged": True,
                    },
                )
            )

        def fake_apply(workspace):
            return [
                {
                    "command": ["terraform", "apply", "-input=false", "-auto-approve", "tfplan"],
                    "returncode": 0,
                    "stdout": "apply ok",
                    "stderr": "",
                }
            ]

        with patch.object(self.api_v1_router, "run_terraform_apply", side_effect=fake_apply):
            response = asyncio.run(
                self.api_v1_router.apply_vm_draft_terraform_plan(
                    draft_id,
                    {
                        **approved_payload,
                        "manifest_commit_sha": manifest_commit_sha,
                        "expected_plan_path": plan_run_response["data"]["plan_path"],
                        "terraform_plan_acknowledged": True,
                        "terraform_apply_acknowledged": True,
                        "proxmox_mutation_acknowledged": True,
                    },
                )
            )

        self.assertTrue(response["ok"])
        self.assertEqual("terraform_apply_live_mutation", response["meta"]["mode"])
        self.assertTrue(response["data"]["terraform_apply_ran"])
        self.assertTrue(response["data"]["terraform_apply_enabled"])
        self.assertTrue(response["data"]["proxmox_mutation_enabled"])
        self.assertEqual(manifest_commit_sha, response["data"]["manifest_commit_sha"])
        self.assertEqual(
            [
                "terraform_workspace_created",
                "iac_manifest_status_applying",
                "iac_git_commit_created",
                "iac_manifest_status_applied",
                "iac_git_commit_created",
                "terraform_apply_invoked",
            ],
            response["data"]["side_effects"],
        )
        self.assertEqual("applied", response["data"]["manifest_status"]["phase"])
        self.assertEqual("apply ok", response["data"]["terraform_apply_results"][0]["stdout"])

    def test_terraform_apply_failure_marks_manifest_apply_failed(self):
        draft_id = "draft-api-terraform-apply-fail"
        payload = {
            "operator_id": "api-terraform-test",
            "job_id": "job-api-terraform-apply-fail",
            "static_ip": "192.168.2.142",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        review = plan_response["data"]["review_confirm"]
        approved_payload = {
            **payload,
            "plan_artifact_id": review["plan_artifact_id"],
            "review_summary_checksum": review["review_summary_checksum"],
            "yellow_risk_acknowledged": False,
        }
        execute_response = asyncio.run(self.api_v1_router.execute_vm_draft(draft_id, approved_payload))
        manifest_commit_sha = execute_response["data"]["commit_sha"]

        def fake_plan(workspace):
            Path(workspace.plan_path).write_text("fake binary plan\n", encoding="utf-8")
            return [{"command": ["terraform", "plan"], "returncode": 0, "stdout": "plan ok", "stderr": ""}]

        with patch.object(self.api_v1_router, "run_terraform_plan", side_effect=fake_plan):
            plan_run_response = asyncio.run(
                self.api_v1_router.prepare_vm_draft_terraform_plan(
                    draft_id,
                    {
                        **approved_payload,
                        "run_terraform_plan": True,
                        "terraform_plan_acknowledged": True,
                    },
                )
            )

        def fake_apply(_workspace):
            raise TerraformRunnerError(
                "apply failed",
                results=[{"command": ["terraform", "apply"], "returncode": 1, "stdout": "", "stderr": "provider error"}],
            )

        with patch.object(self.api_v1_router, "run_terraform_apply", side_effect=fake_apply):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(
                    self.api_v1_router.apply_vm_draft_terraform_plan(
                        draft_id,
                        {
                            **approved_payload,
                            "manifest_commit_sha": manifest_commit_sha,
                            "expected_plan_path": plan_run_response["data"]["plan_path"],
                            "terraform_plan_acknowledged": True,
                            "terraform_apply_acknowledged": True,
                            "proxmox_mutation_acknowledged": True,
                        },
                    )
                )

        detail = raised.exception.detail
        manifest_path = self.iac_root / "manifests" / "vms" / "vm-job-api-terraform-apply-fail.yaml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("TERRAFORM_APPLY_FAILED", detail["code"])
        self.assertEqual("apply_failed", detail["manifest_status"]["phase"])
        self.assertEqual("provider error", detail["manifest_status"]["last_error"])
        self.assertEqual("apply_failed", manifest["status"]["phase"])
        self.assertEqual("provider error", manifest["status"]["last_error"])
        self.assertIn("terraform_apply_invoked", detail["side_effects"])
        self.assertEqual("", _git(self.iac_root, "status", "--porcelain"))

    def test_archive_route_moves_unapplied_manifest_without_proxmox_mutation(self):
        draft_id = "draft-api-archive"
        payload = {
            "operator_id": "api-archive-test",
            "job_id": "job-api-archive",
            "static_ip": "192.168.2.143",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        review = plan_response["data"]["review_confirm"]
        approved_payload = {
            **payload,
            "plan_artifact_id": review["plan_artifact_id"],
            "review_summary_checksum": review["review_summary_checksum"],
            "yellow_risk_acknowledged": False,
        }
        asyncio.run(self.api_v1_router.execute_vm_draft(draft_id, approved_payload))

        response = asyncio.run(
            self.api_v1_router.archive_vm_draft_manifest(
                draft_id,
                {
                    **payload,
                    "archive_acknowledged": True,
                    "reason": "test cleanup",
                },
            )
        )

        active = self.iac_root / "manifests" / "vms" / "vm-job-api-archive.yaml"
        archived = self.iac_root / "manifests" / "archive" / "vms" / "vm-job-api-archive.yaml"
        self.assertTrue(response["ok"])
        self.assertEqual("gitops_archive_only", response["meta"]["mode"])
        self.assertFalse(response["data"]["proxmox_mutation_enabled"])
        self.assertFalse(response["data"]["terraform_apply_enabled"])
        self.assertFalse(active.exists())
        self.assertTrue(archived.is_file())
        self.assertEqual("archived", response["data"]["manifest_status"]["phase"])
        self.assertEqual("", _git(self.iac_root, "status", "--porcelain"))

    def test_execute_route_commits_manifest_only_after_approval(self):
        draft_id = "draft-api-execute-commit"
        payload = {
            "operator_id": "api-execute-test",
            "job_id": "job-api-execute-commit",
            "static_ip": "192.168.2.147",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        review = plan_response["data"]["review_confirm"]
        before = _git(self.iac_root, "rev-parse", "HEAD")

        execute_response = asyncio.run(
            self.api_v1_router.execute_vm_draft(
                draft_id,
                {
                    **payload,
                    "plan_artifact_id": review["plan_artifact_id"],
                    "review_summary_checksum": review["review_summary_checksum"],
                    "yellow_risk_acknowledged": False,
                },
            )
        )

        after = _git(self.iac_root, "rev-parse", "HEAD")
        manifest_path = self.iac_root / "manifests" / "vms" / "vm-job-api-execute-commit.yaml"
        self.assertTrue(execute_response["ok"])
        self.assertEqual("gitops_commit_only", execute_response["meta"]["mode"])
        self.assertNotEqual(before, after)
        self.assertEqual(after, execute_response["data"]["commit_sha"])
        self.assertEqual("gitops_commit_only", execute_response["data"]["execution_intent"])
        self.assertFalse(execute_response["data"]["terraform_apply_enabled"])
        self.assertFalse(execute_response["data"]["proxmox_mutation_enabled"])
        self.assertEqual(["iac_manifest_written", "iac_git_commit_created"], execute_response["data"]["side_effects"])
        self.assertTrue(manifest_path.is_file())
        self.assertIn("kind: VMInstance", manifest_path.read_text(encoding="utf-8"))
        self.assertEqual("", _git(self.iac_root, "status", "--porcelain"))


if __name__ == "__main__":
    unittest.main()
