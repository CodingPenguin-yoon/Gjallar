"""RED tests for real, checksum-backed, secret-safe Set 4 artifacts."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path


class ArtifactStoreContractTests(unittest.TestCase):
    def test_json_artifact_is_real_file_with_sha256_and_redacted_payload(self):
        try:
            from app.jobs.artifacts import write_json_artifact
        except ModuleNotFoundError as exc:
            self.fail(
                "Expected app.jobs.artifacts.write_json_artifact to write real "
                f"secret-safe artifact files with SHA-256 checksums: {exc}"
            )

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

            artifact_path = Path(record.path)
            self.assertTrue(artifact_path.is_file(), "artifact path must point to a real file")
            self.assertTrue(
                artifact_path.resolve().is_relative_to(Path(tmp).resolve()),
                "Set 4 tests must write only inside the caller-provided temp run directory",
            )
            raw_bytes = artifact_path.read_bytes()
            expected_checksum = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
            self.assertEqual(expected_checksum, record.checksum)

            text = raw_bytes.decode("utf-8")
            self.assertNotIn(raw_secret, text)
            self.assertNotIn("pass@example.invalid", text)
            self.assertIn("[REDACTED]", text)
            stored = json.loads(text)
            self.assertEqual("gjallar-vm-20260509-set4", stored["vm_name"])

    def test_text_artifact_uses_real_checksum_and_does_not_create_fake_only_records(self):
        try:
            from app.jobs.artifacts import write_text_artifact
        except ModuleNotFoundError as exc:
            self.fail(
                "Expected app.jobs.artifacts.write_text_artifact so planned_git_diff "
                f"records point at real files, not fake IDs only: {exc}"
            )

        with tempfile.TemporaryDirectory() as tmp:
            record = write_text_artifact(
                run_dir=Path(tmp),
                job_id="job_set4_001",
                artifact_type="planned_git_diff",
                filename="planned_git_diff.txt",
                text="diff --git a/manifests/vms/example.yaml b/manifests/vms/example.yaml\n",
            )
            artifact_path = Path(record.path)
            self.assertTrue(artifact_path.is_file())
            self.assertEqual(
                "sha256:" + hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                record.checksum,
            )
            self.assertEqual("planned_git_diff", record.type)

    def test_yaml_artifact_redacts_structured_secrets_without_redacting_password_login_flag(self):
        from app.jobs.artifacts import write_yaml_artifact

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

            text = Path(record.path).read_text()

        self.assertIn("password_login: disabled", text)
        self.assertNotIn("raw-token-secret", text)
        self.assertIn("[REDACTED]", text)


if __name__ == "__main__":
    unittest.main()
