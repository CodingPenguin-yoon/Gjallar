"""Path resolution helpers for Create VM IaC and Terraform state roots."""

from __future__ import annotations

import os
from pathlib import Path


DEFAULT_SHARED_ROOT = Path("/mnt/hermes_data")
DEFAULT_IAC_ROOT = DEFAULT_SHARED_ROOT / "IaC"
DEFAULT_TF_STATE_ROOT = DEFAULT_SHARED_ROOT / "IaC-state" / "gjallar"


def _configured_path(*names: str) -> Path | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            expanded = os.path.expandvars(os.path.expanduser(value.strip()))
            return Path(expanded)
    return None


def shared_root() -> Path:
    return _configured_path("GJALLAR_SHARED_ROOT", "HERMES_DATA_ROOT") or DEFAULT_SHARED_ROOT


def iac_root() -> Path:
    return _configured_path("GJALLAR_IAC_ROOT") or shared_root() / "IaC"


def terraform_state_root() -> Path:
    explicit = _configured_path("GJALLAR_TF_STATE_ROOT", "GJALLAR_TERRAFORM_STATE_ROOT")
    if explicit is not None:
        return explicit
    if _configured_path("GJALLAR_IAC_ROOT") is not None:
        return iac_root().parent / "IaC-state" / "gjallar"
    return shared_root() / "IaC-state" / "gjallar"


def terraform_state_path(manifest_id: str) -> str:
    return str(terraform_state_root() / manifest_id / "terraform.tfstate")


def iac_path_context() -> dict[str, str]:
    return {
        "shared_root": str(shared_root()),
        "iac_root": str(iac_root()),
        "terraform_state_root": str(terraform_state_root()),
    }
