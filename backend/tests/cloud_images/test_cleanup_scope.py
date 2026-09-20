import time
from urllib.parse import quote
import pytest
from pydantic import ValidationError
from app.cloud_images.cleanup_contracts import cleanup_request_allowed
from app.setup_integration.contracts import RegistrationIntent, SetupError
from app.setup_integration.planning import acl_plan, ROLE_PRIVILEGES
from app.setup_integration.runtime import ManagedRequests

SCOPE = {'nodes': ['node1'], 'vmids': [40000], 'storages': ['target', 'stage'], 'bridges': [], 'image_cleanup_storages': ['stage']}
VOLUME = 'stage:import/gjallar-image-40000-' + 'a' * 64 + '.qcow2'


def test_cleanup_permission_is_explicit_and_storage_subset_only():
    intent = RegistrationIntent(endpoint='https://pve.example.test', owner='test@pve', scope=SCOPE,
        features=['read', 'image_cleanup'], expires_at=int(time.time()) + 86400)
    rows = acl_plan(intent)
    assert {row['path'] for row in rows if row['role'] == 'GjallarImageCleanupStorageV1'} == {'/storage/stage'}
    assert ROLE_PRIVILEGES['GjallarImageCleanupStorageV1'] == ['Datastore.Allocate']
    assert ROLE_PRIVILEGES['GjallarImageCleanupV1'] == ['VM.Allocate', 'VM.Audit']
    with pytest.raises(ValidationError): RegistrationIntent(**{**intent.model_dump(), 'features': ['read']})
    with pytest.raises(ValidationError): RegistrationIntent(**{**intent.model_dump(), 'scope': {**SCOPE, 'image_cleanup_storages': ['outside']}})


def test_cleanup_policy_rejects_foreign_volume_and_bypass_flags():
    path = ['nodes', 'node1', 'storage', 'stage', 'content', quote(VOLUME, safe='')]
    assert cleanup_request_allowed('DELETE', path, {}, SCOPE)
    for changed in [VOLUME.replace('40000', '40001'), VOLUME.replace('stage:', 'target:'), 'stage:import/manual.qcow2']:
        assert not cleanup_request_allowed('DELETE', path[:-1] + [quote(changed, safe='')], {}, SCOPE)
    assert not cleanup_request_allowed('DELETE', path, {'delay': 1}, SCOPE)
    vm_path = ['nodes', 'node1', 'qemu', '40000']
    assert cleanup_request_allowed('DELETE', vm_path, {'purge': 0, 'destroy-unreferenced-disks': 0}, SCOPE)
    assert not cleanup_request_allowed('DELETE', vm_path, {'purge': 1, 'destroy-unreferenced-disks': 0}, SCOPE)


def test_backing_reference_observation_requires_unfiltered_authority_and_only_returns_count():
    request = object.__new__(ManagedRequests)
    request.configuration = {'features': ['read', 'image_cleanup'], 'scope': {**SCOPE, 'image_cleanup_storages': ['target']}, 'token_id': 'test@pve!test'}
    request.secret = 'synthetic'
    class Transport:
        permissions = {'Datastore.Allocate': 1}
        def request(self, method, path, **kwargs):
            if path == '/access/permissions': return {'/storage/target': self.permissions}
            return [{'volid': 'target:40001/vm-40001-disk-0.qcow2', 'parent': 'target:40000/base-40000-disk-0.qcow2'}]
    request.transport = Transport()
    result = request.image_base_dependents(node='node1', vmid=40000, storage='target', volume='target:40000/base-40000-disk-0.qcow2')
    assert result == {'volume_id': 'target:40000/base-40000-disk-0.qcow2', 'dependent_count': 1}
    request.transport.permissions = {'Datastore.Audit': 1}
    with pytest.raises(SetupError): request.image_base_dependents(node='node1', vmid=40000, storage='target', volume=result['volume_id'])
