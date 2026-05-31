"""Admin-only local user management API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.v1.responses import success_response
from app.auth.audit import audit_response_fields, record_account_audit_event
from app.auth.dependencies import require_admin
from app.auth.roles import AuthenticatedUser, InvalidRoleError
from app.auth.sessions import (
    SessionNotFoundError,
    clear_session_cookie,
    current_session_id_from_request,
    list_session_inventory,
    revoke_session_by_id,
)
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

router = APIRouter(prefix="/api/v1/admin")


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
        "user_id": summary.user_id,
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
    if isinstance(exc, InvalidRoleError):
        return _operator_error(400, "INVALID_ADMIN_ROLE", "Role must be viewer, operator, or admin")
    if isinstance(exc, LastEnabledAdminError):
        return _operator_error(409, "LAST_ENABLED_ADMIN", str(exc))
    if isinstance(exc, UserNotFoundError):
        return _operator_error(404, "USER_NOT_FOUND", str(exc))
    if isinstance(exc, DuplicateUserError):
        return _operator_error(409, "USER_ALREADY_EXISTS", str(exc))
    return _operator_error(400, "INVALID_ADMIN_USER_REQUEST", str(exc))


@router.get("/users")
async def admin_list_users(actor: AuthenticatedUser = Depends(require_admin)) -> dict:
    return success_response([_user_summary(user) for user in list_users()], meta={"mode": "admin_user_management"})


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def admin_create_user(payload: dict | None = None, actor: AuthenticatedUser = Depends(require_admin)) -> dict:
    username = _required_string(payload, "username")
    password = _required_string(payload, "password", strip=False)
    role = _required_string(payload, "role")
    try:
        created_actor = create_user(username=username, password=password, role=role)
        user = _summary_for(username)
    except ValueError as exc:
        raise _map_user_error(exc) from exc
    audit_event = record_account_audit_event(
        actor=actor,
        operation="admin.create_user",
        target_user_id=created_actor.user_id,
        target_username=created_actor.username,
        details={
            "role": created_actor.role,
            "enabled": user["enabled"],
        },
    )
    return success_response({"user": user, **audit_response_fields(audit_event)}, meta={"mode": "admin_user_management"})


@router.patch("/users/{username}/role")
async def admin_set_user_role(
    username: str,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_admin),
) -> dict:
    role = _required_string(payload, "role")
    try:
        previous = get_user_summary(username=username)
        updated_actor = set_user_role(username=username, role=role)
        user = _summary_for(username)
    except ValueError as exc:
        raise _map_user_error(exc) from exc
    audit_event = record_account_audit_event(
        actor=actor,
        operation="admin.set_user_role",
        target_user_id=updated_actor.user_id,
        target_username=updated_actor.username,
        details={
            "changed_fields": {
                "role": {
                    "old": previous.role,
                    "new": updated_actor.role,
                },
            },
            "revoked_sessions": 0,
        },
    )
    return success_response({"user": user, **audit_response_fields(audit_event)}, meta={"mode": "admin_user_management"})


@router.post("/users/{username}/disable")
async def admin_disable_user(username: str, actor: AuthenticatedUser = Depends(require_admin)) -> dict:
    try:
        previous = get_user_summary(username=username)
        result = disable_user(username=username)
        user = _summary_for(username)
    except ValueError as exc:
        raise _map_user_error(exc) from exc
    audit_event = record_account_audit_event(
        actor=actor,
        operation="admin.disable_user",
        target_user_id=result.user.user_id,
        target_username=result.user.username,
        details={
            "changed_fields": {
                "enabled": {
                    "old": previous.enabled,
                    "new": user["enabled"],
                },
            },
            "revoked_sessions": result.revoked_sessions,
        },
    )
    return success_response(
        {
            "user": user,
            "revoked_sessions": result.revoked_sessions,
            **audit_response_fields(audit_event),
        },
        meta={"mode": "admin_user_management"},
    )


@router.post("/users/{username}/reset-password")
async def admin_reset_password(
    username: str,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_admin),
) -> dict:
    password = _required_string(payload, "password", strip=False)
    try:
        previous = get_user_summary(username=username)
        result: UserOperationResult = reset_password(username=username, password=password)
        user = _summary_for(username)
    except ValueError as exc:
        raise _map_user_error(exc) from exc
    audit_event = record_account_audit_event(
        actor=actor,
        operation="admin.reset_password",
        target_user_id=result.user.user_id,
        target_username=result.user.username,
        details={
            "target_role": previous.role,
            "target_enabled": previous.enabled,
            "revoked_sessions": result.revoked_sessions,
        },
    )
    return success_response(
        {
            "user": user,
            "revoked_sessions": result.revoked_sessions,
            **audit_response_fields(audit_event),
        },
        meta={"mode": "admin_user_management"},
    )


@router.get("/sessions")
async def admin_list_sessions(
    request: Request,
    actor: AuthenticatedUser = Depends(require_admin),
) -> dict:
    current_session_id = current_session_id_from_request(request)
    return success_response(
        list_session_inventory(current_session_id=current_session_id),
        meta={"mode": "admin_session_management"},
    )


@router.post("/sessions/{session_id}/revoke")
async def admin_revoke_session(
    session_id: str,
    request: Request,
    response: Response,
    actor: AuthenticatedUser = Depends(require_admin),
) -> dict:
    current_session_id = current_session_id_from_request(request)
    try:
        result = revoke_session_by_id(session_id=session_id, current_session_id=current_session_id)
    except SessionNotFoundError as exc:
        raise _operator_error(404, "SESSION_NOT_FOUND", "Unknown session") from exc
    if result.current_session_revoked:
        clear_session_cookie(response)
    session_summary = result.session.to_dict()
    audit_event = record_account_audit_event(
        actor=actor,
        operation="admin.revoke_session",
        target_user_id=result.session.user_id,
        target_username=result.session.username,
        target_session_id=result.session.session_id,
        details={
            "previous_status": result.previous_status,
            "new_status": result.session.status,
            "revoked": result.revoked,
            "idempotent": result.idempotent,
            "current_session_revoked": result.current_session_revoked,
            "target_role": result.session.role,
            "target_enabled": result.session.enabled,
        },
    )
    return success_response(
        {
            "session": session_summary,
            "revoked": result.revoked,
            "idempotent": result.idempotent,
            "current_session_revoked": result.current_session_revoked,
            **audit_response_fields(audit_event),
        },
        meta={"mode": "admin_session_management"},
    )
