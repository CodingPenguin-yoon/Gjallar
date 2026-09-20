"""Opt-in real PostgreSQL initialization/zero-user race tests, never a live DB."""
import os
import json
import subprocess
import sys
import uuid
from pathlib import Path
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


def test_fresh_process_preserves_account_connection_key_and_operation_history(installed_postgres, tmp_path):
    """Real PostgreSQL/process boundary; no Docker installation or PVE access."""
    key_file = tmp_path / 'credential-key'
    key_file.write_bytes(os.urandom(32))
    key_file.chmod(0o600)
    environment = {
        'PATH': os.environ['PATH'],
        'PYTHONPATH': str(Path(__file__).resolve().parents[2]),
        'GJALLAR_DATABASE_URL': os.environ['GJALLAR_DATABASE_URL'],
        'GJALLAR_INSTALLATION_ID': os.environ['GJALLAR_INSTALLATION_ID'],
        'GJALLAR_CREDENTIAL_KEY_FILE': str(key_file),
        'GJALLAR_PASSWORD_HASH_ITERATIONS': '1200',
    }
    def run(phase):
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), phase],
                                env=environment, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    before = run('prepare')
    after = run('restart')
    assert before == after
    assert before['state'] == 'ready'
    assert before['users'] == before['account_audits'] == 1
    assert before['operation_status'] == 'succeeded'
    assert before['event_count'] > 1


def _process_snapshot(phase):
    from hashlib import sha256
    from sqlalchemy import func
    from app.auth.users import authenticate_user
    from app.db.models import UserRecord, AccountAuditEventRecord
    from app.operations.core.domain import OperationActor, verify_event_chain
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.setup_integration.contracts import RegistrationIntent, SetupError
    from app.setup_integration.repository import RegistrationRepository
    from app.setup_integration.runtime import selected_credential

    # Refuse accidental standalone use against any non-test schema.
    options = make_url(os.environ['GJALLAR_DATABASE_URL']).query.get('options', '')
    assert options.startswith('-csearch_path=installation_test_')
    assert phase in {'prepare', 'restart'}
    repository = RegistrationRepository()
    if phase == 'prepare':
        assert maintenance.setup_admin({'username': 'restart-admin', 'password': 'synthetic-password'}) == 'created'
    else:
        assert maintenance.initialize_schema() == 'ready'
        assert maintenance.setup_admin({'username': 'must-not-replace', 'password': 'different'}) == 'already_initialized'
    maintenance.require_ready()
    actor = authenticate_user(username='restart-admin', password='synthetic-password')
    assert actor is not None and actor.role == 'admin'
    assert authenticate_user(username='restart-admin', password='different') is None
    if phase == 'prepare':
        assert selected_credential() is None
        row = repository.prepare(intent=RegistrationIntent(endpoint='https://pve.example.test', owner='test@pve',
            scope={'nodes': ['node1'], 'vmids': [40000]}, expires_at=2000000000),
            idempotency_key='restart-evidence', actor=OperationActor(user_id=actor.user_id, role=actor.role),
            installation_id=os.environ['GJALLAR_INSTALLATION_ID'], cluster_id='gjallar-mvp')
        row = repository.advance(attempt_id=row['attempt_id'], actor_id=actor.user_id, expected_version=row['version'],
            expected_phases={'prepared'}, phase='token_dispatching', operation_status='dispatching')
        row = repository.stage_secret(attempt_id=row['attempt_id'], actor_id=actor.user_id, expected_version=row['version'],
            token_secret='synthetic-proxmox-token', token_id=row['token_id'])
        # Only repository persistence is under test; no real issuance/verification is claimed.
        row = repository.advance(attempt_id=row['attempt_id'], actor_id=actor.user_id, expected_version=row['version'],
            expected_phases={'secret_staged'}, phase='verified', operation_status='verifying')
        repository.activate(attempt_id=row['attempt_id'], actor_id=actor.user_id, expected_version=row['version'])
        try:
            selected_credential()
        except SetupError as error:
            assert error.code == 'SETUP_RESTART_REQUIRED'
        else:
            raise AssertionError('The old process must require a restart after activation')
    else:
        selected = selected_credential()
        assert selected['secret'] == 'synthetic-proxmox-token'
        assert selected['configuration']['scope']['vmids'] == [40000]

    attempts = repository.list(actor.user_id)
    assert len(attempts) == 1 and attempts[0]['phase'] == 'active'
    attempt = attempts[0]
    store = SqlAlchemyOperationStore()
    events = store.list_events(attempt['operation_id'])
    assert verify_event_chain(events)
    with session_scope() as session:
        user = session.scalar(select(UserRecord))
        result = {'state': maintenance.status(), 'user_id': user.user_id,
            'password_digest': sha256(user.password_hash.encode()).hexdigest(),
            'users': session.scalar(select(func.count()).select_from(UserRecord)),
            'account_audits': session.scalar(select(func.count()).select_from(AccountAuditEventRecord)),
            'attempt': attempt, 'event_checksums': [event.checksum for event in events],
            'event_count': len(events), 'operation_status': store.get(attempt['operation_id']).status}
    print(json.dumps(result))


if __name__ == '__main__':
    _process_snapshot(sys.argv[1])
