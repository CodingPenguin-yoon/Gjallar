import pytest
from app.cloud_images.catalog import ALMA_9, ImageError
from app.cloud_images.contracts import BuildInput, VM_PRIVILEGES
from app.operations.vm_image_build import infrastructure as module

OWNER = 'vm-image-build-' + 'a' * 64


class Pve:
    def __init__(self):
        self.storages = [dict(storage='stage', type='dir', active=1, enabled=1, content='import', avail=10**11),
                         dict(storage='target', type='nfs', active=1, enabled=1, content='images', avail=10**11)]
        self.network = dict(pending_changes=False, interfaces=[dict(iface='vmbr1', type='bridge', active=1)])
        self.permissions = set(VM_PRIVILEGES)
        self.storage_permissions = {'Datastore.Audit', 'Datastore.AllocateSpace', 'Datastore.AllocateTemplate'}
        self.bridge_permissions = {'SDN.Use', 'SDN.Audit'}
        self.config = dict(name='alma-test', description=OWNER, digest='a' * 40, cores=2, memory=2048,
            bios='seabios', scsihw='virtio-scsi-pci', vga='std', boot='order=scsi0', onboot=0, ipconfig0='ip=dhcp', ostype='l26',
            agent='enabled=1', net0='virtio=02:00:00:00:00:01,bridge=vmbr1', scsi0='target:40000/vm-40000-disk-0.qcow2,size=10G',
            ide2='target:40000/vm-40000-cloudinit.qcow2,media=cdrom')
    def assert_vmid_unused(self, **kwargs): pass
    def get_vm_permissions(self, **kwargs): return self.permissions
    def get_storage_permissions(self, **kwargs): return self.storage_permissions
    def get_bridge_permissions(self, **kwargs): return self.bridge_permissions
    def get_node_network_snapshot(self, **kwargs): return self.network
    def get_node_storages(self, **kwargs): return self.storages
    def get_vm_current_config(self, **kwargs): return dict(self.config)
    def get_vm_status(self, **kwargs): return {'status': 'stopped'}
    def get_vm_pending(self, **kwargs): return []
    def get_vm_snapshots(self, **kwargs): return [{'name': 'current'}]
    def get_volume_info(self, *, volume, **kwargs):
        return {'size': 4 * 1024 ** 2 if 'cloudinit' in volume else ALMA_9.virtual_size_bytes, 'format': 'qcow2'}


@pytest.fixture
def adapter(monkeypatch):
    selected = {'revision_id': 'revision', 'configuration': {'features': ['read', 'image_build'],
        'scope': {'nodes': ['node1'], 'image_vmids': [40000], 'storages': ['stage', 'target'], 'bridges': ['vmbr1']}}}
    fake = Pve()
    monkeypatch.setattr(module, 'selected_credential', lambda: selected)
    monkeypatch.setattr(module, 'ManagedRequests', lambda _: None)
    monkeypatch.setattr(module, 'managed_mutation_client', lambda _: fake)
    client = module.ImageBuildClient()
    request = BuildInput(image_id=ALMA_9.image_id, name='alma-test', storage_id='target', staging_storage_id='stage', bridge_id='vmbr1')
    return client, fake, request, selected


def test_preflight_and_actual_prepared_template_observation(adapter):
    client, fake, request, _ = adapter
    assert client.preflight(node_id='node1', vmid=40000, request=request)['image']['sha256'] == ALMA_9.sha256
    result = client.observe_vm(node_id='node1', vmid=40000, request=request, operation_id=OWNER)
    assert result['guest_readiness'] == 'official_image_not_runtime_verified'
    fake.config.update(template=1, scsi0='target:40000/base-40000-disk-0.qcow2,size=10G')
    assert client.observe_vm(node_id='node1', vmid=40000, request=request, operation_id=OWNER, converted=True)['template'] is True


@pytest.mark.parametrize('mode', ['wrong_scope', 'connection_changed', 'no_upload', 'no_vm_allocate', 'no_bridge_use',
                                   'staging_space', 'staging_content', 'target_type', 'network_pending'])
def test_preflight_rejects_ineligible_allocation(adapter, mode):
    client, fake, request, selected = adapter
    if mode == 'wrong_scope': request = request.model_copy(update={'bridge_id': 'vmbr9'})
    if mode == 'connection_changed': selected['revision_id'] = 'replacement'
    if mode == 'no_upload': fake.storage_permissions.remove('Datastore.AllocateTemplate')
    if mode == 'no_vm_allocate': fake.permissions.remove('VM.Allocate')
    if mode == 'no_bridge_use': fake.bridge_permissions.remove('SDN.Use')
    if mode == 'staging_space': fake.storages[0]['avail'] = 1024
    if mode == 'staging_content': fake.storages[0]['content'] = 'iso'
    if mode == 'target_type': fake.storages[1]['type'] = 'lvmthin'
    if mode == 'network_pending': fake.network['pending_changes'] = True
    with pytest.raises(ImageError): client.preflight(node_id='node1', vmid=40000, request=request)


@pytest.mark.parametrize('patch', [{'description': 'other-operation'}, {'net0': 'virtio=02:00:00:00:00:01,bridge=vmbr9'},
                                   {'memory': 4096}, {'agent': '0'}, {'onboot': 1}])
def test_post_create_result_requires_operation_owned_fixed_configuration(adapter, patch):
    client, fake, request, _ = adapter
    fake.config.update(patch)
    with pytest.raises(ImageError): client.observe_vm(node_id='node1', vmid=40000, request=request, operation_id=OWNER)
