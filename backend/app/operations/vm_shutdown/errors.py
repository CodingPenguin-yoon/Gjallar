"""Application errors exposed by the VM Shutdown compatibility facade."""

from __future__ import annotations

from typing import Any


class VmShutdownError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 409, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = dict(details or {})

    def to_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.details}
