"""Server-side session service and cookie helpers."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from starlette.requests import Request
from starlette.responses import Response
from sqlalchemy import select

from app.auth.config import (
    session_cookie_name,
    session_cookie_samesite,
    session_cookie_secure,
    session_ttl_seconds,
)
from app.auth.roles import AuthenticatedUser
from app.auth.users import actor_from_user
from app.db.models import SessionRecord, UserRecord
from app.db.session import session_scope


@dataclass(frozen=True)
class IssuedSession:
    token: str
    expires_at: datetime
    actor: AuthenticatedUser


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _optional_hash(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _request_ip(request: Request | None) -> str:
    if request is None or request.client is None:
        return ""
    return str(request.client.host or "")


def create_session(actor: AuthenticatedUser, *, request: Request | None = None) -> IssuedSession:
    token = secrets.token_urlsafe(32)
    now = _now()
    expires_at = now + timedelta(seconds=session_ttl_seconds())
    with session_scope() as session:
        row = SessionRecord(
            session_id=f"sess_{uuid.uuid4().hex}",
            user_id=actor.user_id,
            session_token_hash=_token_hash(token),
            expires_at=expires_at,
            created_at=now,
            user_agent_hash=_optional_hash(request.headers.get("user-agent") if request is not None else None),
            ip_hash=_optional_hash(_request_ip(request)),
        )
        session.add(row)
    return IssuedSession(token=token, expires_at=expires_at, actor=actor)


def actor_for_session_token(token: str | None) -> AuthenticatedUser | None:
    raw_token = str(token or "").strip()
    if not raw_token:
        return None
    now = _now()
    with session_scope() as session:
        row = session.scalar(
            select(SessionRecord).where(SessionRecord.session_token_hash == _token_hash(raw_token))
        )
        if row is None or row.revoked_at is not None:
            return None
        if _aware(row.expires_at) <= now:
            row.revoked_at = now
            return None
        user = session.get(UserRecord, row.user_id)
        if user is None or user.enabled is not True:
            row.revoked_at = now
            return None
        return actor_from_user(user)


def revoke_session_token(token: str | None) -> bool:
    raw_token = str(token or "").strip()
    if not raw_token:
        return False
    now = _now()
    with session_scope() as session:
        row = session.scalar(
            select(SessionRecord).where(SessionRecord.session_token_hash == _token_hash(raw_token))
        )
        if row is None or row.revoked_at is not None:
            return False
        row.revoked_at = now
        return True


def session_cookie_value(request: Request) -> str | None:
    return request.cookies.get(session_cookie_name())


def set_session_cookie(response: Response, issued: IssuedSession) -> None:
    response.set_cookie(
        key=session_cookie_name(),
        value=issued.token,
        max_age=session_ttl_seconds(),
        expires=issued.expires_at,
        path="/",
        secure=session_cookie_secure(),
        httponly=True,
        samesite=session_cookie_samesite(),
    )


def clear_session_cookie(response: Response) -> None:
    response.set_cookie(
        key=session_cookie_name(),
        value="",
        max_age=0,
        expires=0,
        path="/",
        secure=session_cookie_secure(),
        httponly=True,
        samesite=session_cookie_samesite(),
    )


def actor_from_request(request: Request) -> AuthenticatedUser | None:
    return actor_for_session_token(session_cookie_value(request))


def actor_payload(actor: AuthenticatedUser | None) -> dict[str, Any]:
    return actor.to_dict() if actor is not None else {}
