"""RED tests that secrets never serialize into logs/artifacts/API payloads."""

import unittest


class SecretRedactionTests(unittest.TestCase):
    def test_secret_values_are_replaced_with_safe_marker(self):
        try:
            from app.core.redaction import redact_secrets
        except ModuleNotFoundError as exc:
            self.fail(
                "Expected app.core.redaction.redact_secrets before any manifest/API "
                f"serialization can be trusted, but it is missing: {exc}"
            )
        payload = {
            "proxmox_api_token_id": "token-id-should-not-leak",
            "proxmox_api_token_secret": "token-secret-should-not-leak",
            "database_url": "postgresql://user:password-should-not-leak@example.invalid/db",
        }
        serialized = repr(redact_secrets(payload))
        self.assertNotIn("token-id-should-not-leak", serialized)
        self.assertNotIn("token-secret-should-not-leak", serialized)
        self.assertNotIn("password-should-not-leak", serialized)
        self.assertIn("[REDACTED]", serialized)


if __name__ == "__main__":
    unittest.main()
