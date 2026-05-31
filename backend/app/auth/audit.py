"""Sanitized audit helper for local account and session operations."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.auth.roles import AuthenticatedUser, actor_evidence
from app.db.models import AccountAuditEventRecord
from app.db.session import session_scope

_OMIT_KEY_NAMES = {
    "ip",
    "ip_hash",
    "remote_ip",
    "client_ip",
    "user_agent",
    "user_agent_hash",
}
_OMIT_KEY_FRAGMENTS = ("password", "token", "hash", "secret")


@dataclass(frozen=True)
class AccountAuditEvent:
    event_id: str
    operation: str
    actor: dict[str, str]
    target: dict[str, str]
    details: dict[str, Any]
    created_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _audit_event_id() -> str:
    return f"acctevt-{uuid.uuid4().hex}"


def _safe_text(value: Any) -> str | None:
    text = str(value if value is not None else "").strip()
    return text or None


def _unsafe_key(key: Any) -> bool:
    normalized = str(key or "").strip().lower()
    if normalized in _OMIT_KEY_NAMES:
        return True
    return any(fragment in normalized for fragment in _OMIT_KEY_FRAGMENTS)


def sanitize_audit_details(value: Any) -> Any:
    """Return JSON-safe audit details with secret-bearing fields omitted."""
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if _unsafe_key(key):
                continue
            sanitized[str(key)] = sanitize_audit_details(item)
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_audit_details(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def audit_event_response(event: AccountAuditEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "operation": event.operation,
        "actor": event.actor,
        "target": event.target,
        "details": event.details,
        "created_at": event.created_at.isoformat(),
    }


def audit_response_fields(event: AccountAuditEvent) -> dict[str, Any]:
    return {
        "audit_event_id": event.event_id,
        "audit_event": audit_event_response(event),
    }


def record_account_audit_event(
    *,
    actor: AuthenticatedUser | dict | None,
    operation: str,
    target_user_id: str | None = None,
    target_username: str | None = None,
    target_session_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> AccountAuditEvent:
    trusted_actor = actor_evidence(actor)
    created_at = _now()
    target = {
        key: value
        for key, value in {
            "user_id": _safe_text(target_user_id),
            "username": _safe_text(target_username),
            "session_id": _safe_text(target_session_id),
        }.items()
        if value
    }
    sanitized_details = sanitize_audit_details(details or {})
    event_id = _audit_event_id()
    with session_scope() as session:
        session.add(
            AccountAuditEventRecord(
                event_id=event_id,
                operation=str(operation or "").strip(),
                actor_user_id=trusted_actor.get("user_id"),
                actor_username=trusted_actor.get("username"),
                actor_role=trusted_actor.get("role"),
                target_user_id=target.get("user_id"),
                target_username=target.get("username"),
                target_session_id=target.get("session_id"),
                details=sanitized_details,
                created_at=created_at,
            )
        )
    return AccountAuditEvent(
        event_id=event_id,
        operation=str(operation or "").strip(),
        actor=trusted_actor,
        target=target,
        details=sanitized_details,
        created_at=created_at,
    )
