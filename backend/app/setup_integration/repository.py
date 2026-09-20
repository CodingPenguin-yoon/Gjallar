"""Transactional setup storage; only allowlisted metadata reaches audit events."""
from contextlib import nullcontext
import hashlib
import uuid

from sqlalchemy import select, text

from app.db.session import session_scope
from app.operations.core.domain import OperationActor, OperationSpec
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.setup_integration.contracts import RegistrationIntent, SetupError, digest
from app.setup_integration.crypto import CredentialCipher, CredentialKeyError
from app.setup_integration.models import ProxmoxConnectionRecord, ProxmoxCredentialRecord, ProxmoxRegistrationRecord

# Shared by registration, source activation and VM mutation admission.
CONNECTION_LOCK_ID = 73106429381742


def lock_connection(session):
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": CONNECTION_LOCK_ID})
    else:
        # SQLite is explicitly test-only; it is not PostgreSQL concurrency proof.
        transaction = session.get_transaction()
        if transaction is not None and session.info.get("gjallar_connection_lock_transaction") is transaction:
            return
        session.execute(text("BEGIN IMMEDIATE"))
        session.info["gjallar_connection_lock_transaction"] = session.get_transaction()


def public_attempt(row):
    return {"attempt_id": row.attempt_id, "operation_id": row.operation_id,
            "mode": row.intent.get("mode", "issue"),
            "token_id": row.intent["owner"] + "!gjallar-" + row.attempt_id if row.intent.get("mode", "issue") == "issue" else None,
            "phase": row.phase, "version": row.version, "resolved": row.resolved,
            "connection_version": row.expected_connection_version,
            "plan_digest": row.plan_digest or None, "revision_id": row.revision_id,
            "revocation_operation_id": row.revocation_operation_id}


class RegistrationRepository:
    def __init__(self, *, sessions=session_scope, cipher_factory=CredentialCipher.configured):
        self.sessions = sessions
        self.cipher_factory = cipher_factory

    @staticmethod
    def operation_store(session):
        # The existing store accepts a caller-owned context manager. nullcontext
        # neither commits nor rolls back: setup + Operation share one transaction.
        return SqlAlchemyOperationStore(sessions=lambda: nullcontext(session))

    def prepare(self, *, intent: RegistrationIntent, idempotency_key: str, actor: OperationActor,
                installation_id: str, cluster_id: str):
        if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 160:
            raise SetupError("SETUP_INVALID_INPUT", "idempotency key가 올바르지 않습니다.", 422)
        if actor.role != "admin" or not actor.user_id:
            raise SetupError("SETUP_ADMIN_REQUIRED", "관리자 권한이 필요합니다.", 403)
        installation_id = str(uuid.UUID(installation_id))
        normalized = intent.model_dump(mode="json")
        intent_hash = digest(normalized)
        identity_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
        # Check key availability before creating a workflow that can issue tokens.
        self.cipher_factory()
        with self.sessions() as session:
            lock_connection(session)
            connection = session.get(ProxmoxConnectionRecord, 1)
            if connection is None:
                connection = ProxmoxConnectionRecord(slot=1, connection_id=str(uuid.uuid4()),
                    installation_id=installation_id, cluster_id=cluster_id, source="legacy_env",
                    admission="open", version=1)
                session.add(connection)
                session.flush()
            if connection.installation_id != installation_id or connection.cluster_id != cluster_id:
                raise SetupError("SETUP_IDENTITY_CONFLICT", "설치 또는 cluster identity가 다릅니다.")
            existing = session.scalar(select(ProxmoxRegistrationRecord).where(
                ProxmoxRegistrationRecord.connection_id == connection.connection_id,
                ProxmoxRegistrationRecord.idempotency_digest == identity_hash))
            if existing is not None:
                if existing.intent_digest != intent_hash or existing.actor_id != actor.user_id:
                    raise SetupError("SETUP_IDEMPOTENCY_CONFLICT", "같은 요청 key가 다른 등록에 사용됐습니다.")
                return public_attempt(existing)
            pending = session.scalar(select(ProxmoxRegistrationRecord.attempt_id).where(
                ProxmoxRegistrationRecord.connection_id == connection.connection_id,
                ProxmoxRegistrationRecord.resolved.is_(False)))
            if pending:
                raise SetupError("SETUP_UNRESOLVED_ATTEMPT", "미완료 등록을 먼저 확인하세요.")
            attempt_id = str(uuid.uuid4())
            operation_id = "proxmox-registration-" + attempt_id
            self.operation_store(session).create(OperationSpec(
                operation_id=operation_id, operation_type="proxmox_registration", execution_mode="managed_api",
                target_type="proxmox_connection", target_id=connection.connection_id,
                idempotency_key=identity_hash, intent_digest=intent_hash, plan_digest=intent_hash,
                actor=actor, initial_status="planned", initial_stage="prepared",
                details={"attempt_id": attempt_id},
            ), event_payload={"attempt_id": attempt_id})
            row = ProxmoxRegistrationRecord(attempt_id=attempt_id, connection_id=connection.connection_id,
                operation_id=operation_id, actor_id=actor.user_id, idempotency_digest=identity_hash,
                intent_digest=intent_hash, plan_digest="", intent=normalized,
                phase="prepared", resolved=False, expected_connection_version=connection.version, version=1)
            session.add(row)
            session.flush()
            return public_attempt(row)

    @staticmethod
    def owned(session, attempt_id, actor_id, expected_version=None):
        row = session.get(ProxmoxRegistrationRecord, attempt_id)
        if row is None or row.actor_id != actor_id:
            raise SetupError("SETUP_ATTEMPT_NOT_FOUND", "등록 요청을 찾을 수 없습니다.", 404)
        if expected_version is not None and row.version != expected_version:
            raise SetupError("SETUP_VERSION_CONFLICT", "등록 상태가 변경됐습니다. 다시 조회하세요.")
        return row

    def get(self, attempt_id, actor_id):
        with self.sessions() as session:
            return public_attempt(self.owned(session, attempt_id, actor_id))

    def list(self, actor_id):
        with self.sessions() as session:
            return [public_attempt(row) for row in session.scalars(select(ProxmoxRegistrationRecord)
                .where(ProxmoxRegistrationRecord.actor_id == actor_id)
                .order_by(ProxmoxRegistrationRecord.created_at.desc()).limit(50)).all()]

    def intent(self, attempt_id, actor_id):
        with self.sessions() as session:
            return RegistrationIntent.model_validate(self.owned(session, attempt_id, actor_id).intent)

    def advance(self, *, attempt_id, actor_id, expected_version, expected_phases, phase,
                operation_status=None, plan_digest=None, resolved=False):
        with self.sessions() as session:
            lock_connection(session)
            row = self.owned(session, attempt_id, actor_id, expected_version)
            if row.phase not in expected_phases or row.resolved:
                raise SetupError("SETUP_PHASE_CONFLICT", "현재 등록 단계에서 실행할 수 없습니다.")
            self._advance(session, row, phase=phase, operation_status=operation_status,
                          plan_digest=plan_digest, resolved=resolved)
            return public_attempt(row)

    def _advance(self, session, row, *, phase, operation_status=None, plan_digest=None, resolved=False):
        self.operation_store(session).append_in_session(
            session, row.operation_id, next_status=operation_status,
            event_type="proxmox_registration_" + phase, stage=phase,
            payload={"attempt_id": row.attempt_id, "revision_id": row.revision_id},
            details_patch={"phase": phase}, is_transition=operation_status is not None,
        )
        row.phase = phase
        row.resolved = resolved
        row.version += 1
        if plan_digest is not None:
            row.plan_digest = plan_digest
        session.flush()

    def stage_secret(self, *, attempt_id, actor_id, expected_version, token_secret, token_id):
        cipher = self.cipher_factory()
        with self.sessions() as session:
            lock_connection(session)
            row = self.owned(session, attempt_id, actor_id, expected_version)
            if row.phase not in {"token_dispatching", "import_staging"} or row.revision_id is not None:
                raise SetupError("SETUP_PHASE_CONFLICT", "발급 중인 요청에만 인증정보를 저장할 수 있습니다.")
            imported = row.intent.get("mode") == "import_env"
            expected_token_id = row.intent["owner"] + "!gjallar-" + row.attempt_id
            if ((imported and (row.phase != "import_staging" or not token_id.startswith(row.intent["owner"] + "!")))
                    or (not imported and (row.phase != "token_dispatching" or token_id != expected_token_id))):
                raise SetupError("SETUP_TOKEN_ID_CONFLICT", "발급된 token identity가 요청과 다릅니다.")
            connection = session.get(ProxmoxConnectionRecord, 1)
            revision_id = str(uuid.uuid4())
            configuration = {**row.intent, "token_id": token_id, "origin": "imported" if imported else "issued"}
            nonce, ciphertext = cipher.encrypt(token_secret, installation_id=connection.installation_id,
                connection_id=connection.connection_id, revision_id=revision_id, metadata=configuration)
            credential = ProxmoxCredentialRecord(revision_id=revision_id, connection_id=connection.connection_id,
                configuration=configuration, state="pending", format_version=1,
                key_id=cipher.key_id, nonce=nonce, ciphertext=ciphertext)
            session.add(credential)
            session.flush()
            row.revision_id = revision_id
            self._advance(session, row, phase="secret_staged", operation_status="running")
            return public_attempt(row)

    def pending_credential(self, *, attempt_id, actor_id):
        with self.sessions() as session:
            row = self.owned(session, attempt_id, actor_id)
            credential = session.get(ProxmoxCredentialRecord, row.revision_id) if row.revision_id else None
            connection = session.get(ProxmoxConnectionRecord, 1)
            if credential is None or credential.state != "pending" or credential.ciphertext is None:
                raise SetupError("SETUP_CREDENTIAL_UNAVAILABLE", "검증할 인증정보가 없습니다.")
            return dict(credential.configuration), decrypt_credential(self.cipher_factory(), connection, credential)

    def activate(self, *, attempt_id, actor_id, expected_version):
        from app.setup_integration.runtime import pin_selection

        with self.sessions() as session:
            lock_connection(session)
            row = self.owned(session, attempt_id, actor_id, expected_version)
            connection = session.get(ProxmoxConnectionRecord, 1)
            if row.phase != "verified" or connection.version != row.expected_connection_version:
                raise SetupError("SETUP_ACTIVATION_CONFLICT", "검증 단계 또는 현재 연결 버전이 변경됐습니다.")
            if self.operation_store(session).has_unfinished_coordination(session, excluding_operation_id=row.operation_id):
                raise SetupError("SETUP_WORK_IN_PROGRESS", "미완결 작업·잠금·복구가 있습니다. 기존 연결을 유지합니다.")
            credential = session.get(ProxmoxCredentialRecord, row.revision_id)
            if credential is None or credential.state != "pending":
                raise SetupError("SETUP_CREDENTIAL_UNAVAILABLE", "검증된 인증정보가 없습니다.")
            decrypt_credential(self.cipher_factory(), connection, credential)
            pin_selection(session.get_bind(), connection)
            if connection.active_revision_id:
                previous = session.get(ProxmoxCredentialRecord, connection.active_revision_id)
                if previous.state == "active":
                    previous.state = "retiring"
                session.flush()
            credential.state = "active"
            connection.active_revision_id = credential.revision_id
            connection.source = "managed"
            connection.admission = "open"
            connection.version += 1
            self._advance(session, row, phase="active", operation_status="succeeded", resolved=True)
            return {**public_attempt(row), "restart_required": True}

    def begin_revoke(self, *, attempt_id, actor_id, expected_version):
        with self.sessions() as session:
            lock_connection(session)
            row = self.owned(session, attempt_id, actor_id, expected_version)
            connection = session.get(ProxmoxConnectionRecord, 1)
            if row.intent.get("mode") == "import_env":
                raise SetupError("SETUP_IMPORTED_TOKEN_PRESERVED", "가져온 외부 token은 자동 폐기하지 않습니다.")
            if row.phase in {"prepared", "authenticated", "mfa_required", "planned", "cancelled", "revoked", "revocation_pending"}:
                raise SetupError("SETUP_PHASE_CONFLICT", "현재 단계에서는 새 폐기 요청을 실행할 수 없습니다.")
            is_active = row.revision_id is not None and row.revision_id == connection.active_revision_id
            store = self.operation_store(session)
            if is_active:
                if store.has_unfinished_coordination(session, excluding_operation_id=row.operation_id):
                    raise SetupError("SETUP_WORK_IN_PROGRESS", "미완결 작업·잠금·복구가 있어 활성 token을 폐기하지 않습니다.")
                connection.admission = "closed"
            operation_id = "proxmox-revocation-" + row.attempt_id
            store.create(OperationSpec(operation_id=operation_id, operation_type="proxmox_credential_revocation",
                execution_mode="managed_api", target_type="proxmox_connection", target_id=row.connection_id,
                idempotency_key=digest(operation_id), intent_digest=digest(row.attempt_id), plan_digest=digest(row.attempt_id),
                actor=OperationActor(user_id=actor_id, role="admin"), details={"attempt_id": row.attempt_id}))
            store.append_in_session(session, operation_id, next_status="dispatching", event_type="revocation_requested",
                stage="revocation_pending", payload={"attempt_id": row.attempt_id}, is_transition=True)
            row.revocation_operation_id = operation_id
            row.phase = "revocation_pending"
            row.version += 1
            session.flush()
            return public_attempt(row)

    def finish_revoke(self, *, attempt_id, actor_id, expected_version):
        with self.sessions() as session:
            lock_connection(session)
            row = self.owned(session, attempt_id, actor_id, expected_version)
            if row.phase != "revocation_pending" or not row.revocation_operation_id:
                raise SetupError("SETUP_PHASE_CONFLICT", "폐기 결과를 확인할 요청이 없습니다.")
            store = self.operation_store(session)
            for status in ("running", "verifying", "succeeded"):
                store.append_in_session(session, row.revocation_operation_id, next_status=status,
                    event_type="revocation_" + status, stage="revoked", payload={"attempt_id": row.attempt_id}, is_transition=True)
            if row.revision_id:
                credential = session.get(ProxmoxCredentialRecord, row.revision_id)
                credential.state = "revoked"
                credential.ciphertext = None
            original = store.get(row.operation_id)
            failure_status = None if original.status == "succeeded" else "failed"
            self._advance(session, row, phase="revoked", operation_status=failure_status, resolved=True)
            return public_attempt(row)


def decrypt_credential(cipher, connection, credential):
    if credential.format_version != 1 or credential.connection_id != connection.connection_id or credential.ciphertext is None:
        raise CredentialKeyError("인증정보 연결 또는 저장 형식이 올바르지 않습니다.")
    return cipher.decrypt(nonce=credential.nonce, ciphertext=credential.ciphertext, key_id=credential.key_id,
        installation_id=connection.installation_id, connection_id=connection.connection_id,
        revision_id=credential.revision_id, metadata=credential.configuration)
