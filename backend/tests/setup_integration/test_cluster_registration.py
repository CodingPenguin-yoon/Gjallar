"""Whole-cluster registration and future-resource boundaries, without live PVE writes."""
import json
import os
import time
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.db.session import session_scope, get_engine
from app.operations.core.domain import OperationActor
from app.setup_integration.contracts import RegistrationIntent, SetupError, FEATURES
from app.setup_integration.crypto import CredentialCipher
from app.setup_integration.models import ProxmoxCredentialRecord
from app.setup_integration.registration import RegistrationService
from app.setup_integration.repository import RegistrationRepository
from app.setup_integration import runtime
from test_registration import FakeProxmox, args, login_and_plan


def intent(**changes):
    return RegistrationIntent(**dict(endpoint='https://pve.example.test', owner='root@pam',
        scope={}, access_mode='cluster', expires_at=int(time.time()) + 86400, **changes))


@pytest.fixture
def cluster(monkeypatch):
    cipher = CredentialCipher(os.urandom(32))
    monkeypatch.setattr(CredentialCipher, 'configured', lambda: cipher)
    repository = RegistrationRepository(cipher_factory=lambda: cipher)
    fake = FakeProxmox(owner='root@pam')
    fake.creation_enabled = True
    service = RegistrationService(repository, transport_factory=lambda *args: fake)
    row = repository.prepare(intent=intent(), idempotency_key='whole-cluster',
        actor=OperationActor(user_id='admin', role='admin'), installation_id=str(uuid.uuid4()), cluster_id='gjallar-mvp')
    return service, fake, row


def test_cluster_token_is_separated_encrypted_and_admits_future_resources(cluster):
    service, fake, row = cluster
    plan = login_and_plan(service, row)
    assert plan['plan']['acls'] == [{'path': '/', 'role': 'GjallarClusterV1', 'propagate': 1}]
    assert set(plan['plan']['features']) == FEATURES
    assert plan['plan']['privsep'] == 1
    verified = service.confirm(**args(plan, plan_digest=plan['plan_digest']))
    assert verified['observed_scope'] == {'nodes': ['node1'], 'access_mode': 'cluster'}
    active = service.activate(attempt_id=row['attempt_id'], actor_id='admin', expected_version=verified['version'])
    assert active['phase'] == 'active' and active['restart_required']
    with session_scope() as session:
        credential = session.scalar(select(ProxmoxCredentialRecord))
        assert credential.configuration['access_mode'] == 'cluster'
        assert not any(credential.configuration['scope'].values())
        assert fake.token_secret not in str(credential.__dict__)
    runtime._pins.pop(get_engine(), None)  # Emulate the explicitly required process restart.
    with session_scope() as session:
        for operation in ('vm_start', 'vm_create', 'vm_clone', 'vm_restore', 'vm_template', 'vm_image_build', 'vm_delete'):
            runtime.admit_mutation(session, cluster_id='gjallar-mvp', vmid=65001, operation_type=operation)
        runtime.admit_host_mutation(session, cluster_id='gjallar-mvp', operation_type='host_network',
                                   target={'node_id': 'future-node', 'bridge_id': 'vmbr99'})
        runtime.admit_host_mutation(session, cluster_id='gjallar-mvp', operation_type='host_storage',
                                   target={'node_id': 'future-node', 'storage_id': 'future-store'})
        with pytest.raises(SetupError):
            runtime.admit_mutation(session, cluster_id='gjallar-mvp', vmid=65001, operation_type='raw_shell')
    assert runtime.console_selection(node_id='future-node', vmid=65001)
    assert 'synthetic-password' not in json.dumps(active)


@pytest.mark.parametrize('phase', ['issue', 'acl'])
def test_cluster_partial_failure_never_reissues_token(cluster, phase):
    service, fake, row = cluster
    planned = login_and_plan(service, row)
    setattr(fake, 'fail_' + phase, True)
    with pytest.raises(SetupError):
        service.confirm(**args(planned, plan_digest=planned['plan_digest']))
    with pytest.raises(SetupError):
        service.confirm(**args(planned, plan_digest=planned['plan_digest']))
    assert sum(method == 'POST' and '/token/gjallar-' in path for method, path, _, _ in fake.calls) == 1


def test_cluster_is_explicit_and_cannot_silently_expand_scoped_intent():
    for changes in ({'access_mode': 'scoped'}, {'scope': {'nodes': ['node1']}}, {'mode': 'import_env'},
                    {'certificate_sha256': 'invalid'}):
        values = intent().model_dump()
        with pytest.raises(ValidationError):
            RegistrationIntent(**{**values, **changes})
