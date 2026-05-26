"""Public auth API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.v1.responses import success_response
from app.auth.sessions import (
    actor_from_request,
    clear_session_cookie,
    create_session,
    revoke_session_token,
    session_cookie_value,
    set_session_cookie,
)
from app.auth.users import authenticate_user

router = APIRouter(prefix="/api/v1/auth")


def _login_failed() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={
            "code": "LOGIN_FAILED",
            "message": "Invalid username or password",
        },
    )


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
