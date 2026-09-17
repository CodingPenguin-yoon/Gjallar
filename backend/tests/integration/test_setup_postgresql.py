"""Opt-in PostgreSQL evidence for setup CAS and shared VM admission."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from app.db.metadata import Base
from app.db.session import reset_session_cache, get_engine, get_session_factory
from app.operations.core.domain import OperationActor
from app.setup_integration.contracts import RegistrationIntent, SetupError
from app.setup_integration.crypto import CredentialCipher
from app.setup_integration.repository import RegistrationRepository

pytestmark = pytest.mark.postgresql


@pytest.fixture
def postgres_setup(monkeypatch):
    configured = os.getenv("GJALLAR_POSTGRES_TEST_URL")
    if not configured:
        pytest.skip("GJALLAR_POSTGRES_TEST_URL is required; SQLite is not concurrency evidence")
    configured = configured.replace("postgresql://", "postgresql+psycopg://", 1)
    schema = "setup_test_" + uuid.uuid4().hex
    admin = create_engine(configured)
    with admin.begin() as connection:
        connection.execute(CreateSchema(schema))
    scoped = make_url(configured).update_query_dict({"options": f"-csearch_path={schema}"})
    monkeypatch.setenv("GJALLAR_DATABASE_URL", scoped.render_as_string(hide_password=False))
    monkeypatch.delenv("GJALLAR_DATABASE_URL_FILE", raising=False)
    reset_session_cache()
    Base.metadata.create_all(get_engine())
    get_session_factory()
    cipher = CredentialCipher(os.urandom(32))
    try:
        yield RegistrationRepository(cipher_factory=lambda: cipher)
    finally:
        reset_session_cache()
        with admin.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        admin.dispose()


def test_concurrent_registration_replays_one_operation(postgres_setup):
    repository = postgres_setup
    intent = RegistrationIntent(endpoint="https://pve.example.test", owner="test@pve",
        scope={"nodes": ["node1"]}, expires_at=2000000000)
    identity = str(uuid.uuid4())
    barrier = Barrier(2)
    def prepare(_):
        barrier.wait(timeout=10)
        return repository.prepare(intent=intent, idempotency_key="same-key-request", actor=OperationActor(user_id="admin", role="admin"),
            installation_id=identity, cluster_id="gjallar-mvp")
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(prepare, range(2)))
    assert rows[0] == rows[1]
    assert len(repository.list("admin")) == 1


def test_concurrent_registration_cas_has_one_dispatch_winner(postgres_setup):
    repository = postgres_setup
    row = repository.prepare(intent=RegistrationIntent(endpoint="https://pve.example.test", owner="test@pve",
        scope={"nodes": ["node1"]}, expires_at=2000000000), idempotency_key="same-key-request",
        actor=OperationActor(user_id="admin", role="admin"), installation_id=str(uuid.uuid4()), cluster_id="gjallar-mvp")
    barrier = Barrier(2)
    def dispatch(_):
        barrier.wait(timeout=10)
        try:
            return repository.advance(attempt_id=row["attempt_id"], actor_id="admin", expected_version=row["version"],
                expected_phases={"prepared"}, phase="token_dispatching", operation_status="dispatching")["phase"]
        except SetupError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(dispatch, range(2)))
    assert sorted(results) == ["SETUP_VERSION_CONFLICT", "token_dispatching"]


def test_activation_and_vm_admission_cannot_both_succeed(postgres_setup):
    from app.operations.locks.domain import DurableTargetLockBusy
    from app.operations.locks.infrastructure.repository import SqlAlchemyDurableTargetLockRepository
    from app.setup_integration.runtime import selected_credential

    repository = postgres_setup
    row = repository.prepare(intent=RegistrationIntent(endpoint="https://pve.example.test", owner="test@pve",
        scope={"nodes": ["node1"], "vmids": [101]}, expires_at=2000000000), idempotency_key="activation-race",
        actor=OperationActor(user_id="admin", role="admin"), installation_id=str(uuid.uuid4()), cluster_id="gjallar-mvp")
    row = repository.advance(attempt_id=row["attempt_id"], actor_id="admin", expected_version=row["version"],
        expected_phases={"prepared"}, phase="token_dispatching", operation_status="dispatching")
    row = repository.stage_secret(attempt_id=row["attempt_id"], actor_id="admin", expected_version=row["version"],
        token_secret="synthetic-secret", token_id=row["token_id"])
    row = repository.advance(attempt_id=row["attempt_id"], actor_id="admin", expected_version=row["version"],
        expected_phases={"secret_staged"}, phase="verified", operation_status="verifying")
    assert selected_credential() is None
    barrier = Barrier(2)

    def activate():
        barrier.wait(timeout=10)
        try:
            repository.activate(attempt_id=row["attempt_id"], actor_id="admin", expected_version=row["version"])
            return "activated"
        except SetupError as error:
            return error.code

    def admit():
        barrier.wait(timeout=10)
        try:
            SqlAlchemyDurableTargetLockRepository().acquire(cluster_id="gjallar-mvp", vmid=101,
                operation_type="vm_start", owner_id="vm-operation", reason="concurrency-test")
            return "admitted"
        except DurableTargetLockBusy as error:
            return error.existing["reason"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        activation = pool.submit(activate)
        admission = pool.submit(admit)
        outcomes = (activation.result(), admission.result())
    assert outcomes in {("activated", "SETUP_RESTART_REQUIRED"), ("SETUP_WORK_IN_PROGRESS", "admitted")}
