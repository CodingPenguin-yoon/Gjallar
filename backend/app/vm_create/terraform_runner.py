"""Terraform workspace generation for Create VM plans."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from app.core.redaction import redact_secrets
from app.vm_create.models import TerraformWorkspaceResult, VmCreatePlan


class TerraformRunnerError(RuntimeError):
    """Raised when Terraform workspace generation or planning fails."""

    def __init__(self, message: str, *, results: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.results = list(results or [])


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _terraform_source_dir() -> Path:
    return _repo_root() / "infra" / "terraform"


def _load_project_env() -> None:
    env_path = _repo_root() / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=False)


def _terraform_env() -> dict[str, str]:
    _load_project_env()
    env = dict(os.environ)
    mappings = {
        "TF_VAR_proxmox_api_url": "PROXMOX_API_URL",
        "TF_VAR_proxmox_api_token_id": "PROXMOX_API_TOKEN_ID",
        "TF_VAR_proxmox_api_token_secret": "PROXMOX_API_TOKEN_SECRET",
        "TF_VAR_proxmox_tls_insecure": "PROXMOX_TLS_INSECURE",
    }
    for tf_var, source_var in mappings.items():
        if not str(env.get(tf_var, "")).strip() and str(env.get(source_var, "")).strip():
            env[tf_var] = str(env[source_var])
    return env


def _static_ip_cidr(ip_address: str | None) -> str:
    if not ip_address:
        return ""
    return ip_address if "/" in ip_address else f"{ip_address}/24"


def _default_gateway(ip_address: str | None) -> str:
    if not ip_address:
        return ""
    parts = ip_address.split("/", 1)[0].split(".")
    if len(parts) == 4:
        return ".".join([parts[0], parts[1], parts[2], "1"])
    return ""


def _ssh_public_key() -> str:
    configured = os.getenv("GJALLAR_DEFAULT_SSH_PUBLIC_KEY", "").strip()
    if configured:
        return configured
    key_path = os.getenv("GJALLAR_DEFAULT_SSH_PUBLIC_KEY_FILE", "").strip()
    if key_path:
        path = Path(key_path).expanduser()
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    return ""


def terraform_vars_from_plan(plan: VmCreatePlan) -> dict[str, Any]:
    review = dict(plan.review_confirm)
    template_vmid = review.get("template_vmid")
    template_node = review.get("template_node_id")
    if not template_vmid:
        raise TerraformRunnerError("plan review is missing template_vmid")
    template_id = f"{template_node}/{template_vmid}" if template_node else str(template_vmid)
    ip_address = str(plan.network.get("ip_address") or "")
    memory_mb = int(plan.hardware.get("memory_mb") or 0)
    return {
        "vm_id": int(plan.vmid),
        "vm_name": plan.vm_name,
        "target_node": plan.target_node_id,
        "template_id": template_id,
        "cpu_cores": int(plan.hardware.get("cpu") or 0),
        "memory_gb": max(memory_mb // 1024, 1),
        "disk_size_gb": int(plan.hardware.get("disk_gb") or 0),
        "storage_id": plan.storage_id,
        "network_ids": [plan.network.get("bridge_id") or "vmbr0"],
        "ssh_user": "yoon",
        "ssh_public_key": _ssh_public_key(),
        "vm_ip": _static_ip_cidr(ip_address),
        "vm_gateway": _default_gateway(ip_address),
        "start_on_create": False,
        "on_boot": False,
    }


def build_terraform_workspace(plan: VmCreatePlan, *, workspace_root: str | Path) -> TerraformWorkspaceResult:
    """Create a per-job Terraform workspace without running Terraform."""
    root = Path(workspace_root)
    terraform_dir = root / "terraform"
    source_dir = _terraform_source_dir()
    if not (source_dir / "main.tf").is_file():
        raise TerraformRunnerError(f"Terraform source is missing: {source_dir}")

    terraform_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_dir / "main.tf", terraform_dir / "main.tf")

    state_path = Path(plan.terraform_state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    backend_config = terraform_dir / "backend.hcl"
    backend_config.write_text(f'path = "{state_path}"\n', encoding="utf-8")
    (terraform_dir / "backend.tf").write_text(
        'terraform {\n  backend "local" {}\n}\n',
        encoding="utf-8",
    )

    tfvars_path = terraform_dir / "terraform.auto.tfvars.json"
    tfvars = redact_secrets(terraform_vars_from_plan(plan))
    tfvars_path.write_text(json.dumps(tfvars, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    plan_path = terraform_dir / "tfplan"
    return TerraformWorkspaceResult(
        job_id=plan.job_id,
        manifest_id=plan.manifest_id,
        workspace_dir=str(root),
        terraform_dir=str(terraform_dir),
        backend_config_path=str(backend_config),
        tfvars_path=str(tfvars_path),
        plan_path=str(plan_path),
        state_path=str(state_path),
        side_effects=["terraform_workspace_created"],
    )


def terraform_plan_commands(workspace: TerraformWorkspaceResult) -> list[list[str]]:
    return [
        ["terraform", "init", "-input=false", f"-backend-config={Path(workspace.backend_config_path).name}"],
        [
            "terraform",
            "plan",
            "-input=false",
            f"-out={Path(workspace.plan_path).name}",
            f"-var-file={Path(workspace.tfvars_path).name}",
        ],
    ]


def terraform_apply_commands(workspace: TerraformWorkspaceResult) -> list[list[str]]:
    return [
        ["terraform", "apply", "-input=false", "-auto-approve", Path(workspace.plan_path).name],
    ]


def run_terraform_plan(
    workspace: TerraformWorkspaceResult,
    *,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[dict[str, Any]]:
    """Run terraform init/plan in the generated workspace.

    Callers must gate this behind approval because Terraform reads the live
    provider and may contact Proxmox. It should still not create or modify VMs.
    """
    results: list[dict[str, Any]] = []
    terraform_dir = Path(workspace.terraform_dir)
    for command in terraform_plan_commands(workspace):
        completed = command_runner(
            command,
            cwd=str(terraform_dir),
            check=False,
            capture_output=True,
            text=True,
            env=_terraform_env(),
        )
        results.append(
            {
                "command": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        )
        if completed.returncode != 0:
            raise TerraformRunnerError(f"Terraform command failed: {' '.join(command)}", results=results)
    return results


def run_terraform_apply(
    workspace: TerraformWorkspaceResult,
    *,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[dict[str, Any]]:
    """Run terraform apply against a previously generated tfplan file.

    Callers must gate this behind explicit operator approval because it creates
    or changes Proxmox resources.
    """
    plan_path = Path(workspace.plan_path)
    if not plan_path.is_file():
        raise TerraformRunnerError("Terraform plan file is missing; run Terraform 검토 실행 first")

    results: list[dict[str, Any]] = []
    terraform_dir = Path(workspace.terraform_dir)
    for command in terraform_apply_commands(workspace):
        completed = command_runner(
            command,
            cwd=str(terraform_dir),
            check=False,
            capture_output=True,
            text=True,
            env=_terraform_env(),
        )
        results.append(
            {
                "command": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        )
        if completed.returncode != 0:
            raise TerraformRunnerError(f"Terraform command failed: {' '.join(command)}", results=results)
    return results
