"""Public errors for Guided `qm` application flows."""

from __future__ import annotations

from typing import Any


class GuidedQmError(RuntimeError):
    """A conservative, API-safe Guided `qm` failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = {
            "execution_mode": "guided_manual",
            "backend_command_execution": False,
            "proxmox_mutation_enabled": False,
            "side_effects": [],
            **dict(details or {}),
        }

    def to_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.details}
