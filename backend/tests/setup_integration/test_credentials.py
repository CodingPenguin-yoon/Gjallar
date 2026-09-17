"""No real credentials, network calls, OS keyring or production database."""
import json
import os
import uuid

import pytest
from sqlalchemy import select, text

from app.db.session import session_scope
from app.operations.core.domain import OperationActor
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.setup_integration.contracts import RegistrationIntent, SetupError
from app.setup_integration.crypto import CredentialCipher, CredentialKeyError
from app.setup_integration.models import ProxmoxCredentialRecord, ProxmoxRegistrationRecord
from app.setup_integration.repository import RegistrationRepository


@pytest.fixture
def cipher():
    return CredentialCipher(os.urandom(32))


@pytest.fixture
def repository(cipher):
    return RegistrationRepository(cipher_factory=lambda: cipher)


@pytest.fixture
def intent():
    return RegistrationIntent(endpoint="https://pve.example.test", owner="test@pve",
        scope={"nodes": ["test-node"], "vmids": [101]}, expires_at=2000000000)


@pytest.fixture
def prepared(repository, intent):
    return repository.prepare(intent=intent, idempotency_key="test-request", actor=OperationActor(user_id="admin", role="admin"),
        installation_id=str(uuid.uuid4()), cluster_id="test-cluster")


def test_authenticated_cipher_rejects_wrong_key_row_and_tampering(cipher):
    binding = dict(installation_id="install", connection_id="connection", revision_id="revision", metadata={"endpoint": "test"})
    nonce, ciphertext = cipher.encrypt("synthetic-token", **binding)
    assert cipher.decrypt(nonce=nonce, ciphertext=ciphertext, key_id=cipher.key_id, **binding) == "synthetic-token"
    for patch in ({"installation_id": "other"}, {"connection_id": "other"}, {"revision_id": "other"}, {"metadata": {"endpoint": "other"}}):
        with pytest.raises(CredentialKeyError):
            cipher.decrypt(nonce=nonce, ciphertext=ciphertext, key_id=cipher.key_id, **{**binding, **patch})
    with pytest.raises(CredentialKeyError):
        cipher.decrypt(nonce=nonce, ciphertext=b"!" + ciphertext[1:], key_id=cipher.key_id, **binding)
    with pytest.raises(CredentialKeyError):
        CredentialCipher(os.urandom(32)).decrypt(nonce=nonce, ciphertext=ciphertext, key_id=cipher.key_id, **binding)
    assert cipher.encrypt("synthetic-token", **binding)[0] != nonce


def test_key_file_missing_permissions_length_and_symlink(tmp_path):
    key = tmp_path / "key"
    with pytest.raises(CredentialKeyError):
        CredentialCipher.from_file(key)
    assert not key.exists()
    key.write_bytes(os.urandom(32))
    key.chmod(0o600)
    assert CredentialCipher.from_file(key).key_id
    key.chmod(0o644)
    with pytest.raises(CredentialKeyError):
        CredentialCipher.from_file(key)
    key.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(key)
    with pytest.raises(CredentialKeyError):
        CredentialCipher.from_file(link)
    key.write_bytes(b"short")
    with pytest.raises(CredentialKeyError):
        CredentialCipher.from_file(key)


def test_original_key_backup_restores_existing_ciphertext(tmp_path):
    original_key = os.urandom(32)
    key_file = tmp_path / "credential-key"
    key_file.write_bytes(original_key.hex().encode())
    key_file.chmod(0o600)
    original = CredentialCipher.from_file(key_file)
    binding = dict(installation_id="install", connection_id="connection", revision_id="revision", metadata={})
    nonce, ciphertext = original.encrypt("synthetic-secret", **binding)
    key_file.write_bytes(os.urandom(32))
    with pytest.raises(CredentialKeyError):
        CredentialCipher.from_file(key_file).decrypt(nonce=nonce, ciphertext=ciphertext, key_id=original.key_id, **binding)
    key_file.write_bytes(original_key)
    assert CredentialCipher.from_file(key_file).decrypt(nonce=nonce, ciphertext=ciphertext, key_id=original.key_id, **binding) == "synthetic-secret"


def test_registration_idempotency_and_single_unresolved_slot(repository, intent):
    options = dict(intent=intent, idempotency_key="test-request", actor=OperationActor(user_id="admin", role="admin"),
                   installation_id=str(uuid.uuid4()), cluster_id="test-cluster")
    first = repository.prepare(**options)
    assert repository.prepare(**options) == first
    with pytest.raises(SetupError, match="미완료"):
        repository.prepare(**{**options, "idempotency_key": "other-request"})
    changed = intent.model_copy(update={"expires_at": intent.expires_at + 1})
    with pytest.raises(SetupError, match="다른 등록"):
        repository.prepare(**{**options, "intent": changed})
    with pytest.raises(SetupError):
        repository.get(first["attempt_id"], "other-admin")


def test_prepare_and_operation_are_atomic(repository, intent, monkeypatch):
    original = SqlAlchemyOperationStore.create
    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("simulated crash")
    monkeypatch.setattr(SqlAlchemyOperationStore, "create", interrupted)
    with pytest.raises(RuntimeError):
        repository.prepare(intent=intent, idempotency_key="test-request", actor=OperationActor(user_id="admin", role="admin"),
            installation_id=str(uuid.uuid4()), cluster_id="test-cluster")
    with session_scope() as session:
        for table in ("proxmox_connections", "proxmox_registration_attempts", "operations", "operation_events"):
            assert session.scalar(text(f"SELECT count(*) FROM {table}")) == 0


def dispatched(repository, prepared):
    return repository.advance(attempt_id=prepared["attempt_id"], actor_id="admin", expected_version=prepared["version"],
        expected_phases={"prepared"}, phase="token_dispatching", operation_status="dispatching")


def test_secret_stage_and_audit_are_atomic_and_no_secret_is_public(repository, prepared):
    current = dispatched(repository, prepared)
    token_id = "test@pve!gjallar-" + current["attempt_id"]
    staged = repository.stage_secret(attempt_id=current["attempt_id"], actor_id="admin", expected_version=current["version"],
        token_secret="synthetic-token-secret", token_id=token_id)
    configuration, secret = repository.pending_credential(attempt_id=current["attempt_id"], actor_id="admin")
    assert secret == "synthetic-token-secret"
    assert configuration["token_id"] == token_id
    assert staged["phase"] == "secret_staged"
    events = SqlAlchemyOperationStore().list_events(staged["operation_id"])
    assert "synthetic-token-secret" not in json.dumps([event.payload for event in events]) + json.dumps(staged)
    with session_scope() as session:
        credential = session.scalar(select(ProxmoxCredentialRecord))
        assert b"synthetic-token-secret" not in credential.ciphertext
    with pytest.raises(SetupError):
        repository.stage_secret(attempt_id=current["attempt_id"], actor_id="admin", expected_version=current["version"],
            token_secret="synthetic-token-secret", token_id=token_id)


def test_stage_rollback_preserves_dispatch_uncertainty(repository, prepared, monkeypatch):
    current = dispatched(repository, prepared)
    monkeypatch.setattr(repository, "_advance", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("crash after encrypt")))
    with pytest.raises(RuntimeError):
        repository.stage_secret(attempt_id=current["attempt_id"], actor_id="admin", expected_version=current["version"],
            token_secret="synthetic-token-secret", token_id="test@pve!gjallar-" + current["attempt_id"])
    assert repository.get(current["attempt_id"], "admin")["phase"] == "token_dispatching"
    with session_scope() as session:
        assert session.scalar(select(ProxmoxCredentialRecord)) is None
        assert session.scalar(select(ProxmoxRegistrationRecord)).revision_id is None


@pytest.mark.parametrize("endpoint", ["http://pve.example.test", "https://127.0.0.1", "https://169.254.169.254", "https://[::1]",
    "https://[::ffff:127.0.0.1]", "https://user:pass@pve.test", "https://pve.test/anything", "https://pve.test?token=secret"])
def test_registration_rejects_unsafe_endpoint(intent, endpoint):
    with pytest.raises(ValueError):
        RegistrationIntent.model_validate({**intent.model_dump(), "endpoint": endpoint})


def test_no_unrecognized_fields_reach_durable_intent(intent):
    with pytest.raises(ValueError):
        RegistrationIntent.model_validate({**intent.model_dump(), "password": "must-not-persist"})
