"""Fresh-install boundaries with isolated SQLite; not PostgreSQL concurrency evidence."""
import io
import json
import uuid

import pytest
from sqlalchemy import MetaData, Table, Column, Integer, insert, select, text

from app.db.session import get_engine, reset_session_cache, session_scope
from app.installation import maintenance


@pytest.fixture
def fresh(monkeypatch, tmp_path):
    monkeypatch.setenv("GJALLAR_DATABASE_URL", f"sqlite:///{tmp_path / 'fresh.db'}")
    monkeypatch.setenv("GJALLAR_ALLOW_SQLITE_FOR_TESTS", "1")
    monkeypatch.delenv("GJALLAR_DATABASE_URL_FILE", raising=False)
    monkeypatch.setenv("GJALLAR_INSTALLATION_ID", str(uuid.uuid4()))
    monkeypatch.setenv("GJALLAR_PASSWORD_HASH_ITERATIONS", "1200")
    reset_session_cache()
    yield
    reset_session_cache()


def test_fresh_schema_admin_and_restart_do_not_migrate_or_reset(fresh, monkeypatch):
    from app.auth.users import authenticate_user
    from app.db.models import UserRecord, AccountAuditEventRecord
    assert maintenance.initialize_schema() == "schema_ready"
    assert maintenance.setup_admin({"username": "first", "password": "original-secret"}) == "created"
    assert maintenance.setup_admin({"username": "another", "password": "replacement-secret"}) == "already_initialized"
    monkeypatch.setattr(maintenance.command, "upgrade", lambda *args: pytest.fail("restart must not migrate"))
    assert maintenance.initialize_schema() == "ready"
    maintenance.require_ready()
    with session_scope() as session:
        assert len(session.scalars(select(UserRecord)).all()) == 1
        events = session.scalars(select(AccountAuditEventRecord)).all()
        assert len(events) == 1 and events[0].operation == "installation.create_first_admin"
    assert authenticate_user(username="first", password="original-secret")
    assert not authenticate_user(username="first", password="replacement-secret")


def test_unknown_existing_db_not_migrated_even_zero_users(fresh, monkeypatch):
    historical = Table("historical_jobs", MetaData(), Column("id", Integer, primary_key=True))
    historical.create(get_engine())
    with get_engine().begin() as connection:
        connection.execute(historical.insert().values(id=7))
    monkeypatch.setattr(maintenance.command, "upgrade", lambda *args: pytest.fail("unknown database"))
    with pytest.raises(maintenance.InstallationError, match="빈 DB"):
        maintenance.initialize_schema()
    with get_engine().connect() as connection:
        assert connection.scalar(select(historical.c.id)) == 7


def test_interrupted_migration_resumes_same_identity(fresh, monkeypatch):
    original = maintenance.command.upgrade
    monkeypatch.setattr(maintenance.command, "upgrade", lambda *args: (_ for _ in ()).throw(RuntimeError("interrupted")))
    with pytest.raises(RuntimeError):
        maintenance.initialize_schema()
    with get_engine().connect() as connection:
        assert maintenance.marker(connection, maintenance.identity())["state"] == "initializing"
    monkeypatch.setattr(maintenance.command, "upgrade", original)
    assert maintenance.initialize_schema() == "schema_ready"


def test_identity_mismatch_is_rejected(fresh, monkeypatch):
    maintenance.initialize_schema()
    monkeypatch.setenv("GJALLAR_INSTALLATION_ID", str(uuid.uuid4()))
    with pytest.raises(maintenance.InstallationError, match="identity"):
        maintenance.initialize_schema()
    with pytest.raises(maintenance.InstallationError):
        maintenance.setup_admin({"username": "x", "password": "secret"})


def test_existing_disabled_user_blocks_admin_and_preserves_hash(fresh):
    from app.auth.users import create_user
    from app.db.models import UserRecord
    maintenance.initialize_schema()
    create_user(username="old", password="original", role="viewer", enabled=False)
    with session_scope() as session:
        previous = session.scalar(select(UserRecord.password_hash))
    with pytest.raises(ValueError, match="zero-user"):
        maintenance.setup_admin({"username": "new", "password": "new-secret"})
    with session_scope() as session:
        assert session.scalar(select(UserRecord.password_hash)) == previous
    assert maintenance.status() == "schema_ready"


def test_history_blocks_zero_user_bootstrap(fresh):
    maintenance.initialize_schema()
    table = Table("preserved_history", MetaData(), Column("id", Integer, primary_key=True))
    table.create(get_engine())
    with get_engine().begin() as connection:
        connection.execute(table.insert().values(id=1))
    with pytest.raises(maintenance.InstallationError, match="업무 이력"):
        maintenance.setup_admin({"username": "new", "password": "secret"})


def test_admin_transaction_rollback_and_retry(fresh, monkeypatch):
    from app.db.models import UserRecord, AccountAuditEventRecord
    maintenance.initialize_schema()
    original = maintenance.create_first_installation_admin
    def interrupted(session, **kwargs):
        original(session, **kwargs)
        raise RuntimeError("interrupt after insert")
    monkeypatch.setattr(maintenance, "create_first_installation_admin", interrupted)
    with pytest.raises(RuntimeError):
        maintenance.setup_admin({"username": "first", "password": "secret"})
    with session_scope() as session:
        assert session.scalar(select(UserRecord)) is None
        assert session.scalar(select(AccountAuditEventRecord)) is None
    assert maintenance.status() == "schema_ready"
    monkeypatch.setattr(maintenance, "create_first_installation_admin", original)
    assert maintenance.setup_admin({"username": "first", "password": "secret"}) == "created"


def test_serve_revision_and_initialization_guard(fresh, monkeypatch):
    from app.installation import serve
    monkeypatch.setattr(serve.os, "execvp", lambda *args: pytest.fail("not ready"))
    maintenance.initialize_schema()
    assert serve.serve() == 1
    maintenance.setup_admin({"username": "first", "password": "secret"})
    with get_engine().begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'unknown_revision'"))
    assert serve.serve() == 1


def test_maintenance_stdin_only_and_sanitized_error(fresh, monkeypatch, capsys):
    maintenance.initialize_schema()
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"username": "first", "password": "synthetic-secret"})))
    assert maintenance.main(["setup-admin"]) == 0
    assert "synthetic-secret" not in capsys.readouterr().out
    monkeypatch.setattr(maintenance, "status", lambda: (_ for _ in ()).throw(RuntimeError("synthetic-secret")))
    assert maintenance.main(["status"]) == 1
    captured = capsys.readouterr()
    assert "synthetic-secret" not in captured.out + captured.err


def test_database_url_file_and_conflict(monkeypatch, tmp_path):
    from app.db.config import get_database_url
    path = tmp_path / "db-secret"
    path.write_text("postgresql://gjallar:synthetic-secret@postgres/gjallar\n")
    monkeypatch.delenv("GJALLAR_DATABASE_URL", raising=False)
    monkeypatch.setenv("GJALLAR_DATABASE_URL_FILE", str(path))
    assert get_database_url().startswith("postgresql+psycopg://")
    monkeypatch.setenv("GJALLAR_DATABASE_URL", "postgresql://another/other")
    with pytest.raises(RuntimeError, match="one database"):
        get_database_url()
