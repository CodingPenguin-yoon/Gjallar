from dataclasses import replace
import pytest
from sqlalchemy import select
from app.db.models import OperationLockRecord
from app.db.session import session_scope
from app.operations.core.domain import OperationActor, OperationSpec, OperationIntentConflict
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.host_config.admission import HostConfigurationAdmission
from app.operations.host_config.domain import target_identity
from app.operations.host_config.infrastructure import ConfigurationLockRepository
from app.operations.locks.domain import DurableTargetLockBusy
from app.operations.locks.infrastructure.repository import SqlAlchemyDurableTargetLockRepository
from app.operations.recovery.domain import RecoveryOperationConflict, RecoveryLeaseLost
from app.operations.recovery.infrastructure.models import OperationRecoveryItemRecord
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore


def spec(kind='host_storage', identity='host-test'):
    target = {'node_id': 'node1', **({'storage_id': 'local-new'} if kind == 'host_storage' else {'bridge_id': 'vmbr9'})}
    target_type, target_id = target_identity(kind, target)
    return OperationSpec(operation_id=identity, operation_type=kind, execution_mode='managed_api',
        target_type=target_type, target_id=target_id, idempotency_key=identity,
        intent_digest='sha256:'+'a'*64, plan_digest='sha256:'+'a'*64, actor=OperationActor(),
        details={'target': target, 'mutation_dispatched': False})


def prepare(kind='host_storage'):
    return HostConfigurationAdmission().prepare(spec(kind), cluster_id='gjallar-mvp')


def finish(lease):
    return SqlAlchemyRecoveryStore().commit_observation(lease, next_status='blocked', event_type='precheck_no_effect',
        stage='precheck', expected_statuses=['planned'], recovery_status='completed', release_target_lock=True)


@pytest.mark.parametrize('kind', ['host_storage','host_network'])
def test_host_admission_is_atomic_and_idempotent_without_fake_vmid(kind):
    operation, lease = prepare(kind)
    assert operation.target_type != 'proxmox_vm' and lease.item.recovery_kind == kind+'_observation'
    held = ConfigurationLockRepository().current(cluster_id='gjallar-mvp')
    assert held.to_dict()['vmid'] is None and held.owner_id == operation.operation_id
    replay, no_lease = prepare(kind)
    assert replay == operation and no_lease is None
    with pytest.raises(OperationIntentConflict):
        HostConfigurationAdmission().prepare(replace(spec(kind), intent_digest='sha256:'+'b'*64), cluster_id='gjallar-mvp')
    finish(lease)
    assert ConfigurationLockRepository().current(cluster_id='gjallar-mvp') is None
    assert prepare(kind)[1] is None


def test_vm_cannot_enter_during_host_configuration():
    _, lease = prepare()
    with pytest.raises(DurableTargetLockBusy) as error:
        SqlAlchemyDurableTargetLockRepository().acquire(operation_type='vm_compute', cluster_id='gjallar-mvp', vmid=40000,
            owner_id='vm-test', reason='test')
    assert error.value.existing['reason'] == 'HOST_CONFIGURATION_IN_PROGRESS'
    finish(lease)
    assert SqlAlchemyDurableTargetLockRepository().acquire(operation_type='vm_compute', cluster_id='gjallar-mvp', vmid=40000,
        owner_id='vm-test', reason='test').vmid == 40000


def test_host_cannot_enter_while_any_vm_coordination_remains_open():
    repository = SqlAlchemyDurableTargetLockRepository()
    held = repository.acquire(operation_type='vm_compute', cluster_id='gjallar-mvp', vmid=40000, owner_id='vm-test', reason='test')
    with pytest.raises(DurableTargetLockBusy): prepare()
    assert SqlAlchemyOperationStore().get('host-test') is None
    repository.release(held, reason='test_completed')
    assert prepare()[1] is not None


def test_host_creation_rolls_back_lock_and_operation_when_recovery_fails(monkeypatch):
    def fail(*args, **kwargs): raise RuntimeError('synthetic rollback')
    monkeypatch.setattr(SqlAlchemyRecoveryStore,'prepare_and_claim',fail)
    with pytest.raises(RuntimeError, match='synthetic'): prepare()
    assert ConfigurationLockRepository().current(cluster_id='gjallar-mvp') is None
    assert SqlAlchemyOperationStore().get('host-test') is None


@pytest.mark.parametrize('damage', ['lock_id','cluster','target','owner','evidence','scope_key','recovery_type',
    'recovery_kind','operation_target','execution_mode'])
def test_corrupt_host_binding_cannot_dispatch_complete_or_release(damage):
    operation, lease = prepare()
    with session_scope() as session:
        recovery = session.get(OperationRecoveryItemRecord, operation.operation_id)
        lock = session.scalar(select(OperationLockRecord))
        if damage == 'lock_id': recovery.details = {**recovery.details, 'target_lock_id':'other'}
        if damage == 'cluster': recovery.details = {**recovery.details, 'cluster_id':'other'}
        if damage == 'target': recovery.details = {**recovery.details, 'target':{'node_id':'node2','storage_id':'local-new'}}
        if damage == 'owner': lock.owner_id = 'other'
        if damage == 'evidence': lock.evidence = {**lock.evidence, 'target_id':'storage:other'}
        if damage == 'scope_key': lock.scope_key = 'other'
        if damage == 'recovery_type': recovery.details = {**recovery.details, 'operation_type':'host_network'}
        if damage == 'recovery_kind': recovery.recovery_kind = 'host_network_observation'
        if damage == 'execution_mode':
            from app.operations.core.infrastructure.models import OperationRecord
            session.get(OperationRecord,operation.operation_id).execution_mode = 'guided_manual'
        if damage == 'operation_target':
            from app.operations.core.infrastructure.models import OperationRecord
            row = session.get(OperationRecord,operation.operation_id);row.target_id='storage:other'
    store = SqlAlchemyRecoveryStore()
    with pytest.raises(RecoveryOperationConflict):
        store.commit_observation(lease, next_status='dispatching', event_type='must_not_dispatch', stage='dispatch',
            expected_statuses=['planned'], recovery_status='leased')
    with pytest.raises(RecoveryOperationConflict): finish(lease)
    store.commit_observation(lease, event_type='binding_unavailable', stage='reconciliation',
        expected_statuses=['planned'], recovery_status='paused', error_code='HOST_BINDING_INVALID')
    assert SqlAlchemyOperationStore().get(operation.operation_id).status == 'planned'
    with session_scope() as session: assert session.scalar(select(OperationLockRecord)).status == 'active'


@pytest.mark.parametrize('field,value', [('target_lock_id','other'), ('cluster_id','other'),
    ('scope_key','other'), ('target_type','proxmox_vm'), ('target_id','storage:other'),
    ('target',{'node_id':'node2','storage_id':'local-new'}), ('operation_type','host_network'),
    ('execution_mode','guided'), ('related_target_locks',[{'vmid':40000}]), ('vmid',40000)])
@pytest.mark.parametrize('ledger', ['operation','recovery','projected_operation','projected_recovery'])
def test_host_checkpoint_cannot_rewrite_admitted_binding(field, value, ledger):
    operation, lease = prepare()
    arguments = {}
    patch = {field:value}
    if ledger == 'operation': arguments['details_patch'] = patch
    elif ledger == 'recovery': arguments['recovery_details_patch'] = patch
    else:
        key = 'operation_details_patch' if ledger == 'projected_operation' else 'recovery_details_patch'
        arguments['projector'] = lambda session: {key:patch}
    store = SqlAlchemyRecoveryStore()
    with pytest.raises(RecoveryOperationConflict):
        store.commit_observation(lease,event_type='invalid_checkpoint',stage='dispatch',next_status='dispatching',
            expected_statuses=['planned'],recovery_status='leased',**arguments)
    assert SqlAlchemyOperationStore().get(operation.operation_id) == operation
    assert store.get(operation.operation_id).details == lease.item.details
    assert ConfigurationLockRepository().current(cluster_id='gjallar-mvp').status == 'active'
    finish(lease)


def test_host_checkpoint_keeps_binding_while_recording_observation():
    operation, lease = prepare()
    store = SqlAlchemyRecoveryStore()
    patch = {'target': operation.details['target'], 'observed_stage':'precheck'}
    result, recovery = store.commit_observation(lease,event_type='host_precheck_observed',stage='precheck',
        expected_statuses=['planned'],recovery_status='leased',details_patch=patch,recovery_details_patch=patch)
    assert result.details['observed_stage'] == recovery.details['observed_stage'] == 'precheck'
    finish(lease)


def test_expired_host_lease_cannot_dispatch():
    from datetime import datetime, timedelta, timezone
    _, lease = prepare()
    with session_scope() as session:
        row = session.get(OperationRecoveryItemRecord, lease.operation_id)
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    with pytest.raises(RecoveryLeaseLost):
        SqlAlchemyRecoveryStore().commit_observation(lease, next_status='dispatching', event_type='dispatch', stage='dispatch', recovery_status='leased')


def test_host_targets_cannot_use_vm_types_or_ambiguous_identifiers():
    for kind, target in [('vm_compute', {'node_id':'node1','storage_id':'s'}),
        ('host_network', {'node_id':'node1','bridge_id':'eth0'}), ('host_storage', {'node_id':'../node','storage_id':'s'})]:
        with pytest.raises(ValueError): target_identity(kind,target)
    with pytest.raises(ValueError):
        HostConfigurationAdmission().prepare(replace(spec(),target_type='proxmox_vm',target_id='vmid:40000'),cluster_id='gjallar-mvp')


@pytest.mark.parametrize('kind', ['host_storage', 'host_network'])
def test_host_lock_is_visible_and_preserved_by_connection_drain(kind):
    from app.operations.target_lock import get_target_operation_lock
    operation, lease = prepare(kind)
    lock = get_target_operation_lock(operation.target_type, operation.target_id)
    assert lock['owner_id'] == operation.operation_id
    assert lock['durable']['vmid'] is None
    assert get_target_operation_lock(operation.target_type, operation.target_id + '-other') is None
    with session_scope() as session:
        assert SqlAlchemyOperationStore().has_unfinished_coordination(session, excluding_operation_id='registration-test')
    finish(lease)
    assert get_target_operation_lock(operation.target_type, operation.target_id) is None
    with session_scope() as session:
        assert not SqlAlchemyOperationStore().has_unfinished_coordination(session, excluding_operation_id='registration-test')
