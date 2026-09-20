import pytest
from pydantic import ValidationError

from app.cloud_images.contracts import request_allowed, selected_import, vm_create_payload
from app.setup_integration.contracts import RegistrationIntent
from app.setup_integration.planning import ROLE_PRIVILEGES, acl_plan

SCOPE = {'nodes': ['node1'], 'vmids': [], 'image_vmids': [40000], 'storages': ['stage', 'target'], 'bridges': ['vmbr1']}
OPERATION = 'vm-image-build-' + 'a' * 64
SOURCE = 'stage:import/gjallar-image-40000-' + 'a' * 64 + '.qcow2'


def payload():
    return vm_create_payload(vmid=40000, name='alma-template', storage_id='target', bridge_id='vmbr1', source_volume=SOURCE, operation_id=OPERATION)


def intent(**patch):
    return RegistrationIntent(endpoint='https://pve.example.test', owner='test@pve', scope=SCOPE,
                              features=['read', 'image_build'], expires_at=2000000000, **patch)


def test_exact_image_config_and_conversion_are_allowed_without_start_or_shell():
    assert request_allowed('POST', ['nodes', 'node1', 'qemu'], payload(), SCOPE)
    assert request_allowed('POST', ['nodes', 'node1', 'qemu', '40000', 'template'], {}, SCOPE)
    assert not request_allowed('POST', ['nodes', 'node1', 'qemu', '40000', 'status', 'start'], {}, SCOPE)
    assert not request_allowed('PUT', ['nodes', 'node1', 'qemu', '40000', 'config'], payload(), SCOPE)


@pytest.mark.parametrize('patch', [{'vmid': 40001}, {'vmid': True}, {'onboot': False}, {'onboot': 1},
    {'description': 'unowned'}, {'name': 'bad name'}, {'cores': 8}, {'net0': 'virtio,bridge=vmbr0'},
    {'scsi0': 'target:0,import-from=/etc/passwd,format=qcow2'}, {'ide2': 'other:cloudinit'},
    {'scsi0': 'target:0,import-from=stage:import/other.qcow2,format=qcow2'},
    {'scsi0': 'target:0,import-from=' + SOURCE.replace('40000', '40001') + ',format=qcow2'},
    {'scsi0': 'target:0,import-from=' + SOURCE.replace('a' * 64, 'b' * 64) + ',format=qcow2'},
    {'archive': 'backup:old'}, {'force': 1}, {'start': 1}, {'cicustom': 'user=evil'}, {'args': '-anything'}])
def test_image_transport_rejects_expanded_or_unowned_requests(patch):
    assert not request_allowed('POST', ['nodes', 'node1', 'qemu'], {**payload(), **patch}, SCOPE)


def test_image_registration_has_no_root_host_power_or_guest_execution_grant():
    rows = acl_plan(intent())
    assert all(row['path'] != '/' for row in rows)
    grants = {privilege for row in rows for privilege in ROLE_PRIVILEGES[row['role']]}
    assert not grants & {'Sys.Modify', 'Sys.AccessNetwork', 'VM.PowerMgmt', 'VM.GuestAgent.Unrestricted'}
    assert {'Datastore.AllocateTemplate', 'Datastore.AllocateSpace', 'VM.Allocate'} <= grants
    assert selected_import(SOURCE, SCOPE)
    assert not selected_import(SOURCE.replace('stage:', 'other:'), SCOPE)


@pytest.mark.parametrize('patch', [{'image_vmids': []}, {'vmids': [40000]}, {'create_vmids': [40000]},
    {'clone_vmids': [40000]}, {'template_vmids': [40000]}, {'storages': []}, {'bridges': []}])
def test_image_future_scope_must_be_explicit_and_disjoint(patch):
    with pytest.raises(ValidationError):
        RegistrationIntent(endpoint='https://pve.example.test', owner='test@pve', scope={**SCOPE, **patch},
                           features=['read', 'image_build'], expires_at=2000000000)
