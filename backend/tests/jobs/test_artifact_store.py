"""Tests for DB-backed, checksum-backed, secret-safe artifacts."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path


class ArtifactStoreContractTests(unittest.TestCase):
    def test_in_session_json_writer_uses_caller_transaction_and_exact_owner_guard(self):
        from app.db.session import get_session_factory
        from app.db.models import JobArtifactRecord
        from app.jobs.artifacts import (
            get_artifact_record,
            get_artifact_record_in_session,
            read_artifact_text_in_session,
            write_json_artifact_in_session,
        )

        session = get_session_factory()()
        try:
            record = write_json_artifact_in_session(
                session,
                run_dir=Path(tempfile.gettempdir()),
                job_id="job-session-artifact",
                artifact_type="evidence",
                filename="evidence.json",
                payload={"result": "observed"},
            )

            retained = get_artifact_record_in_session(
                session,
                record.artifact_id,
                expected_job_id="job-session-artifact",
                expected_artifact_type="evidence",
            )
            self.assertEqual(record, retained)
            self.assertEqual(
                {"result": "observed"},
                json.loads(
                    read_artifact_text_in_session(
                        session,
                        record,
                        expected_job_id="job-session-artifact",
                        expected_artifact_type="evidence",
                        expected_checksum=record.checksum,
                    )
                ),
            )
            with self.assertRaisesRegex(ValueError, "checksum"):
                read_artifact_text_in_session(
                    session,
                    record,
                    expected_job_id="job-session-artifact",
                    expected_artifact_type="evidence",
                    expected_checksum="sha256:" + "0" * 64,
                )
            row = session.get(JobArtifactRecord, record.artifact_id)
            row.content_text = '{"result":"tampered"}\n'
            session.flush()
            with self.assertRaisesRegex(ValueError, "content checksum"):
                read_artifact_text_in_session(
                    session,
                    record,
                    expected_job_id="job-session-artifact",
                    expected_artifact_type="evidence",
                    expected_checksum=record.checksum,
                )
            with self.assertRaisesRegex(ValueError, "different job"):
                get_artifact_record_in_session(
                    session,
                    record.artifact_id,
                    expected_job_id="another-job",
                    expected_artifact_type="evidence",
                )
            session.rollback()
        finally:
            session.close()

        self.assertIsNone(get_artifact_record(record.artifact_id))

    def test_json_artifact_is_db_backed_with_sha256_and_redacted_payload(self):
        from app.jobs.artifacts import read_artifact_text, write_json_artifact

        with tempfile.TemporaryDirectory() as tmp:
            raw_secret = "raw-token-value-should-not-be-persisted"
            record = write_json_artifact(
                run_dir=Path(tmp),
                job_id="job_set4_001",
                artifact_type="plan",
                filename="plan.json",
                payload={
                    "vm_name": "gjallar-vm-20260509-set4",
                    "proxmox_api_token_secret": raw_secret,
                    "nested": {"connection_string": "postgresql://user:pass@example.invalid/db"},
                },
            )

            self.assertTrue(record.path.startswith("db://job-artifacts/"))
            self.assertEqual("db", record.storage_backend)
            raw_bytes = read_artifact_text(record).encode("utf-8")
            expected_checksum = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
            self.assertEqual(expected_checksum, record.checksum)

            text = raw_bytes.decode("utf-8")
            self.assertNotIn(raw_secret, text)
            self.assertNotIn("pass@example.invalid", text)
            self.assertIn("[REDACTED]", text)
            stored = json.loads(text)
            self.assertEqual("gjallar-vm-20260509-set4", stored["vm_name"])

    def test_text_artifact_uses_real_checksum_and_db_reference(self):
        from app.jobs.artifacts import read_artifact_text, write_text_artifact

        with tempfile.TemporaryDirectory() as tmp:
            record = write_text_artifact(
                run_dir=Path(tmp),
                job_id="job_set4_001",
                artifact_type="planned_git_diff",
                filename="planned_git_diff.txt",
                text="diff --git a/manifests/vms/example.yaml b/manifests/vms/example.yaml\n",
            )
            self.assertEqual(
                "sha256:" + hashlib.sha256(read_artifact_text(record).encode("utf-8")).hexdigest(),
                record.checksum,
            )
            self.assertEqual("planned_git_diff", record.type)
            self.assertTrue(record.path.startswith("db://job-artifacts/"))

    def test_yaml_artifact_redacts_structured_secrets_without_redacting_password_login_flag(self):
        from app.jobs.artifacts import read_artifact_text, write_yaml_artifact

        with tempfile.TemporaryDirectory() as tmp:
            record = write_yaml_artifact(
                run_dir=Path(tmp),
                job_id="job_set4_yaml",
                artifact_type="vm_instance_manifest",
                filename="vm_instance_manifest.yaml",
                payload={
                    "access": {
                        "password_login": "disabled",
                        "proxmox_api_token_secret": "raw-token-secret",
                    }
                },
            )

            text = read_artifact_text(record)

        self.assertIn("password_login: disabled", text)
        self.assertNotIn("raw-token-secret", text)
        self.assertIn("[REDACTED]", text)

    def test_artifact_id_collision_cannot_reassign_an_existing_artifact(self):
        from app.jobs.artifacts import get_artifact_record, read_artifact_text, write_json_artifact

        first_job_id = "a" * 120 + "-first"
        colliding_job_id = "a" * 120 + "-second"
        first = write_json_artifact(
            run_dir=Path(tempfile.gettempdir()),
            job_id=first_job_id,
            artifact_type="observed_after",
            filename="observed_after.json",
            payload={"owner": "first"},
        )

        with self.assertRaisesRegex(ValueError, "different job"):
            write_json_artifact(
                run_dir=Path(tempfile.gettempdir()),
                job_id=colliding_job_id,
                artifact_type="observed_after",
                filename="observed_after.json",
                payload={"owner": "second"},
            )

        retained = get_artifact_record(first.artifact_id)
        self.assertIsNotNone(retained)
        self.assertEqual(first_job_id, retained.job_id)
        self.assertEqual({"owner": "first"}, json.loads(read_artifact_text(retained)))


if __name__ == "__main__":
    unittest.main()
