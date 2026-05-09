"""Shared /api/v1 response envelope helpers.

The MVP API keeps a small, predictable envelope so frontend and artifact
snapshots can rely on one success/error shape while the implementation is
filled in Set by Set.
"""

from __future__ import annotations

from typing import Any


def success_response(data: Any = None, *, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the standard successful /api/v1 response envelope."""
    response: dict[str, Any] = {"ok": True, "data": data if data is not None else {}}
    if meta is not None:
        response["meta"] = meta
    return response


def error_response(code: str, message: str, *, details: Any = None) -> dict[str, Any]:
    """Return the standard error /api/v1 response envelope."""
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"ok": False, "error": error}
