"""Tests for Gjallar database URL policy."""

from __future__ import annotations

from pathlib import Path

from app.db.config import DATABASE_URL_ENV, SQLITE_TEST_ALLOW_ENV, get_database_url


def test_database_url_normalizes_postgresql_to_psycopg(monkeypatch):
    monkeypatch.setenv(DATABASE_URL_ENV, "postgresql://gjallar:pw@postgres:5432/gjallar")

    assert get_database_url() == "postgresql+psycopg://gjallar:pw@postgres:5432/gjallar"


def test_database_url_normalizes_postgres_alias_to_psycopg(monkeypatch):
    monkeypatch.setenv(DATABASE_URL_ENV, "postgres://gjallar:pw@postgres:5432/gjallar")

    assert get_database_url() == "postgresql+psycopg://gjallar:pw@postgres:5432/gjallar"


def test_database_url_rejects_sqlite_without_test_opt_in(monkeypatch):
    monkeypatch.setenv(DATABASE_URL_ENV, "sqlite:///tmp/gjallar.db")
    monkeypatch.delenv(SQLITE_TEST_ALLOW_ENV, raising=False)

    try:
        get_database_url()
    except RuntimeError as exc:
        assert "must use PostgreSQL" in str(exc)
    else:  # pragma: no cover - defensive assertion branch.
        raise AssertionError("SQLite URL should be rejected without test opt-in")


def test_database_url_allows_sqlite_only_with_test_opt_in(monkeypatch):
    monkeypatch.setenv(DATABASE_URL_ENV, "sqlite:///tmp/gjallar.db")
    monkeypatch.setenv(SQLITE_TEST_ALLOW_ENV, "1")

    assert get_database_url() == "sqlite:///tmp/gjallar.db"


def test_database_url_rejects_unknown_scheme(monkeypatch):
    monkeypatch.setenv(DATABASE_URL_ENV, "mysql://gjallar:pw@db/gjallar")

    try:
        get_database_url()
    except RuntimeError as exc:
        assert "must use postgresql+psycopg://" in str(exc)
    else:  # pragma: no cover - defensive assertion branch.
        raise AssertionError("Non-PostgreSQL URL should be rejected")


def test_alembic_config_accepts_percent_encoded_database_url(tmp_path, monkeypatch):
    from alembic.command import upgrade
    from alembic.config import Config

    from app.db.session import reset_session_cache

    db_path = tmp_path / "alembic-percent%3Dencoded.db"
    database_url = f"sqlite:///{db_path}"
    monkeypatch.setenv(DATABASE_URL_ENV, database_url)
    monkeypatch.setenv(SQLITE_TEST_ALLOW_ENV, "1")
    reset_session_cache()

    config = Config(str(Path("backend/alembic.ini").resolve()))
    try:
        upgrade(config, "head")
        assert db_path.is_file()
        assert config.get_main_option("sqlalchemy.url") == database_url
    finally:
        reset_session_cache()
