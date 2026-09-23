"""Lazy auth configuration helpers."""

from __future__ import annotations

import os

SESSION_COOKIE_NAME_ENV = "GJALLAR_SESSION_COOKIE_NAME"
SESSION_TTL_SECONDS_ENV = "GJALLAR_SESSION_TTL_SECONDS"
SESSION_COOKIE_SECURE_ENV = "GJALLAR_SESSION_COOKIE_SECURE"
SESSION_COOKIE_SAMESITE_ENV = "GJALLAR_SESSION_COOKIE_SAMESITE"
ALLOWED_ORIGINS_ENV = "GJALLAR_ALLOWED_ORIGINS"

DEFAULT_SESSION_COOKIE_NAME = "gjallar_session"
DEFAULT_SESSION_TTL_SECONDS = 8 * 60 * 60


def _truthy(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def session_cookie_name() -> str:
    return str(os.getenv(SESSION_COOKIE_NAME_ENV, DEFAULT_SESSION_COOKIE_NAME)).strip() or DEFAULT_SESSION_COOKIE_NAME


def session_ttl_seconds() -> int:
    raw = str(os.getenv(SESSION_TTL_SECONDS_ENV, "")).strip()
    if not raw:
        return DEFAULT_SESSION_TTL_SECONDS
    try:
        return max(60, int(raw))
    except ValueError:
        return DEFAULT_SESSION_TTL_SECONDS


def session_cookie_secure() -> bool:
    explicit = _truthy(os.getenv(SESSION_COOKIE_SECURE_ENV))
    if explicit is not None:
        return explicit
    return str(os.getenv("GJALLAR_ENV", "")).strip().lower() in {"prod", "production"}


def session_cookie_samesite() -> str:
    value = str(os.getenv(SESSION_COOKIE_SAMESITE_ENV, "lax")).strip().lower()
    return value if value in {"lax", "strict", "none"} else "lax"


def allowed_origins() -> set[str]:
    frontend_port = os.getenv("FRONTEND_PORT", "5173")
    origins = {
        f"http://localhost:{frontend_port}",
        f"http://127.0.0.1:{frontend_port}",
    }
    configured = str(os.getenv(ALLOWED_ORIGINS_ENV, "")).strip()
    if configured:
        origins.update(origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip())
    return origins


def allow_same_origin() -> bool:
    return _truthy(os.getenv("GJALLAR_ALLOW_SAME_ORIGIN")) is True
