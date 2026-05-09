import tempfile
import unittest
from pathlib import Path

from app.domains.deploy.readiness import ProvisioningReadinessService
from app.main import app


class ProvisioningReadinessServiceTest(unittest.TestCase):
    def test_ready_when_runtime_files_and_required_env_are_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            terraform_dir = root / "infra" / "terraform"
            ansible_dir = root / "infra" / "ansible"
            terraform_dir.mkdir(parents=True)
            ansible_dir.mkdir(parents=True)
            (terraform_dir / "main.tf").write_text("terraform {}\n")
            (ansible_dir / "playbook.yml").write_text("---\n- hosts: all\n")

            env = {
                "PROXMOX_API_URL": "https://proxmox.example:8006/api2/json",
                "PROXMOX_API_TOKEN_ID": "root@pam!token",
                "PROXMOX_API_TOKEN_SECRET": "super-secret-token",
            }

            service = ProvisioningReadinessService(
                terraform_dir=terraform_dir,
                ansible_dir=ansible_dir,
                env=env,
                executable_resolver=lambda name: f"/usr/bin/{name}",
                version_runner=lambda command: "Terraform v1.15.1" if command[0] == "terraform" else "ansible-playbook 2.10.8",
            )

            result = service.check()

            self.assertEqual(result["status"], "ready")
            self.assertTrue(all(check["status"] == "ok" for check in result["checks"]))
            rendered = repr(result)
            self.assertNotIn("super-secret-token", rendered)
            self.assertNotIn("root@pam!token", rendered)
            self.assertNotIn("proxmox.example", rendered)

    def test_error_when_required_runtime_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = ProvisioningReadinessService(
                terraform_dir=root / "missing-terraform",
                ansible_dir=root / "missing-ansible",
                env={},
                executable_resolver=lambda name: None,
                version_runner=lambda command: "",
            )

            result = service.check()

            self.assertEqual(result["status"], "error")
            check_map = {check["id"]: check for check in result["checks"]}
            self.assertEqual(check_map["terraform_cli"]["status"], "error")
            self.assertEqual(check_map["ansible_playbook_cli"]["status"], "error")
            self.assertEqual(check_map["terraform_config"]["status"], "error")
            self.assertEqual(check_map["ansible_playbook"]["status"], "error")
            self.assertEqual(check_map["proxmox_api_config"]["status"], "error")
            self.assertGreaterEqual(len(result["next_actions"]), 3)


class ProvisioningReadinessRouteTest(unittest.TestCase):
    def test_readiness_route_is_registered_under_api(self):
        routes = {
            (route.path, tuple(sorted(getattr(route, "methods", []))))
            for route in app.routes
        }
        self.assertIn(("/api/provision/readiness", ("GET",)), routes)


if __name__ == "__main__":
    unittest.main()
