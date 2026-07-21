"""Tests for /api/v1 VM create approval and native create boundary."""

import asyncio
import contextlib
import io
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

TEST_SSH_PUBLIC_KEY = (
    "ssh-ed25519 "
    "AAAAC3NzaC1lZDI1NTE5AAAAIAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8g "
    "gjallar@test"
)


class ApiV1VmCreateApprovalExecuteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            from app.main import app
            from app.api.v1 import router as api_v1_router
        cls.app = app
        cls.paths = {getattr(route, "path", "") for route in app.routes}
        cls.api_v1_router = api_v1_router

    def _approved_payload(self, draft_id, payload):
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        review = plan_response["data"]["review_confirm"]
        return {
            **payload,
            "plan_artifact_id": review["plan_artifact_id"],
            "review_summary_checksum": review["review_summary_checksum"],
            "yellow_risk_acknowledged": False,
            "proxmox_mutation_acknowledged": True,
        }

    def _plan_from_payload(self, draft_id, payload):
        return self.api_v1_router._api_preview_plan_from_payload(draft_id, payload)

    def _successful_create_result(self, plan, run_dir, fingerprint_seed="1"):
        from app.jobs.artifacts import write_json_artifact

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
                "fingerprint": {"hash": "sha256:" + str(fingerprint_seed) * 64},
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
            "observed_after": {"status": "stopped", "fingerprint": {"hash": "sha256:" + str(fingerprint_seed) * 64}},
            "observed_after_artifact": artifact.to_dict(),
            "artifacts": [artifact.to_dict()],
            "side_effects": [
                "proxmox_clone_invoked",
                "proxmox_task_polled",
                "proxmox_config_updated",
                "proxmox_post_check_observed",
            ],
        }

    def _record_existing_create_request(self, *, draft_id, payload, status, result=None):
        from app.db.vm_runtime import record_vm_create_request

        plan = self._plan_from_payload(draft_id, payload)
        if result is None:
            result = {
                "job_id": plan.job_id,
                "manifest_id": plan.manifest_id,
                "vmid": plan.vmid,
                "target_node_id": plan.target_node_id,
                "success": False,
                "status": status,
                "message": f"existing {status} create request",
                "side_effects": [],
            }
        record_vm_create_request(
            plan,
            status=status,
            approval={"can_execute": True},
            result=result,
            actor={"username": "existing-operator", "role": "operator"},
        )
        return plan

    def _assert_existing_target_status_blocks_new_request(self, *, existing_status, expected_code):
        existing_payload = {
            "operator_id": "api-proxmox-test",
            "job_id": f"job-existing-target-{existing_status}",
            "bridge_id": "vmbr0",
            "static_ip": "192.168.2.152",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }
        result = None
        if existing_status == "completed":
            existing_plan = self._plan_from_payload(f"draft-existing-target-{existing_status}", existing_payload)
            result = self._successful_create_result(existing_plan, self.api_v1_router._api_preview_run_dir(existing_plan.job_id), fingerprint_seed="5")
        self._record_existing_create_request(
            draft_id=f"draft-existing-target-{existing_status}",
            payload=existing_payload,
            status=existing_status,
            result=result,
        )
        new_payload = {
            "operator_id": "api-proxmox-test",
            "job_id": f"job-new-target-{existing_status}",
            "bridge_id": "vmbr0",
            "static_ip": "192.168.2.153",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }

        with patch.object(self.api_v1_router, "acquire_target_operation_lock", return_value={"handle": "lock-should-not-run"}, create=True) as acquire_lock:
            with patch.object(self.api_v1_router, "run_proxmox_create", create=True) as mutation:
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(
                        self.api_v1_router.create_vm_draft_proxmox_native(
                            f"draft-new-target-{existing_status}",
                            self._approved_payload(f"draft-new-target-{existing_status}", new_payload),
                        )
                    )

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual(expected_code, raised.exception.detail["code"])
        self.assertEqual(existing_status, raised.exception.detail["existing_status"])
        self.assertEqual(existing_payload["job_id"], raised.exception.detail["request_id"])
        self.assertEqual("vmid:102", raised.exception.detail["target_id"])
        self.assertEqual(new_payload["job_id"], raised.exception.detail["requested_request_id"])
        acquire_lock.assert_not_called()
        mutation.assert_not_called()

    def test_approval_and_native_create_routes_exist_under_api_v1(self):
        expected = {
            "/api/v1/vm-create/{draft_id}/approve",
            "/api/v1/vm-create/{draft_id}/proxmox-preview",
            "/api/v1/vm-create/{draft_id}/proxmox-create",
        }
        missing = sorted(expected - self.paths)
        self.assertEqual([], missing, f"Missing approval/native create safety routes: {missing}")
        self.assertNotIn("/api/v1/vm-create/{draft_id}/terraform-plan", self.paths)
        self.assertNotIn("/api/v1/vm-create/{draft_id}/terraform-apply", self.paths)
        self.assertNotIn("/api/v1/vm-create/{draft_id}/execute", self.paths)
        self.assertNotIn("/api/v1/vm-create/{draft_id}/archive", self.paths)

    def test_removed_terraform_and_gitops_routes_are_not_accepted(self):
        client = TestClient(self.app)

        for suffix in ("terraform-plan", "terraform-apply", "execute", "archive"):
            response = client.post(f"/api/v1/vm-create/removed-terraform/{suffix}", json={})
            self.assertIn(response.status_code, {404, 405})

    def test_approve_validates_exact_plan_artifacts_without_side_effects(self):
        draft_id = "draft-api-approval-green"
        payload = {
            "operator_id": "api-approval-test",
            "job_id": draft_id,
            "bridge_id": "vmbr0",
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
            "bridge_id": "vmbr0",
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
            "bridge_id": "vmbr0",
            "static_ip": "192.168.2.142",
            "prefix": 25,
            "gateway": "192.168.2.254",
        }
        plan_response = asyncio.run(self.api_v1_router.plan_vm_draft(draft_id, payload))
        review = plan_response["data"]["review_confirm"]

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

        self.assertTrue(response["ok"])
        self.assertEqual("proxmox_native_preview_no_mutation", response["meta"]["mode"])
        self.assertFalse(response["data"]["proxmox_mutation_enabled"])
        self.assertEqual([], response["data"]["side_effects"])
        self.assertEqual("/nodes/yoonmanserver2/qemu/9000/clone", response["data"]["clone"]["endpoint"])
        mutation.assert_not_called()

    def test_proxmox_create_blocks_without_final_acknowledgement(self):
        draft_id = "draft-api-proxmox-create-gates"
        payload = {
            "operator_id": "api-proxmox-test",
            "job_id": "job-api-proxmox-create-gates",
            "bridge_id": "vmbr0",
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

    def test_proxmox_create_success_marks_applied_only_with_observed_after_artifact(self):
        draft_id = "draft-api-proxmox-create-success"
        payload = {
            "operator_id": "api-proxmox-test",
            "job_id": "job-api-proxmox-create-success",
            "bridge_id": "vmbr0",
            "static_ip": "192.168.2.144",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }
        def fake_create(plan, *, run_dir, client):
            return self._successful_create_result(plan, run_dir)

        with patch.object(self.api_v1_router, "get_default_proxmox_mutation_client", return_value=object()):
            with patch.object(self.api_v1_router, "acquire_target_operation_lock", return_value={"handle": "success-lock"}, create=True):
                with patch.object(self.api_v1_router, "release_target_operation_lock", create=True):
                    with patch.object(self.api_v1_router, "run_proxmox_create", side_effect=fake_create):
                        response = asyncio.run(
                            self.api_v1_router.create_vm_draft_proxmox_native(
                                draft_id,
                                self._approved_payload(draft_id, payload),
                            )
                        )

        self.assertTrue(response["ok"])
        self.assertEqual("proxmox_native_create_live_mutation", response["meta"]["mode"])
        self.assertTrue(response["data"]["proxmox_create_ran"])
        self.assertTrue(response["data"]["proxmox_mutation_enabled"])
        self.assertNotIn("manifest_status", response["data"])
        self.assertIn("proxmox_preview", response["data"])
        self.assertEqual("stopped", response["data"]["observed_after"]["status"])
        self.assertTrue(response["data"]["observed_after_artifact"]["path"].startswith("db://job-artifacts/"))
        self.assertEqual("stopped", response["data"]["vm_instance"]["status"])
        self.assertEqual(payload["job_id"], response["data"]["operation_id"])
        self.assertEqual("vm_create", response["data"]["operation"]["operation_type"])
        self.assertEqual("succeeded", response["data"]["operation"]["status"])

        from app.operations.facade import get_operation

        detail = get_operation(payload["job_id"])
        self.assertEqual("succeeded", detail["operation"]["status"])
        self.assertEqual(
            [
                "operation_created",
                "approval_granted",
                "dispatch_prepared",
                "dispatch_result_observed",
                "task_and_state_observed",
                "verification_succeeded",
            ],
            [event["event_type"] for event in detail["events"]],
        )
        self.assertEqual("yoonmanserver2:102", detail["operation"]["details"]["workload"]["vm_instance_id"])

    def test_proxmox_create_success_releases_target_lock_after_all_persistence(self):
        draft_id = "draft-api-proxmox-create-success-release-lock"
        payload = {
            "operator_id": "api-proxmox-test",
            "job_id": "job-api-proxmox-create-success-release-lock",
            "bridge_id": "vmbr0",
            "static_ip": "192.168.2.154",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }

        def fake_create(plan, *, run_dir, client):
            return self._successful_create_result(plan, run_dir, fingerprint_seed="6")

        handle = {"handle": "success-lock"}
        with patch.object(self.api_v1_router, "get_default_proxmox_mutation_client", return_value=object()):
            with patch.object(self.api_v1_router, "acquire_target_operation_lock", return_value=handle, create=True):
                with patch.object(self.api_v1_router, "release_target_operation_lock", create=True) as release_lock:
                    with patch.object(self.api_v1_router, "run_proxmox_create", side_effect=fake_create):
                        response = asyncio.run(
                            self.api_v1_router.create_vm_draft_proxmox_native(
                                draft_id,
                                self._approved_payload(draft_id, payload),
                            )
                        )

        self.assertTrue(response["ok"])
        release_lock.assert_called_once_with(handle)

    def test_proxmox_create_clear_clone_rejection_releases_target_lock(self):
        draft_id = "draft-api-proxmox-create-clear-reject-release-lock"
        payload = {
            "operator_id": "api-proxmox-test",
            "job_id": "job-api-proxmox-create-clear-reject-release-lock",
            "bridge_id": "vmbr0",
            "static_ip": "192.168.2.155",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }

        def fake_create(plan, *, run_dir, client):
            return {
                "job_id": plan.job_id,
                "manifest_id": plan.manifest_id,
                "vmid": plan.vmid,
                "target_node_id": plan.target_node_id,
                "success": False,
                "status": "failed",
                "message": "Proxmox API HTTP 409: clone rejected",
                "task": {"status": "unknown"},
                "artifacts": [],
                "side_effects": ["proxmox_clone_rejected"],
            }

        handle = {"handle": "clear-reject-lock"}
        with patch.object(self.api_v1_router, "get_default_proxmox_mutation_client", return_value=object()):
            with patch.object(self.api_v1_router, "acquire_target_operation_lock", return_value=handle, create=True):
                with patch.object(self.api_v1_router, "release_target_operation_lock", create=True) as release_lock:
                    with patch.object(self.api_v1_router, "run_proxmox_create", side_effect=fake_create):
                        with self.assertRaises(HTTPException) as raised:
                            asyncio.run(
                                self.api_v1_router.create_vm_draft_proxmox_native(
                                    draft_id,
                                    self._approved_payload(draft_id, payload),
                                )
                            )

        self.assertEqual("PROXMOX_CREATE_FAILED", raised.exception.detail["code"])
        release_lock.assert_called_once_with(handle)
        from app.db.vm_runtime import find_vm_create_request_for_target, get_vm_create_request_record

        stored = get_vm_create_request_record(payload["job_id"])
        self.assertEqual("failed", stored["status"])
        self.assertIsNone(find_vm_create_request_for_target(vmid=102))

        with patch.object(self.api_v1_router, "run_proxmox_create", create=True) as retry_mutation:
            with self.assertRaises(HTTPException) as retry:
                asyncio.run(
                    self.api_v1_router.create_vm_draft_proxmox_native(
                        draft_id,
                        self._approved_payload(draft_id, payload),
                    )
                )

        self.assertEqual("PROXMOX_CREATE_IDEMPOTENCY_CONFLICT", retry.exception.detail["code"])
        retry_mutation.assert_not_called()

    def test_proxmox_create_ambiguous_result_retains_target_lock(self):
        draft_id = "draft-api-proxmox-create-ambiguous-retain-lock"
        payload = {
            "operator_id": "api-proxmox-test",
            "job_id": "job-api-proxmox-create-ambiguous-retain-lock",
            "bridge_id": "vmbr0",
            "static_ip": "192.168.2.156",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }

        def fake_create(plan, *, run_dir, client):
            return {
                "job_id": plan.job_id,
                "manifest_id": plan.manifest_id,
                "vmid": plan.vmid,
                "target_node_id": plan.target_node_id,
                "success": False,
                "status": "needs_reconciliation",
                "message": "clone task polling is unknown",
                "task": {"upid": "UPID:yoonmanserver2:0001:test", "status": "unknown"},
                "artifacts": [],
                "side_effects": ["proxmox_clone_invoked", "proxmox_task_poll_state_unknown"],
            }

        with patch.object(self.api_v1_router, "get_default_proxmox_mutation_client", return_value=object()):
            with patch.object(self.api_v1_router, "acquire_target_operation_lock", return_value={"handle": "ambiguous-lock"}, create=True):
                with patch.object(self.api_v1_router, "release_target_operation_lock", create=True) as release_lock:
                    with patch.object(self.api_v1_router, "run_proxmox_create", side_effect=fake_create):
                        with self.assertRaises(HTTPException) as raised:
                            asyncio.run(
                                self.api_v1_router.create_vm_draft_proxmox_native(
                                    draft_id,
                                    self._approved_payload(draft_id, payload),
                                )
                            )

        self.assertEqual("PROXMOX_CREATE_NEEDS_RECONCILIATION", raised.exception.detail["code"])
        self.assertEqual(payload["job_id"], raised.exception.detail["operation_id"])
        self.assertEqual("needs_reconciliation", raised.exception.detail["operation_status"])
        release_lock.assert_not_called()

        from app.operations.facade import get_operation

        detail = get_operation(payload["job_id"])
        self.assertEqual("needs_reconciliation", detail["operation"]["status"])
        self.assertEqual("reconciliation_required", detail["events"][-1]["event_type"])

    def test_proxmox_create_persistence_fault_after_mutation_retains_target_lock(self):
        draft_id = "draft-api-proxmox-create-persistence-fault-retain-lock"
        payload = {
            "operator_id": "api-proxmox-test",
            "job_id": "job-api-proxmox-create-persistence-fault-retain-lock",
            "bridge_id": "vmbr0",
            "static_ip": "192.168.2.157",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }

        def fake_create(plan, *, run_dir, client):
            return self._successful_create_result(plan, run_dir, fingerprint_seed="7")

        with patch.object(self.api_v1_router, "get_default_proxmox_mutation_client", return_value=object()):
            with patch.object(self.api_v1_router, "acquire_target_operation_lock", return_value={"handle": "persistence-fault-lock"}, create=True):
                with patch.object(self.api_v1_router, "release_target_operation_lock", create=True) as release_lock:
                    with patch.object(self.api_v1_router, "run_proxmox_create", side_effect=fake_create) as mutation:
                        with patch.object(self.api_v1_router, "record_vm_instance_from_create", side_effect=RuntimeError("db persistence failed")):
                            with self.assertRaises(RuntimeError):
                                asyncio.run(
                                    self.api_v1_router.create_vm_draft_proxmox_native(
                                        draft_id,
                                        self._approved_payload(draft_id, payload),
                                    )
                                )

        self.assertEqual(1, mutation.call_count)
        release_lock.assert_not_called()

        from app.operations.facade import get_operation

        detail = get_operation(payload["job_id"])
        self.assertEqual("verifying", detail["operation"]["status"])
        self.assertEqual("task_and_state_observed", detail["events"][-1]["event_type"])

        with patch.object(self.api_v1_router, "acquire_target_operation_lock", create=True) as acquire_lock:
            with patch.object(self.api_v1_router, "run_proxmox_create", create=True) as retry_mutation:
                replay = asyncio.run(
                    self.api_v1_router.create_vm_draft_proxmox_native(
                        draft_id,
                        self._approved_payload(draft_id, payload),
                    )
                )

        self.assertTrue(replay["data"]["idempotent_replay"])
        self.assertEqual("verifying", replay["data"]["operation"]["status"])
        acquire_lock.assert_not_called()
        retry_mutation.assert_not_called()
        detail = get_operation(payload["job_id"])
        self.assertEqual("compatibility_guard_blocked", detail["events"][-1]["event_type"])

    def test_proxmox_create_target_lock_busy_blocks_before_mutation_or_request_record(self):
        class Busy(Exception):
            def __init__(self):
                super().__init__("target is already locked")
                self.evidence = {"target_type": "proxmox_vm", "target_id": "vmid:102", "owner_id": "other-job"}

        draft_id = "draft-api-proxmox-create-lock-busy"
        payload = {
            "operator_id": "api-proxmox-test",
            "job_id": "job-api-proxmox-create-lock-busy",
            "bridge_id": "vmbr0",
            "static_ip": "192.168.2.147",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }

        with patch.object(self.api_v1_router, "TargetOperationLockBusy", Busy, create=True):
            with patch.object(self.api_v1_router, "acquire_target_operation_lock", side_effect=Busy(), create=True) as acquire_lock:
                with patch.object(self.api_v1_router, "release_target_operation_lock", create=True) as release_lock:
                    with patch.object(self.api_v1_router, "run_proxmox_create", create=True) as mutation:
                        with self.assertRaises(HTTPException) as raised:
                            asyncio.run(
                                self.api_v1_router.create_vm_draft_proxmox_native(
                                    draft_id,
                                    self._approved_payload(draft_id, payload),
                                )
                            )

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("PROXMOX_CREATE_TARGET_IN_PROGRESS", raised.exception.detail["code"])
        self.assertEqual("proxmox_vm", raised.exception.detail["target_type"])
        acquire_lock.assert_called_once_with(
            target_type="proxmox_vm",
            target_id="vmid:102",
            owner_id="job-api-proxmox-create-lock-busy",
            operation_type="vm_create",
        )
        release_lock.assert_not_called()
        mutation.assert_not_called()
        from app.db.models import VmCreateRequestRecord
        from app.db.session import session_scope

        with session_scope() as session:
            self.assertIsNone(session.get(VmCreateRequestRecord, "job-api-proxmox-create-lock-busy"))

    def test_common_dispatch_persistence_failure_blocks_before_proxmox_mutation(self):
        draft_id = "draft-api-proxmox-create-operation-persistence-failure"
        payload = {
            "operator_id": "api-proxmox-test",
            "job_id": "job-api-proxmox-create-operation-persistence-failure",
            "bridge_id": "vmbr0",
            "static_ip": "192.168.2.158",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }
        approved_payload = self._approved_payload(draft_id, payload)
        handle = {"handle": "operation-persistence-failure-lock"}

        with patch.object(self.api_v1_router, "acquire_target_operation_lock", return_value=handle, create=True):
            with patch.object(self.api_v1_router, "release_target_operation_lock", create=True) as release_lock:
                with patch.object(self.api_v1_router, "record_vm_create_dispatch_prepared", side_effect=RuntimeError("operation store unavailable")):
                    with patch.object(self.api_v1_router, "run_proxmox_create", create=True) as mutation:
                        with self.assertRaises(RuntimeError):
                            asyncio.run(
                                self.api_v1_router.create_vm_draft_proxmox_native(
                                    draft_id,
                                    approved_payload,
                                )
                            )

        mutation.assert_not_called()
        release_lock.assert_called_once_with(handle)

    def test_proxmox_create_replays_completed_same_intent_without_second_mutation(self):
        draft_id = "draft-api-proxmox-create-replay"
        payload = {
            "operator_id": "api-proxmox-test",
            "job_id": "job-api-proxmox-create-replay",
            "bridge_id": "vmbr0",
            "static_ip": "192.168.2.148",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }

        def fake_create(plan, *, run_dir, client):
            return self._successful_create_result(plan, run_dir, fingerprint_seed="3")

        with patch.object(self.api_v1_router, "get_default_proxmox_mutation_client", return_value=object()):
            with patch.object(self.api_v1_router, "acquire_target_operation_lock", return_value={"handle": "lock-1"}, create=True) as acquire_lock:
                with patch.object(self.api_v1_router, "release_target_operation_lock", create=True) as release_lock:
                    with patch.object(self.api_v1_router, "run_proxmox_create", side_effect=fake_create) as mutation:
                        first = asyncio.run(
                            self.api_v1_router.create_vm_draft_proxmox_native(
                                draft_id,
                                self._approved_payload(draft_id, payload),
                            )
                        )
                        second = asyncio.run(
                            self.api_v1_router.create_vm_draft_proxmox_native(
                                draft_id,
                                self._approved_payload(draft_id, payload),
                            )
                        )

        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertEqual(1, mutation.call_count)
        self.assertEqual(1, acquire_lock.call_count)
        self.assertEqual(1, release_lock.call_count)
        self.assertFalse(second["data"]["proxmox_create_ran"])
        self.assertFalse(second["data"]["proxmox_mutation_enabled"])
        self.assertTrue(second["data"]["proxmox_mutation_ran_previously"])
        self.assertTrue(second["data"]["idempotent_replay"])
        self.assertEqual("completed", second["data"]["proxmox_create_status"])
        self.assertEqual([], second["data"]["side_effects"])
        self.assertIn("proxmox_clone_invoked", second["data"]["historical_side_effects"])
        self.assertTrue(second["data"]["idempotency"]["replayed"])
        self.assertTrue(second["data"]["idempotency"]["historical_side_effects"])
        self.assertEqual("job-api-proxmox-create-replay", second["data"]["idempotency"]["request_id"])
        self.assertEqual("completed", second["data"]["vm_create_request"]["status"])
        self.assertEqual("stopped", second["data"]["vm_instance"]["status"])
        self.assertEqual(first["data"]["operation_id"], second["data"]["operation_id"])
        self.assertEqual("succeeded", second["data"]["operation"]["status"])

        from app.operations.facade import get_operation

        detail = get_operation(payload["job_id"])
        self.assertEqual("idempotent_replay_returned", detail["events"][-1]["event_type"])

    def test_proxmox_create_blocks_different_request_when_same_target_is_running(self):
        self._assert_existing_target_status_blocks_new_request(
            existing_status="running",
            expected_code="PROXMOX_CREATE_TARGET_IN_PROGRESS",
        )

    def test_proxmox_create_blocks_different_request_when_same_target_needs_reconciliation(self):
        self._assert_existing_target_status_blocks_new_request(
            existing_status="needs_reconciliation",
            expected_code="PROXMOX_CREATE_RECONCILIATION_REQUIRED",
        )

    def test_proxmox_create_blocks_different_request_when_same_target_apply_failed(self):
        self._assert_existing_target_status_blocks_new_request(
            existing_status="apply_failed",
            expected_code="PROXMOX_CREATE_RECONCILIATION_REQUIRED",
        )

    def test_proxmox_create_blocks_different_request_when_same_target_already_completed(self):
        self._assert_existing_target_status_blocks_new_request(
            existing_status="completed",
            expected_code="PROXMOX_CREATE_TARGET_CONFLICT",
        )

    def test_proxmox_create_rejects_same_job_id_with_different_plan_intent(self):
        draft_id = "draft-api-proxmox-create-idempotency-conflict"
        payload = {
            "operator_id": "api-proxmox-test",
            "job_id": "job-api-proxmox-create-idempotency-conflict",
            "bridge_id": "vmbr0",
            "static_ip": "192.168.2.149",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }
        changed_payload = {**payload, "static_ip": "192.168.2.150"}

        def fake_create(plan, *, run_dir, client):
            return self._successful_create_result(plan, run_dir, fingerprint_seed="4")

        with patch.object(self.api_v1_router, "get_default_proxmox_mutation_client", return_value=object()):
            with patch.object(self.api_v1_router, "acquire_target_operation_lock", return_value={"handle": "lock-1"}, create=True):
                with patch.object(self.api_v1_router, "release_target_operation_lock", create=True):
                    with patch.object(self.api_v1_router, "run_proxmox_create", side_effect=fake_create) as mutation:
                        first = asyncio.run(
                            self.api_v1_router.create_vm_draft_proxmox_native(
                                draft_id,
                                self._approved_payload(draft_id, payload),
                            )
                        )
                        with self.assertRaises(HTTPException) as raised:
                            asyncio.run(
                                self.api_v1_router.create_vm_draft_proxmox_native(
                                    draft_id,
                                    self._approved_payload(draft_id, changed_payload),
                                )
                            )

        self.assertTrue(first["ok"])
        self.assertEqual(1, mutation.call_count)
        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("PROXMOX_CREATE_IDEMPOTENCY_CONFLICT", raised.exception.detail["code"])

    def test_proxmox_create_needs_reconciliation_record_is_not_auto_retried(self):
        draft_id = "draft-api-proxmox-create-no-auto-retry"
        payload = {
            "operator_id": "api-proxmox-test",
            "job_id": "job-api-proxmox-create-no-auto-retry",
            "bridge_id": "vmbr0",
            "static_ip": "192.168.2.151",
            "prefix": 24,
            "gateway": "192.168.2.1",
        }

        def fake_create(plan, *, run_dir, client):
            return {
                "job_id": plan.job_id,
                "manifest_id": plan.manifest_id,
                "vmid": plan.vmid,
                "target_node_id": plan.target_node_id,
                "success": False,
                "status": "needs_reconciliation",
                "message": "clone task state is unknown after UPID acquisition",
                "task": {"upid": "UPID:yoonmanserver2:0001:test", "status": "unknown"},
                "artifacts": [],
                "side_effects": ["proxmox_clone_invoked", "proxmox_task_poll_state_unknown"],
            }

        with patch.object(self.api_v1_router, "get_default_proxmox_mutation_client", return_value=object()):
            with patch.object(self.api_v1_router, "acquire_target_operation_lock", return_value={"handle": "lock-1"}, create=True):
                with patch.object(self.api_v1_router, "release_target_operation_lock", create=True):
                    with patch.object(self.api_v1_router, "run_proxmox_create", side_effect=fake_create) as mutation:
                        with self.assertRaises(HTTPException) as first:
                            asyncio.run(
                                self.api_v1_router.create_vm_draft_proxmox_native(
                                    draft_id,
                                    self._approved_payload(draft_id, payload),
                                )
                            )
                        with self.assertRaises(HTTPException) as second:
                            asyncio.run(
                                self.api_v1_router.create_vm_draft_proxmox_native(
                                    draft_id,
                                    self._approved_payload(draft_id, payload),
                                )
                            )

        self.assertEqual("PROXMOX_CREATE_NEEDS_RECONCILIATION", first.exception.detail["code"])
        self.assertEqual(1, mutation.call_count)
        self.assertEqual(409, second.exception.status_code)
        self.assertEqual("PROXMOX_CREATE_RECONCILIATION_REQUIRED", second.exception.detail["code"])
        self.assertEqual("needs_reconciliation", second.exception.detail["existing_status"])

    def test_proxmox_create_powered_on_post_check_needs_reconciliation_not_applied(self):
        from app.jobs.artifacts import write_json_artifact

        draft_id = "draft-api-proxmox-create-reconcile"
        payload = {
            "operator_id": "api-proxmox-test",
            "job_id": "job-api-proxmox-create-reconcile",
            "bridge_id": "vmbr0",
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
            with patch.object(self.api_v1_router, "acquire_target_operation_lock", return_value={"handle": "reconcile-lock"}, create=True):
                with patch.object(self.api_v1_router, "release_target_operation_lock", create=True) as release_lock:
                    with patch.object(self.api_v1_router, "run_proxmox_create", side_effect=fake_create):
                        with self.assertRaises(HTTPException) as raised:
                            asyncio.run(
                                self.api_v1_router.create_vm_draft_proxmox_native(
                                    draft_id,
                                    {
                                        **approved_payload,
                                        "proxmox_mutation_acknowledged": True,
                                    },
                                )
                            )

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("PROXMOX_CREATE_NEEDS_RECONCILIATION", raised.exception.detail["code"])
        self.assertNotIn("manifest_status", raised.exception.detail)
        self.assertIn("proxmox_preview", raised.exception.detail)
        release_lock.assert_not_called()

    def test_string_false_does_not_acknowledge_yellow_risk(self):
        draft_id = "draft-api-approval-yellow"
        payload = {
            "operator_id": "api-approval-test",
            "job_id": draft_id,
            "bridge_id": "vmbr0",
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

    def test_artifact_records_are_db_backed_for_malicious_job_id(self):
        draft_id = "draft-api-path-containment"
        plan_response = asyncio.run(
            self.api_v1_router.plan_vm_draft(
                draft_id,
                {
                    "operator_id": "api-approval-test",
                    "job_id": "/tmp/gjallar-path-escape",
                    "bridge_id": "vmbr0",
                    "static_ip": "192.168.2.146",
                    "prefix": 24,
                    "gateway": "192.168.2.1",
                },
            )
        )
        for artifact in plan_response["data"]["artifacts"]:
            self.assertTrue(artifact["path"].startswith("db://job-artifacts/"))
            self.assertNotIn("/tmp/", artifact["path"])
            self.assertNotIn("..", artifact["path"])


if __name__ == "__main__":
    unittest.main()
