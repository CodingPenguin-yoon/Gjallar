"""Durable target locking never depends on container-local files."""
from dataclasses import replace
from unittest.mock import patch
import pytest
from app.operations.target_lock import (
    TargetOperationLockBusy, acquire_target_operation_lock, get_target_operation_lock,
    release_target_operation_lock, release_target_operation_lock_for_owner,
)


def acquire(owner, operation_type='vm_create'):
    return acquire_target_operation_lock('proxmox_vm', 'vmid:306', owner, operation_type=operation_type)


def test_cross_action_lock_survives_without_files():
    with patch('os.open', side_effect=AssertionError('filesystem lock forbidden')):
        first = acquire('owner-a')
        with pytest.raises(TargetOperationLockBusy):
            acquire('owner-b', 'vm_start')
        assert get_target_operation_lock('proxmox_vm', 'vmid:306')['owner_id'] == 'owner-a'
        release_target_operation_lock(first)
        release_target_operation_lock(acquire('owner-b', 'vm_shutdown'))


def test_old_handle_cannot_release_replacement_even_with_same_owner():
    old = acquire('owner-a')
    release_target_operation_lock(old)
    current = acquire('owner-a')
    release_target_operation_lock(old)
    assert get_target_operation_lock('proxmox_vm', 'vmid:306')['lock_id'] == current.lock_id
    release_target_operation_lock(current)


def test_wrong_owner_cannot_release_and_exact_owner_can():
    first = acquire('owner-a')
    assert not release_target_operation_lock_for_owner('proxmox_vm', 'vmid:306', 'owner-b')
    assert get_target_operation_lock('proxmox_vm', 'vmid:306') == first.to_dict()
    assert release_target_operation_lock_for_owner('proxmox_vm', 'vmid:306', 'owner-a')


def test_foreign_handle_cannot_release():
    first = acquire('owner-a')
    release_target_operation_lock(replace(first, durable=replace(first.durable, owner_id='other')))
    assert get_target_operation_lock('proxmox_vm', 'vmid:306') is not None
    release_target_operation_lock(first)


@pytest.mark.parametrize('target_type,target_id', [('vm','306'), ('proxmox_vm','node:306'), ('proxmox_vm','vmid:0')])
def test_invalid_locator_is_not_silently_normalized(target_type,target_id):
    with pytest.raises(ValueError):
        acquire_target_operation_lock(target_type,target_id,'owner',operation_type='vm_create')


@pytest.mark.parametrize("action", ["start", "shutdown"])
@pytest.mark.parametrize("marker", ["pre_dispatch_no_effect_verified", "pre_dispatch_file_guard_cleaned"])
def test_pre_dispatch_history_retains_no_effect_proof(action, marker):
    from importlib import import_module
    from types import SimpleNamespace

    workflow = import_module(f"app.operations.vm_{action}.workflow")
    operation = SimpleNamespace(status="planned", details={
        "recovery_contract": workflow.PRE_DISPATCH_RECOVERY_CONTRACT,
    })
    result = {f"proxmox_{action}_ran": False, "proxmox_mutation_enabled": False, marker: True}
    job = {"status": "failed", "details": {f"vm_{action}_result": result}}
    assert workflow._is_recoverable_pre_dispatch_terminal_replay(job, operation)
    result[f"proxmox_{action}_ran"] = True
    assert not workflow._is_recoverable_pre_dispatch_terminal_replay(job, operation)
