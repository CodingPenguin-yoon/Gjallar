import json
import os
import time
import uuid
from urllib.parse import quote

import pytest
from sqlalchemy import select

from app.db.session import session_scope
from app.operations.core.domain import OperationActor
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.setup_integration.contracts import RegistrationIntent, SetupError
from app.setup_integration.crypto import CredentialCipher
from app.setup_integration.models import ProxmoxCredentialRecord
from app.setup_integration.planning import ROLE_PRIVILEGES
from app.setup_integration.registration import RegistrationService
from app.setup_integration.repository import RegistrationRepository


class FakeProxmox:
    def __init__(self):
        self.calls = []
        self.token = None
        self.token_secret = "synthetic-issued-secret"
        self.fail_issue = False
        self.fail_acl = False
        self.fail_revoke = False
        self.totp = False
        self.roles = {}
        self.granted = set()

    def request(self, method, path, *, data=None, **kwargs):
        self.calls.append((method, path, data, kwargs))
        if path == "/access/ticket":
            if self.totp and "tfa-challenge" not in data:
                ticket = "PVE:!tfa!" + quote(json.dumps({"totp": True}), safe="") + ":fake-signature"
                return {"username": "test@pve", "ticket": ticket, "CSRFPreventionToken": "synthetic-csrf"}
            if "tfa-challenge" in data:
                assert data["password"] == "totp:123456" and "otp" not in data
            return {"username": "test@pve", "ticket": "PVE:synthetic-ticket", "CSRFPreventionToken": "synthetic-csrf"}
        if path == "/version":
            return {"version": "9.0.11", "release": "9.0", "repoid": "fixture-only"}
        if path == "/access/users/test%40pve":
            return {"enable": 1, "expire": 0}
        if path.endswith("/token"):
            return [self.token] if self.token else []
        if "/token/gjallar-" in path and method == "POST":
            self.token = {"tokenid": path.split("/")[-1], **data}
            if self.fail_issue:
                raise SetupError("PROXMOX_COMMUNICATION_FAILED", "lost response", 502)
            return {"full-tokenid": "test@pve!" + self.token["tokenid"], "value": self.token_secret}
        if "/token/gjallar-" in path and method == "DELETE":
            self.token = None
            if self.fail_revoke:
                raise SetupError("PROXMOX_COMMUNICATION_FAILED", "lost delete response", 502)
            return None
        if path == "/access/roles":
            if method == "POST":
                self.roles[data["roleid"]] = data["privs"].split()
                return None
            return [{"roleid": name} for name in self.roles]
        if path.startswith("/access/roles/"):
            return dict.fromkeys(self.roles[path.split("/")[-1]], 1)
        if path == "/access/permissions":
            if kwargs.get("secret"):
                privileges = set()
                for acl_path, role in self.granted:
                    if acl_path == data["path"]:
                        privileges.update(ROLE_PRIVILEGES[role])
                return {data["path"]: dict.fromkeys(privileges, 0)}
            return {data["path"]: dict.fromkeys({p for ps in ROLE_PRIVILEGES.values() for p in ps} | {"Sys.Modify", "Permissions.Modify"}, 0)}
        if path == "/access/acl":
            if self.fail_acl:
                raise SetupError("PROXMOX_COMMUNICATION_FAILED", "lost ACL response", 502)
            self.granted.add((data["path"], data["roles"]))
            return None
        if path == "/nodes":
            return [{"node": "node1"}]
        if path == "/nodes/node1/qemu":
            return [{"vmid": 101}]
        if path == "/nodes/node1/qemu/101/config":
            return {"memory": 1024}
        raise AssertionError((method, path))


@pytest.fixture
def flow():
    cipher = CredentialCipher(os.urandom(32))
    repository = RegistrationRepository(cipher_factory=lambda: cipher)
    fake = FakeProxmox()
    service = RegistrationService(repository, transport_factory=lambda *args: fake)
    intent = RegistrationIntent(endpoint="https://pve.example.test", owner="test@pve",
        scope={"nodes": ["node1"], "vmids": [101]}, expires_at=int(time.time()) + 86400)
    row = repository.prepare(intent=intent, idempotency_key="test-request", actor=OperationActor(user_id="admin", role="admin"),
        installation_id=str(uuid.uuid4()), cluster_id="gjallar-mvp")
    return service, fake, row


def args(row, **extra):
    return dict(attempt_id=row["attempt_id"], actor_id="admin", session_id="session-one", expected_version=row["version"], **extra)


def login_and_plan(service, row):
    row = service.login(**args(row, password="synthetic-password"))
    return service.plan(**args(row))


def test_registration_complete_until_explicit_activation(flow):
    service, fake, row = flow
    planned = login_and_plan(service, row)
    assert planned["plan"]["can_confirm"] is True
    verified = service.confirm(**args(planned, plan_digest=planned["plan_digest"]))
    assert verified["phase"] == "verified"
    assert verified["observed_scope"] == {"nodes": ["node1"], "vmids": [101]}
    with session_scope() as session:
        assert session.scalar(select(ProxmoxCredentialRecord)).state == "pending"
    active = service.activate(attempt_id=row["attempt_id"], actor_id="admin", expected_version=verified["version"])
    assert active["phase"] == "active" and active["restart_required"]
    public = json.dumps(active) + str(SqlAlchemyOperationStore().list_events(row["operation_id"]))
    assert all(secret not in public for secret in ("synthetic-password", "synthetic-issued-secret", "synthetic-ticket"))


def test_totp_is_session_bound_and_not_durable(flow):
    service, fake, row = flow
    fake.totp = True
    row = service.login(**args(row, password="synthetic-password"))
    assert row["mfa_required"]
    with pytest.raises(SetupError, match="같은 Gjallar"):
        service.mfa(**{**args(row, otp="123456"), "session_id": "other-session"})
    row = service.mfa(**args(row, otp="123456"))
    assert row["phase"] == "authenticated"
    service.invalidate_session("session-one")
    assert service.status(row["attempt_id"], "admin", "session-one")["reauth_required"]
    with pytest.raises(SetupError):
        service.plan(**args(row))


def test_lost_issue_response_never_reissues_and_observation_preserves_uncertainty(flow):
    service, fake, row = flow
    planned = login_and_plan(service, row)
    fake.fail_issue = True
    with pytest.raises(SetupError):
        service.confirm(**args(planned, plan_digest=planned["plan_digest"]))
    current = service.repository.get(row["attempt_id"], "admin")
    assert current["phase"] == "token_dispatching"
    with pytest.raises(SetupError):
        service.confirm(**args(current, plan_digest=planned["plan_digest"]))
    observation = service.observe(**args(current))
    assert observation["token_exists"] and observation["token_matches_attempt"]
    assert not observation["secret_recoverable"] and not observation["automatic_retry_allowed"]
    assert len([call for call in fake.calls if call[0] == "POST" and "/token/gjallar-" in call[1]]) == 1


def test_acl_failure_retains_staged_secret_and_old_source(flow):
    service, fake, row = flow
    planned = login_and_plan(service, row)
    fake.fail_acl = True
    with pytest.raises(SetupError):
        service.confirm(**args(planned, plan_digest=planned["plan_digest"]))
    current = service.repository.get(row["attempt_id"], "admin")
    assert current["phase"] == "acl_applying"
    with pytest.raises(SetupError):
        service.verify(attempt_id=row["attempt_id"], actor_id="admin", expected_version=current["version"])
    with session_scope() as session:
        assert session.scalar(select(ProxmoxCredentialRecord)).state == "pending"
    with pytest.raises(SetupError):
        service.cancel(attempt_id=row["attempt_id"], actor_id="admin", expected_version=current["version"])


def test_rate_limit_and_context_expiry(flow):
    service, fake, row = flow
    now = [10.0]
    service.clock = lambda: now[0]
    for _ in range(5):
        row = service.login(**args(row, password="synthetic-password"))
    with pytest.raises(SetupError) as failure:
        service.login(**args(row, password="synthetic-password"))
    assert failure.value.status == 429
    now[0] = 311
    assert service.status(row["attempt_id"], "admin", "session-one")["reauth_required"]


def test_env_import_does_not_issue_or_change_acl(flow, monkeypatch):
    service, fake, row = flow
    service.cancel(attempt_id=row["attempt_id"], actor_id="admin", expected_version=row["version"])
    original = service.repository.intent(row["attempt_id"], "admin")
    imported = original.model_copy(update={"mode": "import_env"})
    from app.setup_integration.models import ProxmoxConnectionRecord
    with session_scope() as session:
        install_id = session.get(ProxmoxConnectionRecord, 1).installation_id
    row = service.repository.prepare(intent=imported, idempotency_key="env-import-request",
        actor=OperationActor(user_id="admin", role="admin"), installation_id=install_id, cluster_id="gjallar-mvp")
    monkeypatch.setenv("PROXMOX_API_URL", imported.endpoint)
    monkeypatch.setenv("PROXMOX_API_TOKEN_ID", "test@pve!existing")
    monkeypatch.setenv("PROXMOX_API_TOKEN_SECRET", "synthetic-env-secret")
    monkeypatch.setenv("PROXMOX_TLS_INSECURE", "false")
    fake.granted = {("/nodes/node1", "GjallarNodeReadV1"), ("/vms/101", "GjallarVmReadV1")}
    row = service.import_plan(attempt_id=row["attempt_id"], actor_id="admin", expected_version=row["version"])
    assert row["plan"]["upstream_changes"] is False
    row = service.import_env(attempt_id=row["attempt_id"], actor_id="admin", expected_version=row["version"], plan_digest=row["plan_digest"])
    assert row["phase"] == "verified"
    assert all(call[0] == "GET" for call in fake.calls)
    with session_scope() as session:
        credential = session.scalar(select(ProxmoxCredentialRecord))
        assert credential.configuration["origin"] == "imported"
    with pytest.raises(SetupError, match="외부 token"):
        service.repository.begin_revoke(attempt_id=row["attempt_id"], actor_id="admin", expected_version=row["version"])


def test_activation_refuses_unfinished_work_and_stale_runtime(flow, monkeypatch, tmp_path):
    service, fake, row = flow
    planned = login_and_plan(service, row)
    verified = service.confirm(**args(planned, plan_digest=planned["plan_digest"]))
    from app.operations.core.domain import OperationSpec
    store = SqlAlchemyOperationStore()
    store.create(OperationSpec(operation_id="unfinished", operation_type="vm_start", execution_mode="managed_api",
        target_type="proxmox_vm", target_id="vmid:102", idempotency_key="pending", intent_digest="intent", plan_digest="plan",
        actor=OperationActor(user_id="admin", role="admin")))
    with pytest.raises(SetupError, match="미완결"):
        service.repository.activate(attempt_id=row["attempt_id"], actor_id="admin", expected_version=verified["version"])
    store.transition("unfinished", next_status="cancelled", event_type="cancelled", stage="cancelled")
    from app.setup_integration.runtime import selected_credential
    assert selected_credential() is None  # Pins the old env source.
    service.repository.activate(attempt_id=row["attempt_id"], actor_id="admin", expected_version=verified["version"])
    with pytest.raises(SetupError) as result:
        selected_credential()
    assert result.value.code == "SETUP_RESTART_REQUIRED"


def test_lost_revoke_response_is_observed_without_second_delete(flow):
    service, fake, row = flow
    planned = login_and_plan(service, row)
    row = service.confirm(**args(planned, plan_digest=planned["plan_digest"]))
    fake.fail_revoke = True
    with pytest.raises(SetupError):
        service.revoke(**args(row, token_id=row["token_id"]))
    row = service.repository.get(row["attempt_id"], "admin")
    assert row["phase"] == "revocation_pending"
    row = service.revoke(**args(row, token_id=row["token_id"]))
    assert row["phase"] == "revoked" and row["resolved"]
    assert len([call for call in fake.calls if call[0] == "DELETE"]) == 1
    with session_scope() as session:
        credential = session.scalar(select(ProxmoxCredentialRecord))
        assert credential.state == "revoked" and credential.ciphertext is None
    assert SqlAlchemyOperationStore().get(row["revocation_operation_id"]).status == "succeeded"


def test_activation_rechecks_permissions_and_preserves_pending_on_failure(flow):
    service, fake, row = flow
    planned = login_and_plan(service, row)
    row = service.confirm(**args(planned, plan_digest=planned["plan_digest"]))
    fake.granted.clear()
    with pytest.raises(SetupError, match="권한 검증"):
        service.activate(attempt_id=row["attempt_id"], actor_id="admin", expected_version=row["version"])
    with session_scope() as session:
        assert session.scalar(select(ProxmoxCredentialRecord)).state == "pending"


def test_expired_or_logged_out_context_cannot_dispatch(flow):
    service, fake, row = flow
    row = login_and_plan(service, row)
    context = service.context(row["attempt_id"], "admin", "session-one")
    service.invalidate_session("session-one")
    count = len(fake.calls)
    with pytest.raises(SetupError):
        context.request("POST", "/access/roles", data={})
    assert len(fake.calls) == count
