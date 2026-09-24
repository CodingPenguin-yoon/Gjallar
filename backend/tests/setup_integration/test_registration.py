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
    def __init__(self, owner="test@pve"):
        self.owner = owner
        self.calls = []
        self.token = None
        self.token_secret = "synthetic-issued-secret"
        self.fail_issue = False
        self.fail_acl = False
        self.fail_revoke = False
        self.totp = False
        self.roles = {}
        self.granted = set()
        self.creation_enabled = False

    def request(self, method, path, *, data=None, **kwargs):
        self.calls.append((method, path, data, kwargs))
        if path == "/access/ticket":
            if self.totp and "tfa-challenge" not in data:
                ticket = "PVE:!tfa!" + quote(json.dumps({"totp": True}), safe="") + ":fake-signature"
                return {"username": self.owner, "ticket": ticket, "CSRFPreventionToken": "synthetic-csrf"}
            if "tfa-challenge" in data:
                assert data["password"] == "totp:123456" and "otp" not in data
            return {"username": self.owner, "ticket": "PVE:synthetic-ticket", "CSRFPreventionToken": "synthetic-csrf"}
        if path == "/version":
            return {"version": "9.0.11", "release": "9.0", "repoid": "fixture-only"}
        if path == "/access/users/" + quote(self.owner, safe=""):
            return {"enable": 1, "expire": 0}
        if path.endswith("/token"):
            return [self.token] if self.token else []
        if "/token/gjallar-" in path and method == "POST":
            self.token = {"tokenid": path.split("/")[-1], **data}
            if self.fail_issue:
                raise SetupError("PROXMOX_COMMUNICATION_FAILED", "lost response", 502)
            return {"full-tokenid": self.owner + "!" + self.token["tokenid"], "value": self.token_secret}
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
            return [{"vmid": 101}, *([{"vmid": 9000}] if self.creation_enabled else [])]
        if path == "/nodes/node1/qemu/101/config":
            return {"memory": 1024}
        if self.creation_enabled:
            resources = {"/nodes/node1/qemu/9000/config": {"template": 1},
                         "/nodes/node1/storage": [{"storage": "store1"}],
                         "/nodes/node1/network": [{"iface": "vmbr0"}]}
            if path in resources:
                return resources[path]
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


@pytest.mark.parametrize('kind,target', [
    ('host_storage', {'node_id':'node1','storage_id':'new-dir'}),
    ('host_network', {'node_id':'node1','bridge_id':'vmbr9'}),
])
def test_existing_managed_connection_never_inherits_host_configuration_permission(flow, monkeypatch, kind, target):
    from app.setup_integration import runtime
    from app.setup_integration.models import ProxmoxConnectionRecord
    from app.db.session import get_engine
    service, _, row = flow
    monkeypatch.setattr(CredentialCipher, 'configured', service.repository.cipher_factory)
    planned = login_and_plan(service, row)
    verified = service.confirm(**args(planned, plan_digest=planned['plan_digest']))
    service.activate(attempt_id=row['attempt_id'], actor_id='admin', expected_version=verified['version'])
    arguments = dict(cluster_id='gjallar-mvp', operation_type=kind, target=target)
    with session_scope() as session, pytest.raises(SetupError) as failure:
        runtime.admit_host_mutation(session, **arguments)
    assert failure.value.code == 'SETUP_RESTART_REQUIRED'
    runtime._pins.pop(get_engine(), None)
    with session_scope() as session, pytest.raises(SetupError) as failure:
        runtime.admit_host_mutation(session, **arguments)
    assert failure.value.code == 'SETUP_FEATURE_NOT_SELECTED'
    with session_scope() as session:
        session.get(ProxmoxConnectionRecord, 1).admission = 'closed'
    with session_scope() as session, pytest.raises(SetupError) as failure:
        runtime.admit_host_mutation(session, **arguments)
    assert failure.value.code == 'SETUP_ADMISSION_CLOSED'


@pytest.mark.parametrize('feature,scope,role,privileges,action', [
    ('host_network', {'host_bridges':['vmbr40']}, 'GjallarHostNetworkV1', ['Sys.Modify'], 'host_network'),
    ('host_storage', {'host_storages':['new-dir']}, 'GjallarHostStorageV1', ['Datastore.Allocate'], 'host_storage'),
    ('image_cleanup', {'storages': ['store1'], 'image_cleanup_storages': ['store1']},
     'GjallarImageCleanupV1', ['VM.Allocate', 'VM.Audit'], 'vm_image_cleanup'),
    ('image_build', {'storages': ['store1'], 'bridges': ['vmbr0'], 'image_vmids': [40000]},
     'GjallarImageBuildV1', ROLE_PRIVILEGES['GjallarImageBuildV1'], 'vm_image_build'),
    ('template', {'storages': ['store1']}, 'GjallarVmTemplateV2', ['VM.Allocate', 'VM.Config.Disk'], 'vm_template'),
    ('console', {}, 'GjallarVmConsoleV1', ['VM.Console'], 'vm_console'),
    ('delete', {'storages': ['store1']}, 'GjallarVmDeleteV1', ['VM.Allocate'], 'vm_delete'),
    ('compute', {}, 'GjallarVmComputeV1', ['VM.Config.CPU', 'VM.Config.Memory'], 'vm_compute'),
    ('disk', {'storages': ['store1']}, 'GjallarVmDiskV1', ['VM.Config.Disk'], 'vm_disk_resize'),
    ('network', {'bridges': ['vmbr0']}, 'GjallarVmNetworkV1', ['VM.Config.Network'], 'vm_network'),
    ('clone', {'storages': ['store1'], 'bridges': ['vmbr0'], 'clone_vmids': [40000]},
     'GjallarVmCloneTargetV2', ['VM.Allocate', 'VM.Audit', 'VM.Config.Disk'], 'vm_clone'),
])
def test_existing_managed_connection_capability_upgrade_retains_old_revision(flow, monkeypatch, feature, scope, role, privileges, action):
    from app.setup_integration.models import ProxmoxConnectionRecord
    from app.setup_integration import runtime
    from app.db.session import get_engine

    def admit(session, **kwargs):
        if kwargs['operation_type'] == 'host_network':
            return runtime.admit_host_mutation(session, cluster_id=kwargs['cluster_id'], operation_type='host_network',
                target={'node_id':'node1', 'bridge_id':'vmbr40' if kwargs['vmid'] == 101 else 'vmbr99'})
        if kwargs['operation_type'] == 'host_storage':
            return runtime.admit_host_mutation(session,cluster_id=kwargs['cluster_id'],operation_type='host_storage',
                target={'node_id':'node1','storage_id':'new-dir' if kwargs['vmid'] == 101 else 'outside'})
        if feature == 'image_build' and kwargs['vmid'] == 101 and kwargs['operation_type'] == action:
            kwargs['vmid'] = 40000
        if kwargs['operation_type'] == 'vm_console':
            return runtime.console_selection(node_id='node1', vmid=kwargs['vmid'])
        return runtime.admit_mutation(session, **kwargs)

    service, fake, row = flow
    fake.creation_enabled = True
    cipher = service.repository.cipher_factory()
    monkeypatch.setattr(CredentialCipher, "configured", lambda: cipher)
    planned = login_and_plan(service, row)
    verified = service.confirm(**args(planned, plan_digest=planned["plan_digest"]))
    active = service.activate(attempt_id=row["attempt_id"], actor_id="admin", expected_version=verified["version"])
    runtime._pins.pop(get_engine(), None)  # First activation also requires restart.
    with session_scope() as session:
        with pytest.raises(SetupError) as failure:
            admit(session, cluster_id="gjallar-mvp", vmid=101, operation_type=action)
        assert failure.value.code == "SETUP_FEATURE_NOT_SELECTED"
        installation_id = session.get(ProxmoxConnectionRecord, 1).installation_id
    original = service.repository.intent(row["attempt_id"], "admin").model_dump()
    intent = RegistrationIntent(**{**original, "features": ["read", feature], "scope": {**original["scope"], **scope}})
    upgraded = service.repository.prepare(intent=intent, idempotency_key=feature + "-upgrade",
        actor=OperationActor(user_id="admin", role="admin"), installation_id=installation_id, cluster_id="gjallar-mvp")
    planned = login_and_plan(service, upgraded)
    assert planned["plan"]["roles"][role] == privileges
    verified = service.confirm(**args(planned, plan_digest=planned["plan_digest"]))
    with session_scope() as session:
        assert session.get(ProxmoxConnectionRecord, 1).active_revision_id == active["revision_id"]
    service.activate(attempt_id=upgraded["attempt_id"], actor_id="admin", expected_version=verified["version"])
    with session_scope() as session:
        assert session.get(ProxmoxCredentialRecord, active["revision_id"]).state == "retiring"
        with pytest.raises(SetupError) as failure:
            admit(session, cluster_id="gjallar-mvp", vmid=101, operation_type=action)
        assert failure.value.code == "SETUP_RESTART_REQUIRED"
    runtime._pins.pop(get_engine(), None)  # Simulate all processes restarting.
    with session_scope() as session:
        admit(session, cluster_id="gjallar-mvp", vmid=101, operation_type=action)
    if feature == "clone":
        with session_scope() as session:
            admit(session, cluster_id="gjallar-mvp", vmid=40000, operation_type=action)
    for vmid, action in ((102, action), (101, "vm_start"), (101, "vm_create"), (40000, "vm_start")):
        with session_scope() as session:
            with pytest.raises(SetupError):
                admit(session, cluster_id="gjallar-mvp", vmid=vmid, operation_type=action)


def test_creation_registration_admits_only_selected_new_vmids(flow, monkeypatch):
    from app.setup_integration import runtime
    from app.db.session import get_engine
    from app.setup_integration.models import ProxmoxConnectionRecord

    service, fake, row = flow
    fake.creation_enabled = True
    service.cancel(attempt_id=row["attempt_id"], actor_id="admin", expected_version=row["version"])
    cipher = service.repository.cipher_factory()
    monkeypatch.setattr(CredentialCipher, "configured", lambda: cipher)
    with session_scope() as session:
        installation_id = session.get(ProxmoxConnectionRecord, 1).installation_id
    intent = RegistrationIntent(endpoint="https://pve.example.test", owner="test@pve",
        scope={"nodes": ["node1"], "vmids": [101], "template_vmids": [9000], "create_vmids": [40000],
               "storages": ["store1"], "bridges": ["vmbr0"]},
        features=["read", "create"], expires_at=int(time.time()) + 86400)
    row = service.repository.prepare(intent=intent, idempotency_key="create-capability",
        actor=OperationActor(user_id="admin", role="admin"), installation_id=installation_id, cluster_id="gjallar-mvp")
    planned = login_and_plan(service, row)
    verified = service.confirm(**args(planned, plan_digest=planned["plan_digest"]))
    assert verified["phase"] == "verified"
    service.activate(attempt_id=row["attempt_id"], actor_id="admin", expected_version=verified["version"])
    runtime._pins.pop(get_engine(), None)
    for action in ("vm_create", "vm_start", "vm_shutdown"):
        with session_scope() as session:
            runtime.admit_mutation(session, cluster_id="gjallar-mvp", vmid=40000, operation_type=action)
    for vmid, action in ((101, "vm_create"), (9000, "vm_create"), (40001, "vm_create"),
                         (101, "vm_start"), (40000, "vm_compute")):
        with session_scope() as session, pytest.raises(SetupError):
            runtime.admit_mutation(session, cluster_id="gjallar-mvp", vmid=vmid, operation_type=action)


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
