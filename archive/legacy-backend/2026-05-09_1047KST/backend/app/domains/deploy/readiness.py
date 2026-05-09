"""Provisioning runtime readiness checks for Gjallar VM creation."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Mapping, Optional

Check = dict[str, object]


class ProvisioningReadinessService:
    """Builds a safe, non-secret readiness summary for VM provisioning."""

    def __init__(
        self,
        terraform_dir: Optional[Path] = None,
        ansible_dir: Optional[Path] = None,
        env: Optional[Mapping[str, str]] = None,
        executable_resolver: Optional[Callable[[str], Optional[str]]] = None,
        version_runner: Optional[Callable[[list[str]], str]] = None,
    ) -> None:
        repo_root = Path(__file__).resolve().parents[4]
        self.terraform_dir = Path(terraform_dir) if terraform_dir else repo_root / "infra" / "terraform"
        self.ansible_dir = Path(ansible_dir) if ansible_dir else repo_root / "infra" / "ansible"
        self.env = env if env is not None else os.environ
        self.executable_resolver = executable_resolver or shutil.which
        self.version_runner = version_runner or self._run_version_command

    def check(self) -> dict[str, object]:
        checks = [
            self._check_executable(
                check_id="terraform_cli",
                label="Terraform CLI",
                executable="terraform",
                version_command=["terraform", "version"],
                missing_action="Install Terraform on the backend host and ensure it is on PATH.",
            ),
            self._check_executable(
                check_id="ansible_playbook_cli",
                label="Ansible Playbook CLI",
                executable="ansible-playbook",
                version_command=["ansible-playbook", "--version"],
                missing_action="Install Ansible/ansible-playbook on the backend host and ensure it is on PATH.",
            ),
            self._check_file(
                check_id="terraform_config",
                label="Terraform config",
                path=self.terraform_dir / "main.tf",
                missing_action="Restore infra/terraform/main.tf before VM provisioning.",
            ),
            self._check_file(
                check_id="ansible_playbook",
                label="Ansible playbook",
                path=self.ansible_dir / "playbook.yml",
                missing_action="Restore infra/ansible/playbook.yml before bootstrap provisioning.",
            ),
            self._check_proxmox_env(),
        ]

        checks.append(self._check_terraform_validate(checks))

        status = self._overall_status(checks)
        next_actions = [
            str(check["next_action"])
            for check in checks
            if check.get("status") in {"error", "warning"} and check.get("next_action")
        ]

        return {
            "status": status,
            "summary": self._summary_for_status(status),
            "checks": [self._public_check(check) for check in checks],
            "next_actions": next_actions,
        }

    def _check_executable(
        self,
        check_id: str,
        label: str,
        executable: str,
        version_command: list[str],
        missing_action: str,
    ) -> Check:
        path = self.executable_resolver(executable)
        if not path:
            return {
                "id": check_id,
                "label": label,
                "status": "error",
                "message": f"{executable} executable was not found on PATH.",
                "next_action": missing_action,
            }

        version = self.version_runner(version_command).splitlines()[0:1]
        return {
            "id": check_id,
            "label": label,
            "status": "ok",
            "message": f"{executable} executable found.",
            "detail": version[0] if version else "version detected",
        }

    def _check_file(self, check_id: str, label: str, path: Path, missing_action: str) -> Check:
        if path.exists():
            return {
                "id": check_id,
                "label": label,
                "status": "ok",
                "message": f"{path.name} exists.",
                "detail": str(path),
            }
        return {
            "id": check_id,
            "label": label,
            "status": "error",
            "message": f"Required file is missing: {path}",
            "next_action": missing_action,
        }

    def _check_proxmox_env(self) -> Check:
        required_keys = [
            "PROXMOX_API_URL",
            "PROXMOX_API_TOKEN_ID",
            "PROXMOX_API_TOKEN_SECRET",
        ]
        missing = [key for key in required_keys if not self.env.get(key)]
        if missing:
            return {
                "id": "proxmox_api_config",
                "label": "Proxmox API config",
                "status": "error",
                "message": f"Missing required Proxmox environment keys: {', '.join(missing)}",
                "detail": "Values are intentionally hidden.",
                "next_action": "Set Proxmox API URL/token env values in the backend .env, then restart the backend.",
            }
        return {
            "id": "proxmox_api_config",
            "label": "Proxmox API config",
            "status": "ok",
            "message": "Required Proxmox API environment keys are configured.",
            "detail": "Values are intentionally hidden.",
        }

    def _check_terraform_validate(self, checks: list[Check]) -> Check:
        check_map = {str(check["id"]): check for check in checks}
        if check_map.get("terraform_cli", {}).get("status") != "ok":
            return {
                "id": "terraform_validate",
                "label": "Terraform validate",
                "status": "warning",
                "message": "Skipped because Terraform CLI is not available.",
                "next_action": "Install Terraform, then run terraform init/validate again.",
            }
        if check_map.get("terraform_config", {}).get("status") != "ok":
            return {
                "id": "terraform_validate",
                "label": "Terraform validate",
                "status": "warning",
                "message": "Skipped because Terraform config is missing.",
                "next_action": "Restore Terraform config, then run terraform validate.",
            }

        output = self.version_runner([
            "terraform",
            f"-chdir={self.terraform_dir}",
            "validate",
            "-no-color",
        ])
        if output.startswith("ERROR:"):
            return {
                "id": "terraform_validate",
                "label": "Terraform validate",
                "status": "warning",
                "message": "Terraform validate did not pass.",
                "detail": output[:500],
                "next_action": "Run terraform -chdir=infra/terraform init -input=false && terraform -chdir=infra/terraform validate.",
            }
        return {
            "id": "terraform_validate",
            "label": "Terraform validate",
            "status": "ok",
            "message": "Terraform configuration validates successfully.",
        }

    @staticmethod
    def _overall_status(checks: list[Check]) -> str:
        statuses = {check.get("status") for check in checks}
        if "error" in statuses:
            return "error"
        if "warning" in statuses:
            return "warning"
        return "ready"

    @staticmethod
    def _summary_for_status(status: str) -> str:
        if status == "ready":
            return "Provisioning runtime is ready."
        if status == "warning":
            return "Provisioning runtime is usable but needs attention."
        return "Provisioning runtime has blocking issues."

    @staticmethod
    def _public_check(check: Check) -> dict[str, object]:
        allowed = {"id", "label", "status", "message", "detail"}
        return {key: value for key, value in check.items() if key in allowed}

    @staticmethod
    def _run_version_command(command: list[str]) -> str:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except Exception as exc:  # pragma: no cover - defensive subprocess guard
            return f"ERROR: {exc}"

        output = (result.stdout or result.stderr or "").strip()
        if result.returncode != 0:
            return f"ERROR: {output or 'command failed'}"
        return output


__all__ = ["ProvisioningReadinessService"]
