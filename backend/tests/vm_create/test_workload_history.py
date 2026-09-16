"""Historical Create results are bound to the completed operation target."""
from types import SimpleNamespace

import pytest

from app.operations.vm_create.domain import completed_workload_history


def operation():
    return SimpleNamespace(operation_type='vm_create', execution_mode='managed_api', status='succeeded',
        target_type='proxmox_vm', target_id='vmid:102', details={
            'target': {'node_id': 'node-a', 'vmid': 102},
            'workload': {'vm_instance_id': 'node-a:102', 'node_id': 'node-a', 'vmid': 102,
                         'name': 'historical-vm', 'status': 'stopped', 'updated_at': '2026-09-07T00:00:00Z'},
        })


@pytest.mark.parametrize('field,value', [('operation_type','vm_start'), ('execution_mode','guided'),
    ('status','running'), ('target_type','unknown'), ('target_id','vmid:103')])
def test_wrong_operation_cannot_supply_history(field, value):
    op = operation()
    setattr(op, field, value)
    assert completed_workload_history(op, node_id='node-a', vmid=102) is None


@pytest.mark.parametrize('section,patch', [('target', {'node_id':'other'}), ('target', {'vmid': True}),
    ('workload', {'vm_instance_id':'node-b:102'}), ('workload', {'vmid':'102'}),
    ('workload', {'name':''}), ('workload', {'updated_at':None})])
def test_corrupt_history_is_not_reconstructed(section, patch):
    op = operation()
    op.details[section].update(patch)
    assert completed_workload_history(op, node_id='node-a', vmid=102) is None


def test_history_missing_does_not_look_like_success():
    op = operation()
    op.details.pop('workload')
    assert completed_workload_history(op, node_id='node-a', vmid=102) is None
