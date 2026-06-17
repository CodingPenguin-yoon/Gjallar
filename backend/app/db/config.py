"""Database configuration boundary."""

from __future__ import annotations

import os


DATABASE_URL_ENV = "GJALLAR_DATABASE_URL"
SQLITE_TEST_ALLOW_ENV = "GJALLAR_ALLOW_SQLITE_FOR_TESTS"


def _env_truthy(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_database_url(database_url: str) -> str:
    normalized = database_url.strip()
    lowered = normalized.lower()
    if lowered.startswith("postgresql://"):
        return f"postgresql+psycopg://{normalized[len('postgresql://'):]}"
    if lowered.startswith("postgres://"):
        return f"postgresql+psycopg://{normalized[len('postgres://'):]}"
    return normalized


def get_database_url() -> str:
    """Return the configured Gjallar database URL."""
    database_url = _normalize_database_url(str(os.getenv(DATABASE_URL_ENV, "")).strip())
    if not database_url:
        raise RuntimeError(f"{DATABASE_URL_ENV} is required")
    lowered = database_url.lower()
    if lowered.startswith("sqlite"):
        if _env_truthy(SQLITE_TEST_ALLOW_ENV):
            return database_url
        raise RuntimeError(
            f"{DATABASE_URL_ENV} must use PostgreSQL; SQLite is only allowed when "
            f"{SQLITE_TEST_ALLOW_ENV}=1 for tests"
        )
    if not lowered.startswith("postgresql+psycopg://"):
        raise RuntimeError(f"{DATABASE_URL_ENV} must use postgresql+psycopg://")
    return database_url
