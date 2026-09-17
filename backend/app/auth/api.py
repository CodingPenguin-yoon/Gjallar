"""Public auth API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.v1.responses import success_response
from app.auth.audit import audit_response_fields, record_account_audit_event
from app.auth.dependencies import require_user
from app.auth.roles import AuthenticatedUser
from app.auth.sessions import (
    actor_from_request,
    clear_session_cookie,
    create_session,
    current_session_id_from_request,
    revoke_session_token,
    session_cookie_value,
    set_session_cookie,
)
from app.auth.users import CurrentPasswordInvalidError, change_own_password, authenticate_user

router = APIRouter(prefix="/api/v1/auth")


def _login_failed() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={
            "code": "LOGIN_FAILED",
            "message": "Invalid username or password",
        },
    )


def _operator_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
        },
    )


def _required_string(payload: dict[str, Any] | None, key: str, *, strip: bool = True) -> str:
    if not isinstance(payload, dict):
        raise _operator_error(400, "INVALID_CHANGE_PASSWORD_REQUEST", "Request body must be a JSON object")
    raw_value = str(payload.get(key) or "")
    value = raw_value.strip() if strip else raw_value
    if not value:
        raise _operator_error(400, "INVALID_CHANGE_PASSWORD_REQUEST", f"{key} is required")
    return value


@router.post("/login")
async def login(request: Request, response: Response, payload: dict | None = None) -> dict:
    payload = payload or {}
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    if not username or not password:
        raise _login_failed()
    actor = authenticate_user(username=username, password=password)
    if actor is None:
        raise _login_failed()
    issued = create_session(actor, request=request)
    set_session_cookie(response, issued)
    return success_response(
        {
            "authenticated": True,
            "user": actor.to_dict(),
            "expires_at": issued.expires_at.isoformat(),
        },
        meta={"mode": "session_login"},
    )


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict:
    from app.setup_integration.registration import service as registration_service

    registration_service.invalidate_session(current_session_id_from_request(request))
    revoked = revoke_session_token(session_cookie_value(request))
    clear_session_cookie(response)
    return success_response(
        {
            "authenticated": False,
            "revoked": revoked,
        },
        meta={"mode": "session_logout"},
    )


@router.get("/me")
async def me(request: Request, response: Response) -> dict:
    token = session_cookie_value(request)
    actor = actor_from_request(request)
    if token and actor is None:
        clear_session_cookie(response)
    return success_response(
        {
            "authenticated": actor is not None,
            "user": actor.to_dict() if actor is not None else None,
        },
        meta={"mode": "session_status"},
    )


@router.post("/change-password")
async def change_password(
    request: Request,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_user),
) -> dict:
    current_password = _required_string(payload, "current_password", strip=False)
    new_password = _required_string(payload, "new_password", strip=False)
    current_session_id = current_session_id_from_request(request)
    try:
        result = change_own_password(
            actor=actor,
            current_password=current_password,
            new_password=new_password,
            current_session_id=current_session_id,
        )
    except CurrentPasswordInvalidError as exc:
        raise _operator_error(403, "CURRENT_PASSWORD_INVALID", "Current password is invalid") from exc
    except ValueError as exc:
        raise _operator_error(400, "INVALID_CHANGE_PASSWORD_REQUEST", str(exc)) from exc

    audit_event = record_account_audit_event(
        actor=actor,
        operation="auth.change_password",
        target_user_id=result.user.user_id,
        target_username=result.user.username,
        target_session_id=current_session_id,
        details={
            "revoked_sessions": result.revoked_sessions,
            "current_session_preserved": result.current_session_preserved,
        },
    )
    return success_response(
        {
            "authenticated": True,
            "user": result.user.to_dict(),
            "revoked_sessions": result.revoked_sessions,
            "current_session_preserved": result.current_session_preserved,
            **audit_response_fields(audit_event),
        },
        meta={"mode": "self_password_change"},
    )
