"""Admin-only local user management API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.responses import success_response
from app.auth.dependencies import require_admin
from app.auth.users import (
    DuplicateUserError,
    LastEnabledAdminError,
    UserNotFoundError,
    UserOperationResult,
    UserSummary,
    create_user,
    disable_user,
    get_user_summary,
    list_users,
    reset_password,
    set_user_role,
)

router = APIRouter(prefix="/api/v1/admin", dependencies=[Depends(require_admin)])


def _operator_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
        },
    )


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _user_summary(summary: UserSummary) -> dict[str, Any]:
    return {
        "username": summary.username,
        "role": summary.role,
        "enabled": summary.enabled,
        "created_at": _timestamp(summary.created_at),
        "updated_at": _timestamp(summary.updated_at),
        "last_login_at": _timestamp(summary.last_login_at),
    }


def _required_string(payload: dict[str, Any] | None, key: str, *, strip: bool = True) -> str:
    if not isinstance(payload, dict):
        raise _operator_error(400, "INVALID_ADMIN_USER_REQUEST", "Request body must be a JSON object")
    raw_value = str(payload.get(key) or "")
    value = raw_value.strip() if strip else raw_value
    if not value:
        raise _operator_error(400, "INVALID_ADMIN_USER_REQUEST", f"{key} is required")
    return value


def _summary_for(username: str) -> dict[str, Any]:
    return _user_summary(get_user_summary(username=username))


def _map_user_error(exc: ValueError) -> HTTPException:
    if isinstance(exc, LastEnabledAdminError):
        return _operator_error(409, "LAST_ENABLED_ADMIN", str(exc))
    if isinstance(exc, UserNotFoundError):
        return _operator_error(404, "USER_NOT_FOUND", str(exc))
    if isinstance(exc, DuplicateUserError):
        return _operator_error(409, "USER_ALREADY_EXISTS", str(exc))
    return _operator_error(400, "INVALID_ADMIN_USER_REQUEST", str(exc))


@router.get("/users")
async def admin_list_users() -> dict:
    return success_response([_user_summary(user) for user in list_users()], meta={"mode": "admin_user_management"})


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def admin_create_user(payload: dict | None = None) -> dict:
    username = _required_string(payload, "username")
    password = _required_string(payload, "password", strip=False)
    role = _required_string(payload, "role")
    try:
        create_user(username=username, password=password, role=role)
        user = _summary_for(username)
    except ValueError as exc:
        raise _map_user_error(exc) from exc
    return success_response({"user": user}, meta={"mode": "admin_user_management"})


@router.patch("/users/{username}/role")
async def admin_set_user_role(username: str, payload: dict | None = None) -> dict:
    role = _required_string(payload, "role")
    try:
        set_user_role(username=username, role=role)
        user = _summary_for(username)
    except ValueError as exc:
        raise _map_user_error(exc) from exc
    return success_response({"user": user}, meta={"mode": "admin_user_management"})


@router.post("/users/{username}/disable")
async def admin_disable_user(username: str) -> dict:
    try:
        result = disable_user(username=username)
        user = _summary_for(username)
    except ValueError as exc:
        raise _map_user_error(exc) from exc
    return success_response(
        {
            "user": user,
            "revoked_sessions": result.revoked_sessions,
        },
        meta={"mode": "admin_user_management"},
    )


@router.post("/users/{username}/reset-password")
async def admin_reset_password(username: str, payload: dict | None = None) -> dict:
    password = _required_string(payload, "password", strip=False)
    try:
        result: UserOperationResult = reset_password(username=username, password=password)
        user = _summary_for(username)
    except ValueError as exc:
        raise _map_user_error(exc) from exc
    return success_response(
        {
            "user": user,
            "revoked_sessions": result.revoked_sessions,
        },
        meta={"mode": "admin_user_management"},
    )
