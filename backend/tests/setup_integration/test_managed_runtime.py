"""Exercise the real managed client boundary with a network-free transport."""
import pytest

from app.proxmox.client import ProxmoxMutationError
from app.setup_integration.contracts import RegistrationIntent, SetupError
from app.setup_integration.planning import ROLE_PRIVILEGES, acl_plan
from app.setup_integration.runtime import managed_mutation_client


@pytest.fixture
def managed(monkeypatch):
    calls = []

    class Transport:
        def __init__(self, *args):
            pass

        def request(self, method, path, *, data=None, **kwargs):
            assert "?" not in path
            calls.append((method, path, data))
            if path == "/access/permissions":
                return {data["path"]: {"Sys.Audit": 1}}
            if path.endswith("/tasks"):
                return []
            return None

    monkeypatch.setattr("app.setup_integration.transport.ProxmoxSetupTransport", Transport)
    selection = {"secret": "synthetic", "configuration": {
        "endpoint": "https://pve.example.test", "ca_pem": "", "token_id": "test@pve!test",
        "features": ["read", "compute"],
        "scope": {"nodes": ["node1"], "vmids": [101], "storages": [], "bridges": []},
    }}
    return managed_mutation_client(selection), selection, calls


def test_managed_existing_client_query_requests(managed):
    client, _, calls = managed
    assert client.has_node_task_audit(node="node1")
    assert client.list_active_vm_tasks(node="node1", vmid=101) == []
    assert calls == [
        ("GET", "/access/permissions", {"path": "/nodes/node1"}),
        ("GET", "/nodes/node1/tasks", {"source": "active", "vmid": "101"}),
    ]


def test_host_storage_capability_is_exact_and_does_not_grant_volume_or_vm_writes(managed):
    from app.operations.host_storage.domain import StorageChange, mutation_body
    client,selection,calls = managed
    change = StorageChange(mode='create',path='/mnt/existing',content=['images'])
    body = mutation_body(change,node_id='node1',storage_id='new-dir',before=None)
    with pytest.raises(SetupError): client._request('POST','/storage',data=body)
    selection['configuration']['features'] = ['read','host_storage']
    selection['configuration']['scope']['host_storages'] = ['new-dir']
    client._request('POST','/storage',data=body)
    client.get_storage_configuration_permissions()
    update = {'content':'images,iso','disable':0,'create-base-path':0,'create-subdirs':0,'digest':'a'*40}
    client._request('PUT','/storage/new-dir',data=update)
    count = len(calls)
    for method,path,data in [('POST','/storage',{**body,'storage':'other'}),('POST','/storage',{**body,'nodes':'other'}),
        ('POST','/storage',{**body,'create-base-path':1}),('POST','/storage',{**body,'shared':1}),
        ('POST','/storage',{**body,'path':'/mnt/../other'}),('POST','/storage',{**body,'type':'nfs'}),
        ('PUT','/storage/new-dir',{**update,'path':'/other'}),('PUT','/storage/new-dir',{**update,'delete':'nodes'}),
        ('PUT','/storage/new-dir',{key:value for key,value in update.items() if key!='digest'}),
        ('DELETE','/storage/new-dir',{}),('GET','/storage/other',None),('GET','/storage/new-dir?extra=x',None),
        ('DELETE','/nodes/node1/storage/new-dir/content/new-dir:101/vm-101-disk-0.qcow2',{}),
        ('PUT','/nodes/node1/qemu/101/config',{'cores':4})]:
        with pytest.raises(SetupError): client._request(method,path,data=data)
    assert len(calls) == count


def test_host_storage_registration_has_explicit_global_authority_and_future_ids():
    from app.setup_integration.contracts import RegistrationIntent
    from pydantic import ValidationError
    intent = RegistrationIntent(endpoint='https://pve.example.test',owner='test@pve',expires_at=2000000000,
        features=['read','host_storage'],scope={'nodes':['node1'],'host_storages':['new-dir']})
    acls = acl_plan(intent)
    assert {'path':'/storage','role':'GjallarHostStorageV1','propagate':1} in acls
    assert {'path':'/storage/new-dir','role':'GjallarStorageReadV1','propagate':1} in acls
    assert set(ROLE_PRIVILEGES['GjallarHostStorageV1']) == {'Datastore.Allocate'}
    assert not any(row['path'].startswith('/vms/') for row in acls)
    for patch in ({'features':['read']},{'scope':{'nodes':['node1']}}):
        with pytest.raises(ValidationError): RegistrationIntent(**{**intent.model_dump(),**patch})


def test_compute_role_is_additive_and_exact():
    intent = RegistrationIntent(endpoint="https://pve.example.test", owner="test@pve",
        scope={"nodes": ["node1"], "vmids": [101]}, features=["read", "compute"], expires_at=2000000000)
    rows = acl_plan(intent)
    assert {row["role"] for row in rows if row["path"] == "/vms/101"} == {"GjallarVmReadV1", "GjallarVmComputeV1"}
    assert set(ROLE_PRIVILEGES["GjallarVmComputeV1"]) == {"VM.Config.CPU", "VM.Config.Memory"}
    assert "VM.Config.CPU" not in ROLE_PRIVILEGES["GjallarVmPowerV1"]


def test_monitoring_uses_existing_read_scope_only(managed):
    client, selection, calls = managed
    selection['configuration']['features'] = ['read']
    selection['configuration']['scope']['storages'] = ['store1']
    for kind, kwargs in [('node', {}), ('vm', {'vmid': 101}), ('storage', {'storage': 'store1'})]:
        client.get_monitoring_data(kind=kind, node='node1', **kwargs)
        for period in ('hour', 'day', 'week', 'month', 'year'):
            client.get_monitoring_data(kind=kind, node='node1', timeframe=period, **kwargs)
    assert len(calls) == 18 and all(row[0] == 'GET' for row in calls)
    for path in ('/nodes/other/rrddata?timeframe=hour&cf=AVERAGE', '/nodes/node1/qemu/102/rrddata?timeframe=day&cf=AVERAGE',
                 '/nodes/node1/storage/other/rrddata?timeframe=hour&cf=AVERAGE', '/nodes/node1/rrddata?timeframe=hour&cf=MAX',
                 '/nodes/node1/rrddata?timeframe=decade&cf=AVERAGE', '/nodes/node1/rrddata?timeframe=hour&cf=AVERAGE&command=x',
                 '/nodes/node1/storage/other/status'):
        with pytest.raises(SetupError): client._request('GET', path)
    with pytest.raises(SetupError): client._request('POST', '/nodes/node1/rrddata', data={'timeframe': 'hour', 'cf': 'AVERAGE'})
    assert len(calls) == 18


def test_compute_allows_only_selected_vm_and_fields(managed):
    client, selection, calls = managed
    client.set_vm_config(node="node1", vmid=101, config={"cores": 4, "memory": 4096, "digest": "a" * 40})
    assert calls[-1][0:2] == ("PUT", "/nodes/node1/qemu/101/config")
    for node, vmid, config in [
        ("node1", 102, {"cores": 4}), ("other", 101, {"cores": 4}),
        ("node1", 101, {"delete": "scsi0"}), ("node1", 101, {"cores": 4, "skiplock": 1}),
        ("node1", 101, {"sockets": 2}), ("node1", 101, {"balloon": 0}),
    ]:
        with pytest.raises(ProxmoxMutationError):
            client.set_vm_config(node=node, vmid=vmid, config=config)
    assert len(calls) == 1
    selection["configuration"]["features"] = ["read", "power"]
    with pytest.raises(ProxmoxMutationError):
        client.set_vm_config(node="node1", vmid=101, config={"cores": 4})
    assert len(calls) == 1


@pytest.mark.parametrize("path", [
    "/access/permissions?path=/nodes/other", "/access/permissions?path=/nodes/node1&path=/",
    "/nodes/node1/tasks?source=active&vmid=102", "/nodes/node1/tasks?source=active&vmid=101&limit=1000",
    "/nodes/node1/qemu/101/config?delete=scsi0", "/nodes/node1/tasks?source=active&vmid=101#fragment",
])
def test_query_normalization_cannot_expand_scope(managed, path):
    client, _, calls = managed
    with pytest.raises(SetupError):
        client._request("GET", path)
    assert calls == []


def test_disk_requires_explicit_capability_and_scoped_volume(managed):
    client, selection, calls = managed
    with pytest.raises(ProxmoxMutationError):
        client.resize_vm_disk_reviewed(node="node1", vmid=101, size_gib=24, digest="a" * 40)
    selection["configuration"]["features"] = ["read", "disk"]
    selection["configuration"]["scope"]["storages"] = ["store1"]
    client.resize_vm_disk_reviewed(node="node1", vmid=101, size_gib=24, digest="a" * 40)
    assert calls[-1] == ("PUT", "/nodes/node1/qemu/101/resize", {"disk": "scsi0", "size": "24G", "digest": "a" * 40})
    client._request("GET", "/nodes/node1/storage/store1/content/store1%3A101%2Fvm-101-disk-0.qcow2")
    client.get_storage_permissions(storage="store1")
    allowed_count = len(calls)
    for path in ("/nodes/node1/storage/other/content/other%3A101%2Fvm-101-disk-0.qcow2",
                 "/nodes/node1/storage/store1/content/store1%3A102%2Fvm-102-disk-0.qcow2",
                 "/nodes/node1/storage/store1/content/store1%3A101%2F..%2Fvm-101-disk-0.qcow2",
                 "/access/permissions?path=/storage/other"):
        with pytest.raises(SetupError):
            client._request("GET", path)
    for fields in ({"disk": "scsi1", "size": "24G", "digest": "a" * 40},
                   {"disk": "scsi0", "size": "+24G", "digest": "a" * 40},
                   {"disk": "scsi0", "size": "24G"}):
        with pytest.raises(SetupError):
            client._request("PUT", "/nodes/node1/qemu/101/resize", data=fields)
    assert len(calls) == allowed_count


def test_network_scope_is_additive_and_checks_selected_bridge(managed):
    client, selection, calls = managed
    config = {'net0': 'virtio=02:00:00:00:00:01,bridge=vmbr0,firewall=1,tag=100', 'digest': 'a' * 40}
    with pytest.raises(ProxmoxMutationError):
        client.set_vm_config(node='node1', vmid=101, config=config)
    selection['configuration']['features'] = ['read', 'network']
    selection['configuration']['scope']['bridges'] = ['vmbr0']
    client.set_vm_config(node='node1', vmid=101, config=config)
    client.get_bridge_permissions(bridge='vmbr0')
    assert len(calls) == 2
    for changed in ({**config, 'net0': config['net0'].replace('vmbr0', 'other')},
                    {**config, 'net0': config['net0'] + ',trunks=100;200'},
                    {**config, 'net0': config['net0'] + ',bridge=other'},
                    {**config, 'net0': config['net0'].replace('tag=100', 'tag=0')},
                    {**config, 'net1': config['net0']}, {**config, 'skiplock': 1}):
        with pytest.raises(ProxmoxMutationError):
            client.set_vm_config(node='node1', vmid=101, config=changed)
    assert len(calls) == 2
    with pytest.raises(ProxmoxMutationError):
        client.get_bridge_permissions(bridge='other')
    intent = RegistrationIntent(endpoint='https://pve.example.test', owner='test@pve',
        scope={'nodes': ['node1'], 'vmids': [101], 'bridges': ['vmbr0']}, features=['read', 'network'], expires_at=2000000000)
    rows = acl_plan(intent)
    assert {'path': '/vms/101', 'role': 'GjallarVmNetworkV1', 'propagate': 1} in rows
    assert {'path': '/sdn/zones/localnetwork/vmbr0', 'role': 'GjallarBridgeUseV1', 'propagate': 1} in rows
    assert ROLE_PRIVILEGES['GjallarVmNetworkV1'] == ['VM.Config.Network']


def test_network_metadata_retained_while_managed_scope_filters_data(monkeypatch):
    from app.setup_integration.runtime import ManagedRequests
    from app.proxmox.client import ProxmoxMutationClient
    payload = {'data': [{'iface': 'vmbr0', 'active': 1}, {'iface': 'other', 'active': 1}],
               'changes': 'synthetic host diff must not be exposed'}
    class Transport:
        def __init__(self, *args): pass
        def request(self, *args, **kwargs):
            assert kwargs['response_metadata'] is True
            return payload
    monkeypatch.setattr('app.setup_integration.transport.ProxmoxSetupTransport', Transport)
    selection = {'secret': 'synthetic', 'configuration': {'endpoint': 'https://pve.example.test', 'ca_pem': '',
        'token_id': 'test@pve!test', 'features': ['read', 'network'],
        'scope': {'nodes': ['node1'], 'vmids': [101], 'storages': [], 'bridges': ['vmbr0']}}}
    client = managed_mutation_client(selection)
    assert client.get_node_network_snapshot(node='node1') == {'interfaces': [{'iface': 'vmbr0', 'active': 1}], 'pending_changes': True}
    payload.pop('changes')
    assert client.get_node_network_snapshot(node='node1')['pending_changes'] is False
    payload['changes'] = {'unknown': True}
    with pytest.raises(ProxmoxMutationError):
        client.get_node_network_snapshot(node='node1')
    with pytest.raises(SetupError):
        ManagedRequests(selection).request('GET', '/nodes/node1/qemu', response_metadata=True)
    # An old injected client that silently drops metadata cannot imply safety.
    legacy = ProxmoxMutationClient(api_url='https://pve.example.test', token_id='fake', token_secret='fake', request=lambda *a, **kw: [])
    with pytest.raises(ProxmoxMutationError):
        legacy.get_node_network_snapshot(node='node1')


def test_full_clone_requires_distinct_source_target_scope_and_exact_request(managed):
    client, selection, calls = managed
    config = selection['configuration']
    config['scope'].update(clone_vmids=[102], storages=['store1'], bridges=['vmbr0'])
    arguments = dict(node='node1', vmid=101, new_vmid=102, name='copy-102', storage='store1',
                     disk_format='qcow2', description='vm-clone-' + 'a' * 64)
    with pytest.raises(ProxmoxMutationError): client.clone_vm_reviewed(**arguments)
    config['features'] = ['read', 'clone']
    client.clone_vm_reviewed(**arguments)
    assert calls[-1] == ('POST', '/nodes/node1/qemu/101/clone', {'newid': 102, 'name': 'copy-102',
        'storage': 'store1', 'format': 'qcow2', 'full': 1, 'description': 'vm-clone-' + 'a' * 64})
    for patch in ({'vmid': 103}, {'new_vmid': 101}, {'new_vmid': 104}, {'storage': 'other'},
                  {'description': 'unbound'}, {'disk_format': 'vmdk'}, {'node': 'other'}):
        with pytest.raises(ProxmoxMutationError): client.clone_vm_reviewed(**{**arguments, **patch})
    assert len(calls) == 1
    config['features'] += ['power', 'compute', 'disk']
    # Clone allocation scope does not silently acquire other mutation capabilities.
    for dispatch in (lambda: client.start_vm(node='node1', vmid=102),
                     lambda: client.set_vm_config(node='node1', vmid=102, config={'cores': 4}),
                     lambda: client.resize_vm_disk_reviewed(node='node1', vmid=102, size_gib=24, digest='a' * 40)):
        with pytest.raises(ProxmoxMutationError): dispatch()
    assert len(calls) == 1
    intent = RegistrationIntent(endpoint='https://pve.example.test', owner='test@pve', features=['read', 'clone'],
        scope=config['scope'], expires_at=2000000000)
    rows = acl_plan(intent)
    assert {row['role'] for row in rows if row['path'] == '/vms/102'} == {'GjallarVmCloneTargetV2'}
    assert set(ROLE_PRIVILEGES['GjallarVmCloneTargetV2']) == {'VM.Audit', 'VM.Allocate', 'VM.Config.Disk'}


def test_cluster_resource_inventory_keeps_selected_ids_on_other_nodes_and_fails_closed(monkeypatch):
    payload = [{'vmid': 102, 'node': 'other-node', 'type': 'lxc'}, {'vmid': 999, 'node': 'node1', 'type': 'qemu'}]
    class Transport:
        def __init__(self, *args): pass
        def request(self, method, path, *, data=None, **kwargs):
            assert method == 'GET' and path == '/cluster/resources' and data == {'type': 'vm'}
            return payload
    monkeypatch.setattr('app.setup_integration.transport.ProxmoxSetupTransport', Transport)
    selection = {'secret': 'synthetic', 'configuration': {'endpoint': 'https://pve.example.test', 'ca_pem': '',
        'token_id': 'test@pve!test', 'features': ['read', 'clone'],
        'scope': {'nodes': ['node1'], 'vmids': [101], 'clone_vmids': [102], 'storages': ['store1'], 'bridges': ['vmbr0']}}}
    client = managed_mutation_client(selection)
    assert client.list_vm_resources() == [payload[0]]
    payload[0]['vmid'] = '102'
    with pytest.raises(ProxmoxMutationError): client.list_vm_resources()


@pytest.mark.parametrize('value,confirmed', [(40000, True), ('40000', True), (True, False), (None, False),
                                           (40001, False), ('040000', False), ({'vmid': 40000}, False)])
def test_vmid_absence_requires_exact_authoritative_scalar(value, confirmed):
    from app.proxmox.client import ProxmoxMutationClient
    client = ProxmoxMutationClient(api_url='https://pve.example.test', token_id='fake', token_secret='fake',
                                  request=lambda *args, **kwargs: value)
    if confirmed:
        assert client.assert_vmid_unused(vmid=40000) is True
    else:
        with pytest.raises(ProxmoxMutationError): client.assert_vmid_unused(vmid=40000)


def test_managed_vmid_and_content_absence_reads_cannot_expand_scope(managed):
    client, selection, calls = managed
    selection['configuration']['scope']['storages'] = ['store1']
    client._request('GET', '/cluster/nextid?vmid=101')
    client._request('GET', '/nodes/node1/storage/store1/content?content=images&vmid=101')
    assert calls[-2:] == [('GET', '/cluster/nextid', {'vmid': '101'}),
                          ('GET', '/nodes/node1/storage/store1/content', {'content': 'images', 'vmid': '101'})]
    for path in ('/cluster/nextid', '/cluster/nextid?vmid=102', '/cluster/nextid?vmid=101&vmid=102',
                 '/nodes/node1/storage/store1/content', '/nodes/node1/storage/store1/content?content=backup&vmid=101',
                 '/nodes/node1/storage/store1/content?content=images&vmid=102',
                 '/nodes/other/storage/store1/content?content=images&vmid=101'):
        with pytest.raises(SetupError): client._request('GET', path)
    assert len(calls) == 2


def test_delete_is_opt_in_and_cannot_expand_cleanup_scope(managed):
    client, selection, calls = managed
    with pytest.raises(ProxmoxMutationError):
        client.delete_vm_reviewed(node='node1', vmid=101)
    selection['configuration']['features'] = ['read', 'delete']
    selection['configuration']['scope']['storages'] = ['store1']
    client.delete_vm_reviewed(node='node1', vmid=101)
    assert calls == [('DELETE', '/nodes/node1/qemu/101', {'purge': 0, 'destroy-unreferenced-disks': 0})]
    for fields in ({'purge': 1, 'destroy-unreferenced-disks': 0}, {'purge': 0, 'destroy-unreferenced-disks': 1},
                   {'purge': 0, 'destroy-unreferenced-disks': 0, 'skiplock': 1}, {}):
        with pytest.raises(SetupError):
            client._request('DELETE', '/nodes/node1/qemu/101', data=fields)
    for path in ('/nodes/node1/qemu/102', '/nodes/other/qemu/101'):
        with pytest.raises(SetupError):
            client._request('DELETE', path, data={'purge': 0, 'destroy-unreferenced-disks': 0})
    assert len(calls) == 1


def test_delete_role_is_minimal_and_storage_observation_is_required():
    intent = RegistrationIntent(endpoint='https://pve.example.test', owner='test@pve',
        scope={'nodes': ['node1'], 'vmids': [101], 'storages': ['store1']}, features=['read', 'delete'], expires_at=2000000000)
    rows = acl_plan(intent)
    assert set(ROLE_PRIVILEGES['GjallarVmDeleteV1']) == {'VM.Allocate'}
    assert {row['role'] for row in rows if row['path'] == '/vms/101'} == {'GjallarVmReadV1', 'GjallarVmDeleteV1'}
    assert not any(row['role'] == 'GjallarStorageAllocateV1' for row in rows)
    with pytest.raises(ValueError):
        RegistrationIntent(endpoint='https://pve.example.test', owner='test@pve',
            scope={'nodes': ['node1'], 'vmids': [101]}, features=['read', 'delete'], expires_at=2000000000)


def test_console_post_requires_explicit_feature_and_existing_vm_scope(managed):
    client, selection, calls = managed
    path = '/nodes/node1/qemu/101/vncproxy'
    with pytest.raises(SetupError):
        client._request('POST', path, data={'websocket': 1})
    selection['configuration']['features'] = ['read', 'console']
    selection['configuration']['scope']['create_vmids'] = [40000]
    client._request('POST', path, data={'websocket': 1})
    assert calls == [('POST', path, {'websocket': 1})]
    for other_path, payload in [(path, {}), (path, {'websocket': 0}), (path, {'websocket': 1, 'port': 5900}),
            ('/nodes/node1/qemu/40000/vncproxy', {'websocket': 1}),
            ('/nodes/other/qemu/101/vncproxy', {'websocket': 1}),
            ('/nodes/node1/qemu/101/termproxy', {'websocket': 1})]:
        with pytest.raises(SetupError):
            client._request('POST', other_path, data=payload)
    assert len(calls) == 1


def test_template_is_explicit_and_only_whole_selected_existing_vm(managed):
    client, selection, calls = managed
    with pytest.raises(ProxmoxMutationError): client.convert_vm_to_template(node='node1', vmid=101)
    selection['configuration']['features'] = ['read', 'template']
    selection['configuration']['scope']['storages'] = ['store1']
    client.convert_vm_to_template(node='node1', vmid=101)
    assert calls == [('POST', '/nodes/node1/qemu/101/template', {})]
    for node, vmid in [('other', 101), ('node1', 102)]:
        with pytest.raises(ProxmoxMutationError): client.convert_vm_to_template(node=node, vmid=vmid)
    for data in ({'disk': 'scsi0'}, {'skiplock': 1}, {'force': 1}):
        with pytest.raises(ProxmoxMutationError): client._request_json('POST', '/nodes/node1/qemu/101/template', data=data)
    assert len(calls) == 1
    client._request_json('GET', '/nodes/node1/storage/store1/content/store1%3A101%2Fbase-101-disk-0.qcow2')
    with pytest.raises(ProxmoxMutationError): client._request_json('GET', '/nodes/node1/storage/store1/content/store1%3A102%2Fbase-102-disk-0.qcow2')


def test_template_role_does_not_grant_storage_allocation_or_expand_old_roles():
    intent = RegistrationIntent(endpoint='https://pve.example.test', owner='test@pve',
        scope={'nodes': ['node1'], 'vmids': [101], 'storages': ['store1']}, features=['read', 'template'], expires_at=2000000000)
    assert ROLE_PRIVILEGES['GjallarVmTemplateV2'] == ['VM.Allocate', 'VM.Config.Disk']
    assert 'VM.Allocate' not in ROLE_PRIVILEGES['GjallarVmReadV1']
    assert {row['role'] for row in acl_plan(intent) if row['path'] == '/storage/store1'} == {'GjallarStorageReadV1'}


def test_managed_image_create_and_import_reads_remain_scoped(managed):
    from app.cloud_images.contracts import vm_create_payload
    client, selection, calls = managed
    config = selection['configuration']
    config['scope'].update(image_vmids=[40000], storages=['store1'], bridges=['vmbr1'])
    source = 'store1:import/gjallar-image-40000-' + 'a' * 64 + '.qcow2'
    data = vm_create_payload(vmid=40000, name='alma-test', storage_id='store1', bridge_id='vmbr1',
                             source_volume=source, operation_id='vm-image-build-' + 'a' * 64)
    with pytest.raises(ProxmoxMutationError): client._request_json('POST', '/nodes/node1/qemu', data=data)
    config['features'] = ['read', 'image_build']
    client._request_json('POST', '/nodes/node1/qemu', data=data)
    client.convert_vm_to_template(node='node1', vmid=40000)
    assert len(calls) == 2
    for patch in ({'start': 1}, {'vmid': 101}, {'vmid': 40001}, {'force': 1}):
        with pytest.raises(ProxmoxMutationError): client._request_json('POST', '/nodes/node1/qemu', data={**data, **patch})
    with pytest.raises(ProxmoxMutationError): client._request_json('GET', '/nodes/node1/storage/store1/content?content=import&limit=10')
    with pytest.raises(ProxmoxMutationError): client._request_json('GET', '/nodes/node1/storage/other/content?content=import')
    assert len(calls) == 2


def test_backup_role_and_selected_storage_are_minimal():
    intent = RegistrationIntent(endpoint='https://pve.example.test',owner='test@pve',
        scope={'nodes':['node1'],'vmids':[101],'storages':['source','backup'],'backup_storages':['backup']},
        features=['read','backup'],expires_at=2000000000)
    rows = acl_plan(intent)
    assert ROLE_PRIVILEGES['GjallarVmBackupV1'] == ['VM.Backup']
    assert {'path':'/storage/backup','role':'GjallarStorageAllocateV1','propagate':1} in rows
    assert {'path':'/storage/source','role':'GjallarStorageAllocateV1','propagate':1} not in rows
    with pytest.raises(ValueError):
        RegistrationIntent.model_validate({**intent.model_dump(),'features':['read']})
    with pytest.raises(ValueError):
        RegistrationIntent.model_validate({**intent.model_dump(),'scope':{**intent.scope.model_dump(),'backup_storages':['unselected']}})


def test_managed_backup_body_and_read_scope_cannot_expand(managed):
    from app.backups.contracts import backup_body
    client,selection,calls=managed
    config=selection['configuration'];config['features']=['read','backup']
    config['scope'].update(storages=['store1','other'],backup_storages=['store1'])
    body=backup_body(101,'store1','vm-backup-'+'a'*64)
    client._request('POST','/nodes/node1/vzdump',data=body)
    for patch in ({'remove':1},{'all':1},{'vmid':'101,102'},{'storage':'other'},{'notes-template':'x'},
                  {'notification-mode':'auto'},{'mailto':'external@example.test'},{'script':'x'},{'fleecing':'enabled=1,storage=store1'},
                  {'prune-backups':'keep-last=1'},{'stop':1},{'remove':False}):
        with pytest.raises(SetupError):client._request('POST','/nodes/node1/vzdump',data={**body,**patch})
    client._request('GET','/nodes/node1/vzdump/defaults?storage=store1')
    client._request('GET','/nodes/node1/storage/store1/content?content=backup&vmid=101')
    assert len(calls)==3
    for path in ('/nodes/other/vzdump/defaults?storage=store1','/nodes/node1/vzdump/defaults?storage=other',
                 '/nodes/node1/vzdump/defaults','/nodes/node1/vzdump/extractconfig',
                 '/nodes/node1/storage/store1/content?content=backup&vmid=102',
                 '/nodes/node1/storage/other/content?content=backup&vmid=101'):
        with pytest.raises(SetupError):client._request('GET',path)
    assert len(calls)==3
    config['features']=['read']
    with pytest.raises(SetupError):client._request('POST','/nodes/node1/vzdump',data=body)
    with pytest.raises(SetupError):client._request('GET','/nodes/node1/storage/store1/content?content=backup&vmid=101')


def test_restore_scope_is_disjoint_and_target_allocation_is_minimal():
    intent=RegistrationIntent(endpoint='https://pve.example.test',owner='test@pve',expires_at=2000000000,
        features=['read','restore'],scope={'nodes':['node1'],'vmids':[101],'restore_vmids':[40001],
            'storages':['source','backup','target'],'backup_storages':['backup'],'restore_storages':['target'],'bridges':['vmbr1']})
    rows=acl_plan(intent)
    allocation={row['path'] for row in rows if row['role']=='GjallarStorageAllocateV1'}
    assert allocation=={'/storage/backup','/storage/target'}
    assert ROLE_PRIVILEGES['GjallarVmRestoreV1']==['VM.Allocate','VM.Audit','VM.Config.Disk','VM.PowerMgmt','VM.GuestAgent.Audit']
    assert 'VM.GuestAgent.Unrestricted' not in ROLE_PRIVILEGES['GjallarVmRestoreV1']
    for patch in ({'restore_vmids':[101]}, {'restore_vmids':[]}, {'restore_storages':['unselected']}):
        with pytest.raises(ValueError):RegistrationIntent.model_validate({**intent.model_dump(),'scope':{**intent.scope.model_dump(),**patch}})
    with pytest.raises(ValueError):RegistrationIntent.model_validate({**intent.model_dump(),'features':['read','backup']})


def test_managed_restore_allows_only_selected_archive_and_isolated_new_vm(managed):
    from app.backups.contracts import restore_body
    client,selection,calls=managed
    config=selection['configuration'];config['features']=['read','restore']
    config['scope'].update(storages=['backup','target'],backup_storages=['backup'],restore_storages=['target'],restore_vmids=[40001],bridges=['vmbr1'])
    archive='backup:backup/vzdump-qemu-101-2026_09_19-05_00_00.vma.zst'
    body=restore_body(new_vmid=40001,name='restored',archive=archive,storage='target',bridge='vmbr1',
        mac='02:00:00:00:00:02',firewall='1',operation_id='vm-restore-'+'a'*64)
    client._request('POST','/nodes/node1/qemu',data=body)
    client._request('GET','/nodes/node1/vzdump/extractconfig',data={'volume':archive})
    client._request('GET','/nodes/node1/storage/backup/content?content=backup&vmid=101')
    client._request('POST','/nodes/node1/qemu/40001/status/start',data={})
    assert len(calls)==4
    for method,path,data in [('POST','/nodes/node1/qemu',{**body,'force':1}),
                            ('POST','/nodes/node1/qemu',{**body,'vmid':101}),
                            ('POST','/nodes/node1/qemu/40001/status/start',{'skiplock':1}),
                            ('PUT','/nodes/node1/qemu/40001/config',{'net0':'virtio,bridge=vmbr1'}),
                            ('GET','/nodes/node1/vzdump/extractconfig',{'volume':archive.replace('101-','102-')}),
                            ('GET','/nodes/node1/vzdump/extractconfig',{'volume':'/tmp/private.vma'}),
                            ('GET','/nodes/node1/vzdump/extractconfig',{'volume':archive,'extra':'x'}),
                            ('DELETE','/nodes/node1/storage/backup/content/'+archive,{})]:
        with pytest.raises(SetupError):client._request(method,path,data=data)
    assert len(calls)==4


def test_migrate_role_does_not_grant_storage_allocation_or_host_modification():
    intent=RegistrationIntent(endpoint='https://pve.example.test',owner='test@pve',expires_at=2000000000,
        features=['read','migrate'],scope={'nodes':['node1','node2'],'vmids':[101],'storages':['nfs'],'bridges':['vmbr1']})
    roles={row['role'] for row in acl_plan(intent)}
    assert ROLE_PRIVILEGES['GjallarVmMigrateV1']==['VM.Migrate','VM.Config.Disk']
    privileges={privilege for role in roles for privilege in ROLE_PRIVILEGES[role]}
    assert not {'Sys.Modify','Datastore.Allocate','Datastore.AllocateSpace','VM.PowerMgmt','VM.Config.Network'} & privileges
    for patch in ({'nodes':['node1']},{'vmids':[]},{'storages':[]},{'bridges':[]}):
        with pytest.raises(ValueError):RegistrationIntent.model_validate({**intent.model_dump(),'scope':{**intent.scope.model_dump(),**patch}})


def test_managed_migration_requires_selected_distinct_nodes_and_fixed_offline_request(managed):
    from app.operations.vm_migrate.domain import request_body
    client,selection,calls=managed
    config=selection['configuration'];config['features']=['read','migrate'];config['scope']['nodes']=['node1','node2']
    client._request('GET','/nodes/node1/qemu/101/migrate?target=node2')
    client._request('POST','/nodes/node1/qemu/101/migrate',data=request_body('node2'))
    assert calls==[('GET','/nodes/node1/qemu/101/migrate',{'target':'node2'}),('POST','/nodes/node1/qemu/101/migrate',request_body('node2'))]
    for method,path,data in [('GET','/nodes/node1/qemu/101/migrate?target=node3',None),
        ('GET','/nodes/node1/qemu/101/migrate?target=node1',None),('GET','/nodes/node1/qemu/101/migrate',None),
        ('GET','/nodes/node1/qemu/101/migrate',{'target':'node2','online':1}),
        ('POST','/nodes/node1/qemu/102/migrate',request_body('node2')),
        ('POST','/nodes/node1/qemu/101/migrate',{**request_body('node2'),'online':1}),
        ('POST','/nodes/node1/qemu/101/migrate',{**request_body('node2'),'targetstorage':'local'}),
        ('POST','/nodes/node1/qemu/101/migrate',{**request_body('node2'),'migration_type':'insecure'})]:
        with pytest.raises(SetupError):client._request(method,path,data=data)
    config['features']=['read']
    with pytest.raises(SetupError):client._request('POST','/nodes/node1/qemu/101/migrate',data=request_body('node2'))
    with pytest.raises(SetupError):client._request('GET','/nodes/node1/qemu/101/migrate?target=node2')
    assert len(calls)==2
