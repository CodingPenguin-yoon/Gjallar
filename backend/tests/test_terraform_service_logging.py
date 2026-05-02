import contextlib
import io
import os
import unittest
from unittest.mock import patch

from app.integrations.terraform import TerraformService


class TerraformServiceLoggingTest(unittest.TestCase):
    def test_init_does_not_print_raw_proxmox_credentials(self):
        env = {
            "PROXMOX_API_URL": "https://sensitive-proxmox.example:8006/api2/json",
            "PROXMOX_API_TOKEN_ID": "root@pam!sensitive-token-id",
            "PROXMOX_API_TOKEN_SECRET": "super-secret-token-value",
            "TF_VAR_proxmox_api_url": "",
            "TF_VAR_proxmox_api_token_id": "",
            "TF_VAR_proxmox_api_token_secret": "",
        }
        clean_env = {key: value for key, value in os.environ.items() if not key.startswith("TF_VAR_proxmox_")}
        clean_env.update(env)

        output = io.StringIO()
        with patch.dict(os.environ, clean_env, clear=True):
            with contextlib.redirect_stdout(output):
                TerraformService(terraform_dir="/tmp/gjallar-terraform-test")

        rendered = output.getvalue()
        self.assertNotIn("sensitive-proxmox.example", rendered)
        self.assertNotIn("sensitive-token-id", rendered)
        self.assertNotIn("super-secret-token-value", rendered)
        self.assertIn("[REDACTED]", rendered)


if __name__ == "__main__":
    unittest.main()
