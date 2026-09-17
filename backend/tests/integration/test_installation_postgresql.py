"""Opt-in real PostgreSQL initialization/zero-user race tests, never a live DB."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from app.db.session import get_engine, get_session_factory, reset_session_cache, session_scope
from app.installation import maintenance

pytestmark = pytest.mark.postgresql


@pytest.fixture
def installed_postgres(monkeypatch):
    configured = os.getenv("GJALLAR_POSTGRES_TEST_URL")
    if not configured:
        pytest.skip("GJALLAR_POSTGRES_TEST_URL is required; SQLite is not concurrency evidence")
    if configured.startswith("postgresql://"):
        configured = configured.replace("postgresql://", "postgresql+psycopg://", 1)
    schema = "installation_test_" + uuid.uuid4().hex
    admin = create_engine(configured)
    with admin.begin() as connection:
        connection.execute(CreateSchema(schema))
    scoped = make_url(configured).update_query_dict({"options": f"-csearch_path={schema}"})
    monkeypatch.setenv("GJALLAR_DATABASE_URL", scoped.render_as_string(hide_password=False))
    monkeypatch.delenv("GJALLAR_DATABASE_URL_FILE", raising=False)
    monkeypatch.setenv("GJALLAR_INSTALLATION_ID", str(uuid.uuid4()))
    monkeypatch.setenv("GJALLAR_PASSWORD_HASH_ITERATIONS", "1200")
    reset_session_cache()
    try:
        maintenance.initialize_schema()
        get_session_factory()
        yield
    finally:
        reset_session_cache()
        with admin.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        admin.dispose()


def test_concurrent_first_admin_creates_one_user_and_one_audit(installed_postgres):
    from app.db.models import UserRecord, AccountAuditEventRecord
    barrier = Barrier(2)
    def create(index):
        barrier.wait(timeout=10)
        return maintenance.setup_admin({"username": f"admin{index}", "password": "test-only"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, range(2)))
    assert sorted(results) == ["already_initialized", "created"]
    with session_scope() as session:
        assert len(session.scalars(select(UserRecord)).all()) == 1
        assert len(session.scalars(select(AccountAuditEventRecord)).all()) == 1


def test_initializer_advisory_lock_rejects_other_connection(installed_postgres):
    with maintenance.maintenance_lock(get_engine()):
        with pytest.raises(maintenance.InstallationError, match="실행 중"):
            with maintenance.maintenance_lock(get_engine()):
                pytest.fail("second initializer acquired the lock")
