"""Server-side session service and cookie helpers."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import Response

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


@dataclass(frozen=True)
class SessionSummary:
    session_id: str
    user_id: str
    username: str
    role: str
    enabled: bool
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    status: str
    is_current_session: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role,
            "enabled": self.enabled,
            "created_at": _iso(self.created_at),
            "expires_at": _iso(self.expires_at),
            "revoked_at": _iso(self.revoked_at),
            "status": self.status,
            "is_current_session": self.is_current_session,
        }


@dataclass(frozen=True)
class SessionRevocationResult:
    session: SessionSummary
    revoked: bool
    idempotent: bool
    previous_status: str
    current_session_revoked: bool = False


class SessionNotFoundError(ValueError):
    """Raised when an admin session operation targets a missing session."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _iso(value: datetime | None) -> str | None:
    aware = _aware(value)
    return aware.isoformat() if aware is not None else None


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _optional_hash(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _session_status(row: SessionRecord, *, now: datetime | None = None) -> str:
    checked_at = now or _now()
    if row.revoked_at is not None:
        return "revoked"
    if _aware(row.expires_at) <= checked_at:
        return "expired"
    return "active"


def _summary_from_rows(
    session_row: SessionRecord,
    user_row: UserRecord,
    *,
    current_session_id: str | None = None,
    now: datetime | None = None,
) -> SessionSummary:
    actor = actor_from_user(user_row)
    return SessionSummary(
        session_id=str(session_row.session_id),
        user_id=str(user_row.user_id),
        username=str(user_row.username),
        role=actor.role,
        enabled=bool(user_row.enabled),
        created_at=session_row.created_at,
        expires_at=session_row.expires_at,
        revoked_at=session_row.revoked_at,
        status=_session_status(session_row, now=now),
        is_current_session=bool(current_session_id and session_row.session_id == current_session_id),
    )


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


def session_id_for_token(token: str | None) -> str | None:
    raw_token = str(token or "").strip()
    if not raw_token:
        return None
    with session_scope() as session:
        row = session.scalar(
            select(SessionRecord.session_id).where(SessionRecord.session_token_hash == _token_hash(raw_token))
        )
        return str(row) if row else None


def current_session_id_from_request(request: Request) -> str | None:
    return session_id_for_token(session_cookie_value(request))


def list_session_inventory(*, current_session_id: str | None = None) -> list[dict[str, Any]]:
    now = _now()
    with session_scope() as session:
        rows = session.execute(
            select(SessionRecord, UserRecord)
            .join(UserRecord, UserRecord.user_id == SessionRecord.user_id)
            .order_by(SessionRecord.created_at.desc(), SessionRecord.session_id.asc())
        ).all()
        return [
            _summary_from_rows(session_row, user_row, current_session_id=current_session_id, now=now).to_dict()
            for session_row, user_row in rows
        ]


def get_session_summary(*, session_id: str, current_session_id: str | None = None) -> SessionSummary:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise SessionNotFoundError("Unknown session")
    now = _now()
    with session_scope() as session:
        row = session.execute(
            select(SessionRecord, UserRecord)
            .join(UserRecord, UserRecord.user_id == SessionRecord.user_id)
            .where(SessionRecord.session_id == normalized_session_id)
        ).first()
        if row is None:
            raise SessionNotFoundError("Unknown session")
        session_row, user_row = row
        return _summary_from_rows(session_row, user_row, current_session_id=current_session_id, now=now)


def revoke_session_by_id(*, session_id: str, current_session_id: str | None = None) -> SessionRevocationResult:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise SessionNotFoundError("Unknown session")
    now = _now()
    with session_scope() as session:
        row = session.execute(
            select(SessionRecord, UserRecord)
            .join(UserRecord, UserRecord.user_id == SessionRecord.user_id)
            .where(SessionRecord.session_id == normalized_session_id)
        ).first()
        if row is None:
            raise SessionNotFoundError("Unknown session")
        session_row, user_row = row
        previous_status = _session_status(session_row, now=now)
        revoked = False
        if previous_status == "active":
            session_row.revoked_at = now
            revoked = True
            session.flush()
        summary = _summary_from_rows(session_row, user_row, current_session_id=current_session_id, now=now)
        return SessionRevocationResult(
            session=summary,
            revoked=revoked,
            idempotent=not revoked,
            previous_status=previous_status,
            current_session_revoked=revoked and bool(current_session_id and normalized_session_id == current_session_id),
        )


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
