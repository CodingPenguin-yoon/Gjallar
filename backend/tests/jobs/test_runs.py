"""Tests for DB-backed job run status resilience."""

import unittest
from unittest.mock import patch


class JobRunsTests(unittest.TestCase):
    def test_strict_list_job_runs_preserves_db_unavailability(self):
        from app.jobs import runs as runs_module

        def unavailable_session():
            raise RuntimeError("database is unavailable")

        with patch.object(runs_module, "session_scope", side_effect=unavailable_session):
            with self.assertRaisesRegex(RuntimeError, "database is unavailable"):
                runs_module.list_job_runs_strict()

    def test_list_job_runs_fails_open_when_db_is_unavailable(self):
        from app.jobs import runs as runs_module

        def unavailable_session():
            raise RuntimeError("database is unavailable")

        with patch.object(runs_module, "session_scope", side_effect=unavailable_session):
            self.assertEqual([], runs_module.list_job_runs())

    def test_strict_get_job_run_preserves_db_unavailability(self):
        from app.jobs import runs as runs_module

        def unavailable_session():
            raise RuntimeError("database is unavailable")

        with patch.object(runs_module, "session_scope", side_effect=unavailable_session):
            with self.assertRaisesRegex(RuntimeError, "database is unavailable"):
                runs_module.get_job_run_strict("job-unavailable")

    def test_vm_create_steps_keep_existing_defaults(self):
        from app.jobs import runs as runs_module

        run = runs_module.record_job_run(
            job_id="job-create-steps",
            job_type="vm_create",
            status="running",
            target_id="node-a:vm-a",
            risk_level="green",
            stage="preflight",
            step_status="completed",
            message="preflight complete",
        )

        self.assertEqual(
            ["draft", "preflight", "plan", "approval", "create"],
            [step["id"] for step in run["steps"]],
        )
        self.assertEqual("사전 검토", run["steps"][1]["label"])

    def test_vm_start_steps_use_start_specific_labels(self):
        from app.jobs import runs as runs_module

        run = runs_module.record_job_run(
            job_id="job-start-steps",
            job_type="vm_start",
            status="running",
            target_id="node-a:306",
            risk_level="unknown",
            stage="task_poll",
            step_status="running",
            message="polling start task",
        )

        self.assertEqual(["precheck", "start", "task_poll", "post_check"], [step["id"] for step in run["steps"]])
        self.assertEqual(["시작 사전 확인", "VM 시작 요청", "Proxmox 작업 확인", "시작 후 확인"], [step["label"] for step in run["steps"]])
        self.assertEqual(["completed", "completed", "running", "pending"], [step["status"] for step in run["steps"]])

    def test_vm_shutdown_steps_use_shutdown_specific_labels(self):
        from app.jobs import runs as runs_module

        run = runs_module.record_job_run(
            job_id="job-shutdown-steps",
            job_type="vm_shutdown",
            status="running",
            target_id="node-a:306",
            risk_level="unknown",
            stage="task_poll",
            step_status="running",
            message="polling shutdown task",
        )

        self.assertEqual(
            ["precheck", "shutdown", "task_poll", "post_check"],
            [step["id"] for step in run["steps"]],
        )
        self.assertEqual(
            ["종료 사전 확인", "VM 종료 요청", "Proxmox 작업 확인", "종료 후 확인"],
            [step["label"] for step in run["steps"]],
        )
        self.assertEqual(
            ["completed", "completed", "running", "pending"],
            [step["status"] for step in run["steps"]],
        )

    def test_drs_migration_steps_are_execution_specific_and_not_vm_create_labels(self):
        from app.jobs import runs as runs_module

        run = runs_module.record_job_run(
            job_id="job-drs-steps",
            job_type="drs_migration",
            status="pending",
            target_id="node-a->node-b:101",
            risk_level="yellow",
            stage="job_intent",
            step_status="pending",
            message="local DRS intent only",
        )

        self.assertEqual(
            [
                "recommendation",
                "final_precheck",
                "approval",
                "job_intent",
                "operation_lock",
                "migration",
                "task_poll",
                "post_check",
                "reconciliation",
            ],
            [step["id"] for step in run["steps"]],
        )
        self.assertEqual(
            [
                "DRS 추천 확인",
                "최종 사전 확인",
                "DRS 승인 패킷",
                "로컬 작업 의도",
                "DRS 작업 잠금",
                "Proxmox 마이그레이션 요청",
                "Proxmox 작업 확인",
                "마이그레이션 후 확인",
                "조정 필요",
            ],
            [step["label"] for step in run["steps"]],
        )
        self.assertNotIn("draft", [step["id"] for step in run["steps"]])
        self.assertNotIn("create", [step["id"] for step in run["steps"]])
        self.assertIn("post_check", [step["id"] for step in run["steps"]])

    def test_post_create_readiness_steps_are_local_evidence_specific(self):
        from app.jobs import runs as runs_module

        run = runs_module.record_job_run(
            job_id="job-post-create-readiness-steps",
            job_type="post_create_readiness",
            status="completed",
            target_id="node-a:306",
            risk_level="unknown",
            stage="evidence_record",
            step_status="completed",
            message="local readiness evidence recorded",
        )

        self.assertEqual(["request", "validation", "evidence_record"], [step["id"] for step in run["steps"]])
        self.assertEqual(["증거 요청", "입력 검증", "증거 기록"], [step["label"] for step in run["steps"]])
        self.assertEqual(["completed", "completed", "completed"], [step["status"] for step in run["steps"]])
        self.assertNotIn("draft", [step["id"] for step in run["steps"]])
        self.assertNotIn("create", [step["id"] for step in run["steps"]])


if __name__ == "__main__":
    unittest.main()
