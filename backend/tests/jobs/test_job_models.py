"""RED tests for the PRD Set 4 job/approval/artifact record substrate."""

import unittest


class JobModelContractTests(unittest.TestCase):
    def test_job_artifact_and_approval_records_expose_prd_fields(self):
        try:
            from app.jobs.models import ApprovalRecord, ArtifactRecord, JobRecord
        except ModuleNotFoundError as exc:
            self.fail(
                "Expected app.jobs.models to define the minimum PRD job, "
                f"artifact, and approval records before preflight/plan work: {exc}"
            )

        started_at = "2026-05-09T02:12:00+09:00"
        job = JobRecord(
            job_id="job_set4_001",
            job_type="vm_create",
            status="planned",
            target_id="gjallar-vm-20260509-set4",
            risk_level="yellow",
            started_at=started_at,
            finished_at=None,
        )
        artifact = ArtifactRecord(
            artifact_id="artifact_plan_job_set4_001",
            job_id=job.job_id,
            type="plan",
            path="/tmp/gjallar-set4/job_set4_001/plan.json",
            checksum="sha256:" + "a" * 64,
            created_at=started_at,
        )
        approval = ApprovalRecord(
            job_id=job.job_id,
            plan_artifact_id=artifact.artifact_id,
            review_summary_checksum=artifact.checksum,
            yellow_risk_acknowledged=False,
            decision="pending",
        )

        self.assertEqual(
            {
                "job_id",
                "job_type",
                "status",
                "target_id",
                "risk_level",
                "started_at",
                "finished_at",
            },
            set(job.to_dict()),
        )
        self.assertEqual("artifact_plan_job_set4_001", artifact.to_dict()["artifact_id"])
        self.assertEqual("sha256:" + "a" * 64, artifact.to_dict()["checksum"])
        self.assertEqual(artifact.artifact_id, approval.to_dict()["plan_artifact_id"])
        self.assertEqual(artifact.checksum, approval.to_dict()["review_summary_checksum"])


if __name__ == "__main__":
    unittest.main()
