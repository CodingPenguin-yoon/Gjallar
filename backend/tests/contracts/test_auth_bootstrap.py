"""Bootstrap admin account contract tests."""

from __future__ import annotations

from sqlalchemy import select


def _fast_hash(monkeypatch) -> None:
    monkeypatch.setenv("GJALLAR_PASSWORD_HASH_ITERATIONS", "1200")


def test_bootstrap_admin_from_env_cli_creates_enabled_admin_without_leaking_password(monkeypatch, capsys):
    _fast_hash(monkeypatch)
    monkeypatch.setenv("GJALLAR_BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("GJALLAR_BOOTSTRAP_ADMIN_PASSWORD", "1234")

    from app.auth.users import main
    from app.auth.users import authenticate_user
    from app.db.models import UserRecord
    from app.db.session import session_scope

    assert main(["bootstrap-admin-from-env"]) == 0
    captured = capsys.readouterr()
    assert "created bootstrap admin user admin" in captured.out
    assert "1234" not in captured.out
    assert captured.err == ""

    actor = authenticate_user(username="admin", password="1234")
    assert actor is not None
    assert actor.role == "admin"
    with session_scope() as session:
        row = session.scalar(select(UserRecord).where(UserRecord.username == "admin"))
        assert row is not None
        assert row.enabled is True
        assert row.role == "admin"
        assert row.password_hash != "1234"


def test_bootstrap_admin_from_env_is_noop_when_not_configured(monkeypatch, capsys):
    monkeypatch.delenv("GJALLAR_BOOTSTRAP_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("GJALLAR_BOOTSTRAP_ADMIN_PASSWORD", raising=False)

    from app.auth.users import main
    from app.db.models import UserRecord
    from app.db.session import session_scope

    assert main(["bootstrap-admin-from-env"]) == 0
    captured = capsys.readouterr()
    assert "bootstrap admin not configured" in captured.out
    assert captured.err == ""
    with session_scope() as session:
        assert session.scalar(select(UserRecord)) is None


def test_bootstrap_admin_from_env_does_not_reset_existing_admin_password(monkeypatch):
    _fast_hash(monkeypatch)
    monkeypatch.setenv("GJALLAR_BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("GJALLAR_BOOTSTRAP_ADMIN_PASSWORD", "1234")

    from app.auth.users import authenticate_user, bootstrap_admin_from_env

    created = bootstrap_admin_from_env()
    assert created.status == "created"

    monkeypatch.setenv("GJALLAR_BOOTSTRAP_ADMIN_PASSWORD", "new-password")
    skipped = bootstrap_admin_from_env()

    assert skipped.status == "already_exists"
    assert authenticate_user(username="admin", password="1234") is not None
    assert authenticate_user(username="admin", password="new-password") is None


def test_bootstrap_admin_from_env_rejects_existing_non_admin_without_leaking_password(monkeypatch, capsys):
    _fast_hash(monkeypatch)
    monkeypatch.setenv("GJALLAR_BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("GJALLAR_BOOTSTRAP_ADMIN_PASSWORD", "1234")

    from app.auth.users import create_user, main

    create_user(username="admin", password="viewer-password", role="viewer")

    assert main(["bootstrap-admin-from-env"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "existing user that is not an enabled admin: admin" in captured.err
    assert "1234" not in captured.err
