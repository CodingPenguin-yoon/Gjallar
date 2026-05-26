"""FastAPI dependencies for Gjallar session authorization."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, Request

from app.auth.roles import AuthenticatedUser, role_at_least
from app.auth.sessions import actor_from_request


def _auth_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
        },
    )


async def optional_user(request: Request) -> AuthenticatedUser | None:
    return actor_from_request(request)


async def require_user(request: Request) -> AuthenticatedUser:
    actor = actor_from_request(request)
    if actor is None:
        raise _auth_error(401, "AUTH_REQUIRED", "A valid Gjallar login session is required")
    return actor


def require_role(required_role: str) -> Callable[[Request], AuthenticatedUser]:
    async def dependency(request: Request) -> AuthenticatedUser:
        actor = await require_user(request)
        if not role_at_least(actor.role, required_role):
            raise _auth_error(403, "AUTH_FORBIDDEN", f"Role {required_role} or higher is required")
        return actor

    return dependency


require_viewer = require_role("viewer")
require_operator = require_role("operator")
require_admin = require_role("admin")
