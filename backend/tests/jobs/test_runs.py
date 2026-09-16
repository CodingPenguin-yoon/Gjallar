"""Tests for DB-backed job run status resilience."""

import unittest
from unittest.mock import patch


class JobRunsTests(unittest.TestCase):
    def test_record_job_run_in_session_rolls_back_job_and_status_artifact_together(self):
        from app.db.models import JobArtifactRecord, JobRunRecord
        from app.db.session import get_session_factory, session_scope
        from app.jobs import runs as runs_module

        job_id = "job-session-rollback"
        session = get_session_factory()()
        try:
            result = runs_module.record_job_run_in_session(
                session,
                job_id=job_id,
                job_type="vm_start",
                status="completed",
                target_id="node-a:306",
                risk_level="unknown",
                stage="post_check",
                step_status="completed",
                message="observed running",
            )

            self.assertEqual(1, result["artifact_count"])
            self.assertIsNotNone(session.get(JobRunRecord, job_id))
            self.assertIsNotNone(
                session.get(JobArtifactRecord, result["artifacts"][0]["artifact_id"])
            )
            session.rollback()
        finally:
            session.close()

        with session_scope() as verification_session:
            self.assertIsNone(verification_session.get(JobRunRecord, job_id))
            self.assertEqual(
                [],
                verification_session.query(JobArtifactRecord)
                .filter(JobArtifactRecord.job_id == job_id)
                .all(),
            )

    def test_record_job_run_rolls_back_new_job_when_status_artifact_owner_collides(self):
        from app.db.models import JobRunRecord
        from app.db.session import session_scope
        from app.jobs import runs as runs_module
        from app.jobs.artifacts import get_artifact_record, write_json_artifact

        first_job_id = "z" * 120 + "-first"
        colliding_job_id = "z" * 120 + "-second"
        existing = write_json_artifact(
            run_dir=runs_module.run_dir(first_job_id),
            job_id=first_job_id,
            artifact_type="job_status",
            filename="job_status.json",
            payload={"owner": "first"},
        )

        with self.assertRaisesRegex(ValueError, "different job"):
            runs_module.record_job_run(
                job_id=colliding_job_id,
                job_type="vm_start",
                status="completed",
                target_id="node-a:306",
                risk_level="unknown",
                stage="post_check",
                step_status="completed",
                message="must roll back",
            )

        with session_scope() as session:
            self.assertIsNone(session.get(JobRunRecord, colliding_job_id))
        retained = get_artifact_record(existing.artifact_id)
        self.assertIsNotNone(retained)
        self.assertEqual(first_job_id, retained.job_id)

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
