"""Path resolution helpers for Create VM IaC roots."""

from __future__ import annotations

import os
from pathlib import Path


DEFAULT_SHARED_ROOT = Path("/mnt/hermes_data")
DEFAULT_IAC_ROOT = DEFAULT_SHARED_ROOT / "IaC"


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


def iac_path_context() -> dict[str, str]:
    return {
        "shared_root": str(shared_root()),
        "iac_root": str(iac_root()),
    }
