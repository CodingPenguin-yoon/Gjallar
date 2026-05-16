"""Database configuration boundary."""

from __future__ import annotations

import os


DATABASE_URL_ENV = "GJALLAR_DATABASE_URL"


def get_database_url() -> str:
    """Return the configured Gjallar database URL."""
    database_url = str(os.getenv(DATABASE_URL_ENV, "")).strip()
    if not database_url:
        raise RuntimeError(f"{DATABASE_URL_ENV} is required")
    return database_url
