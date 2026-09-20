from dataclasses import replace

import pytest
from sqlalchemy import select

from app.db.models import OperationLockRecord
from app.db.session import session_scope
from app.operations.core.domain import OperationActor, OperationSpec
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.locks.domain import DurableTargetLockBusy
from app.operations.locks.infrastructure.repository import SqlAlchemyDurableTargetLockRepository
from app.operations.recovery.application import RecoveryBindingError, _validate_recovery_binding
from app.operations.recovery.domain import RecoveryOperationConflict, RecoveryLease
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.target_lock import get_target_operation_lock
from app.operations.vm_admission import VmMutationAdmission

CLUSTER = 'gjallar-mvp'


def spec(source=40000, destination=40001, operation_id='clone-test'):
    return OperationSpec(operation_id=operation_id, operation_type='vm_clone', execution_mode='managed_api',
        target_type='proxmox_vm', target_id=f'vmid:{destination}', idempotency_key=operation_id,
        intent_digest='sha256:' + 'a' * 64, plan_digest='sha256:' + 'a' * 64, actor=OperationActor(),
        details={'source': {'node_id': 'node1', 'vmid': source}, 'target': {'node_id': 'node1', 'vmid': destination},
                 'mutation_dispatched': False})


def prepare(value):
    return VmMutationAdmission(recovery_kind=value.operation_type + '_observation').prepare(value, cluster_id=CLUSTER,
        vmid=value.details['target']['vmid'], related_vmids=(value.details['source']['vmid'],))


def bound(lease, operation):
    _validate_recovery_binding(lease, operation, recovery_kind=operation.operation_type + '_observation', operation_type=operation.operation_type,
        execution_mode='managed_api', target_lock_reader=get_target_operation_lock)


@pytest.mark.parametrize('source,destination', [(40000, 40001), (40001, 40000)])
def test_two_locks_are_acquired_in_order_and_released_in_one_fenced_commit(source, destination, monkeypatch):
    repository = SqlAlchemyDurableTargetLockRepository()
    acquired = []
    original = SqlAlchemyDurableTargetLockRepository.acquire
    def capture(self, **kwargs):
        acquired.append(kwargs['vmid'])
        return original(self, **kwargs)
    monkeypatch.setattr(SqlAlchemyDurableTargetLockRepository, 'acquire', capture)
    value = spec(source, destination)
    operation, lease = prepare(value)
    assert acquired == [40000, 40001]
    bound(lease, operation)
    for vmid in (source, destination):
        with pytest.raises(DurableTargetLockBusy):
            repository.acquire(operation_type='vm_network', cluster_id=CLUSTER, vmid=vmid, owner_id='other', reason='test')
    recovery = SqlAlchemyRecoveryStore()
    operation, item = recovery.commit_observation(lease, stage='test', next_status='blocked', event_type='clone_precheck_blocked',
        expected_statuses=['planned'], recovery_status='completed', release_target_lock=True)
    assert operation.status == 'blocked' and item.status == 'completed'
    assert all(repository.current(cluster_id=CLUSTER, vmid=vmid) is None for vmid in (source, destination))
    replay, no_lease = prepare(value)
    assert no_lease is None and replay.operation_id == operation.operation_id
    with session_scope() as session:
        assert len(list(session.scalars(select(OperationLockRecord)))) == 2


def test_second_busy_lock_rolls_back_first_and_all_operation_records():
    repository = SqlAlchemyDurableTargetLockRepository()
    repository.acquire(operation_type='vm_start', cluster_id=CLUSTER, vmid=40001, owner_id='other', reason='test')
    with pytest.raises(DurableTargetLockBusy):
        prepare(spec())
    assert repository.current(cluster_id=CLUSTER, vmid=40000) is None
    assert not SqlAlchemyOperationStore().list()
    assert SqlAlchemyRecoveryStore().get('clone-test') is None


@pytest.mark.parametrize('damage', ['released_source', 'wrong_owner', 'wrong_reference'])
def test_incomplete_binding_never_releases_remaining_lock_or_advances_state(damage):
    operation, lease = prepare(spec())
    source_id = operation.details['related_target_locks'][0]['lock_id']
    if damage == 'wrong_reference':
        lease = replace(lease, item=replace(lease.item, details={**lease.item.details,
            'related_target_locks': [{'vmid': 40000, 'lock_id': 'foreign'}]}))
    else:
        with session_scope() as session:
            source = session.get(OperationLockRecord, source_id)
            if damage == 'released_source':
                source.status = 'released'
            else:
                source.owner_id = 'other'
    with pytest.raises(RecoveryBindingError):
        bound(lease, operation)
    if damage != 'wrong_reference':
        with pytest.raises(RecoveryOperationConflict):
            SqlAlchemyRecoveryStore().commit_observation(lease, stage='test', next_status='blocked', event_type='bad_complete',
                recovery_status='completed', expected_statuses=['planned'], release_target_lock=True)
        assert SqlAlchemyOperationStore().get(operation.operation_id).status == 'planned'
    assert SqlAlchemyDurableTargetLockRepository().current(cluster_id=CLUSTER, vmid=40001) is not None


def test_verified_success_releases_both_locks():
    operation, lease = prepare(spec())
    recovery = SqlAlchemyRecoveryStore()
    for state in ('dispatching', 'running', 'verifying'):
        operation, item = recovery.commit_observation(lease, stage='test', next_status=state, event_type='clone_' + state,
            recovery_status='leased', expected_statuses=[operation.status])
        lease = RecoveryLease(item=item, token=lease.token)
    operation, item = recovery.commit_observation(lease, stage='test', next_status='succeeded', event_type='clone_verified',
        recovery_status='completed', expected_statuses=['verifying'], release_target_lock=True)
    assert operation.status == 'succeeded'
    repository = SqlAlchemyDurableTargetLockRepository()
    assert all(repository.current(cluster_id=CLUSTER, vmid=vmid) is None for vmid in (40000, 40001))


def test_dispatch_uncertainty_marks_both_locks_for_reconciliation():
    operation, lease = prepare(spec())
    recovery = SqlAlchemyRecoveryStore()
    operation, item = recovery.commit_observation(lease, next_status='dispatching', stage='dispatch',
        event_type='clone_dispatching', recovery_status='leased', expected_statuses=['planned'])
    lease = RecoveryLease(item=item, token=lease.token)
    operation, item = recovery.commit_observation(lease, next_status='needs_reconciliation', stage='reconciliation',
        event_type='clone_unconfirmed', recovery_status='paused', expected_statuses=['dispatching'])
    assert item.status == 'paused'
    repository = SqlAlchemyDurableTargetLockRepository()
    assert all(repository.current(cluster_id=CLUSTER, vmid=vmid).status == 'reconciliation_required' for vmid in (40000, 40001))


@pytest.mark.parametrize('source,destination', [(40000,40001),(40001,40000)])
def test_restore_acquires_and_releases_both_exact_targets(source, destination):
    value=replace(spec(source,destination,operation_id='restore-test'),operation_type='vm_restore')
    operation,lease=prepare(value)
    bound(lease,operation)
    repository=SqlAlchemyDurableTargetLockRepository()
    assert all(repository.current(cluster_id=CLUSTER,vmid=vmid).operation_type=='vm_restore' for vmid in (source,destination))
    SqlAlchemyRecoveryStore().commit_observation(lease,stage='test',next_status='blocked',event_type='restore_precheck_blocked',
        recovery_status='completed',expected_statuses=['planned'],release_target_lock=True)
    assert all(repository.current(cluster_id=CLUSTER,vmid=vmid) is None for vmid in (source,destination))


def test_restore_source_binding_damage_cannot_release_target():
    operation,lease=prepare(replace(spec(operation_id='restore-test'),operation_type='vm_restore'))
    with session_scope() as session:
        session.get(OperationLockRecord,operation.details['related_target_locks'][0]['lock_id']).owner_id='foreign'
    with pytest.raises(RecoveryBindingError):bound(lease,operation)
    with pytest.raises(RecoveryOperationConflict):
        SqlAlchemyRecoveryStore().commit_observation(lease,stage='test',next_status='blocked',event_type='restore_invalid',
            recovery_status='completed',expected_statuses=['planned'],release_target_lock=True)
    assert SqlAlchemyDurableTargetLockRepository().current(cluster_id=CLUSTER,vmid=40001) is not None
