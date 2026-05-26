"""Role helpers for Gjallar console authorization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

ROLE_ORDER: dict[str, int] = {
    "viewer": 10,
    "operator": 20,
    "admin": 30,
}
VALID_ROLES = tuple(ROLE_ORDER)


@dataclass(frozen=True)
class AuthenticatedUser:
    """Authenticated user identity resolved from a server-side session."""

    user_id: str
    username: str
    role: str

    def to_dict(self) -> dict[str, str]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role,
        }


def normalize_role(role: str) -> str:
    normalized = str(role or "").strip().lower()
    if normalized not in ROLE_ORDER:
        raise ValueError(f"Unsupported Gjallar role: {role!r}")
    return normalized


def role_at_least(actual: str, required: str) -> bool:
    actual_role = normalize_role(actual)
    required_role = normalize_role(required)
    return ROLE_ORDER[actual_role] >= ROLE_ORDER[required_role]


def actor_evidence(actor: AuthenticatedUser | dict | None) -> dict[str, str]:
    """Return auditable actor fields from a trusted authenticated session."""
    if actor is None:
        return {}
    if isinstance(actor, AuthenticatedUser):
        return actor.to_dict()
    if not actor:
        return {}
    return {
        "user_id": str(actor.get("user_id") or ""),
        "username": str(actor.get("username") or ""),
        "role": normalize_role(str(actor.get("role") or "")),
    }


def actor_detail_fields(actor: AuthenticatedUser | dict | None) -> dict[str, object]:
    evidence = actor_evidence(actor)
    if not evidence:
        return {}
    return {
        "actor": evidence,
        "actor_user_id": evidence["user_id"],
        "actor_username": evidence["username"],
        "actor_role": evidence["role"],
    }


def _trusted_actor_fields(payload: Mapping[str, Any]) -> dict[str, object]:
    actor = payload.get("actor")
    actor_map = actor if isinstance(actor, Mapping) else {}
    user_id = str(payload.get("actor_user_id") or actor_map.get("user_id") or "")
    username = str(payload.get("actor_username") or actor_map.get("username") or "")
    role = str(payload.get("actor_role") or actor_map.get("role") or "")
    if not (user_id or username or role):
        return {}
    try:
        return actor_detail_fields({"user_id": user_id, "username": username, "role": role})
    except ValueError:
        return {}


def restore_trusted_actor_evidence(original: Any, redacted: Any) -> Any:
    """Restore trusted session actor evidence after generic secret redaction."""
    if isinstance(original, Mapping) and isinstance(redacted, Mapping):
        restored = {
            key: restore_trusted_actor_evidence(original.get(key), value)
            for key, value in redacted.items()
        }
        restored.update(_trusted_actor_fields(original))
        return restored
    if isinstance(original, Sequence) and not isinstance(original, (str, bytes)) and isinstance(redacted, Sequence):
        return [
            restore_trusted_actor_evidence(original_item, redacted_item)
            for original_item, redacted_item in zip(original, redacted, strict=False)
        ]
    return redacted
