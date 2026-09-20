from types import SimpleNamespace
import pytest
from app.cloud_images.catalog import ALMA_9, ImageError
from app.cloud_images.contracts import upload_filename
from app.operations.vm_template.facade import observe_cleanup_template
from app.operations.vm_image_cleanup import infrastructure as module
from test_vm_image_build_adapter import Pve, OWNER


@pytest.fixture
def flow(monkeypatch):
    fake = Pve()
    fake.config.update(template=1, scsi0='target:40000/base-40000-disk-0.qcow2,size=10G')
    fake.storage_permissions.add('Datastore.Allocate')
    selected = {'revision_id': 'cleanup', 'configuration': {'features': ['read', 'image_cleanup'], 'scope': {
        'nodes': ['node1'], 'vmids': [40000], 'storages': ['stage', 'target'], 'image_cleanup_storages': ['stage', 'target']}}}
    original = observe_cleanup_template(fake, node_id='node1', vmid=40000)
    fake.list_vm_storage_images = lambda **kwargs: [
        {'volid': row['volume_id'], 'vmid': 40000, 'size': row['size_bytes'], 'format': row['format']} for row in original['volumes']]
    source_volume = 'stage:import/' + upload_filename(40000, OWNER)
    class Requests:
        dependents = 0
        rows = [{'volid': source_volume, 'size': ALMA_9.virtual_size_bytes, 'format': 'qcow2'}]
        calls = []
        def image_base_dependents(self, **kwargs): return {'dependent_count': self.dependents}
        def request(self, method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            return self.rows if method == 'GET' else 'UPID:node1:1:2:3:imgdel:stage:test@pve!test:'
    requests = Requests()
    monkeypatch.setattr(module, 'selected_credential', lambda: selected)
    monkeypatch.setattr(module, 'ManagedRequests', lambda _: requests)
    monkeypatch.setattr(module, 'managed_mutation_client', lambda _: fake)
    parent = SimpleNamespace(operation_id=OWNER, details={'target': {'name': 'alma-test'}, 'observed_after': original,
        'requested': {'storage_id': 'target', 'staging_storage_id': 'stage'},
        'source_integrity': {'virtual_size_bytes': ALMA_9.virtual_size_bytes, 'sha256': ALMA_9.sha256}})
    return module.ImageCleanupClient(), fake, requests, parent, selected


def read(flow, resource='template'):
    client, _, _, parent, _ = flow
    return client.read(node_id='node1', vmid=40000, parent=parent, resource=resource)


def test_template_manifest_requires_unfiltered_authority_and_exact_build_owner(flow):
    before = read(flow)
    assert before['dependent_count'] == 0 and len(before['deleted_volumes']) == 2
    assert not before['preserved_volumes']


@pytest.mark.parametrize('mode', ['owner', 'changed_config', 'protected', 'linked_clone', 'storage_permission', 'scope', 'revision'])
def test_template_cleanup_rejects_drift_references_and_scope_loss(flow, mode):
    _, fake, requests, _, selected = flow
    if mode == 'owner': fake.config['description'] = 'other'
    if mode == 'changed_config': fake.config['memory'] = 4096
    if mode == 'protected': fake.config['protection'] = 1
    if mode == 'linked_clone': requests.dependents = 1
    if mode == 'storage_permission': fake.storage_permissions.remove('Datastore.Allocate')
    if mode == 'scope': selected['configuration']['scope']['image_cleanup_storages'] = ['stage']
    if mode == 'revision': selected['revision_id'] = 'new'
    with pytest.raises(ImageError): read(flow)
    assert not requests.calls


def test_source_cleanup_is_exact_and_can_observe_after_vm_acl_disappears(flow):
    client, fake, requests, _, _ = flow
    before = {'resource': 'source', **read(flow, 'source')}
    assert upload_filename(40000, OWNER) in before['deleted_volumes'][0]['volume_id']
    client.apply(node_id='node1', vmid=40000, before=before)
    assert requests.calls[-1][0] == 'DELETE'
    assert requests.calls[-1][2] == {'data': {}}
    fake.permissions = set()
    requests.rows = []
    assert client.observe_deletion(node_id='node1', vmid=40000, before=before)['removed'] is True


@pytest.mark.parametrize('mode', ['absent', 'size', 'format', 'duplicate'])
def test_source_cleanup_requires_current_original_file_metadata(flow, mode):
    _, _, requests, _, _ = flow
    requests.rows = [dict(row) for row in requests.rows]
    if mode == 'absent': requests.rows = []
    if mode == 'size': requests.rows[0]['size'] += 1024
    if mode == 'format': requests.rows[0]['format'] = 'raw'
    if mode == 'duplicate': requests.rows *= 2
    with pytest.raises(ImageError): read(flow, 'source')


def test_source_task_success_with_remaining_file_is_not_removal(flow):
    client, _, _, _, _ = flow
    before = {'resource': 'source', **read(flow, 'source')}
    assert client.observe_deletion(node_id='node1', vmid=40000, before=before)['removed'] is False
