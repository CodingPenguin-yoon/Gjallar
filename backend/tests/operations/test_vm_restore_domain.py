import json
import pytest
from app.backups.archive import parse_archive_config, hardware_fingerprint
from app.backups.domain import BackupError
from app.operations.vm_restore.domain import isolated_mac, task_reference

RAW='''name: source-vm
cores: 2
memory: 2048
scsi0: nfs:40000/vm-40000-disk-0.qcow2,size=10G,iothread=1
ide2: nfs:40000/vm-40000-cloudinit.qcow2,media=cdrom
net0: virtio=02:00:00:00:00:01,bridge=vmbr1,firewall=1
onboot: 1
agent: 1
cipassword: synthetic-password
sshkeys: synthetic-key
smbios1: uuid=old-uuid,manufacturer=example
vmgenid: old-generation
#qmdump#map:scsi0:drive-scsi0:nfs:qcow2:
'''


def test_archive_manifest_never_exposes_credentials_and_tolerates_restored_ids():
    config,manifest=parse_archive_config(RAW,source_vmid=40000)
    assert 'synthetic' not in json.dumps(manifest)
    assert manifest['source_mac']=='02:00:00:00:00:01'
    after={**config,'cores':2,'memory':2048,'onboot':0,'name':'restored','description':'operation-marker',
        'net0':'virtio=02:00:00:00:00:02,bridge=vmbr2,link_down=1',
        'scsi0':'other:40001/vm-40001-disk-3.raw,iothread=1,size=10G',
        'ide2':'other:40001/vm-40001-cloudinit.raw,media=cdrom',
        'smbios1':'uuid=new-uuid,manufacturer=example','vmgenid':'new-generation'}
    assert hardware_fingerprint(after)==manifest['hardware_fingerprint']
    for key,value in [('cores',4),('cipassword','changed'),('scsi0',after['scsi0'].replace('10G','12G'))]:
        assert hardware_fingerprint({**after,key:value})!=manifest['hardware_fingerprint']


@pytest.mark.parametrize('change',[
    lambda s:s+'args: -device host\n',lambda s:s+'hookscript: nfs:snippets/custom\n',lambda s:s+'hostpci0: 00:01.0\n',
    lambda s:s+'net1: virtio=02:00:00:00:00:03,bridge=vmbr1\n',lambda s:s+'[snapshot]\n',
    lambda s:s+'cores: 4\n',lambda s:s.replace('size=10G','size=10G,backup=0'),
    lambda s:s.replace('firewall=1','firewall=1,tag=100'),lambda s:s.replace('firewall=1','firewall=1,trunks=100;200'),
    lambda s:s.replace('#qmdump#map:scsi0:drive-scsi0:nfs:qcow2:',''),
    lambda s:s.replace('drive-scsi0:nfs:','drive-scsi0:other:'),
    lambda s:s.replace('drive-scsi0:nfs:qcow2:', 'drive-scsi0:nfs:raw:'),
    lambda s:s+'serial0: /dev/ttyS0\n',lambda s:s+'bios: ovmf\n',lambda s:s.replace('40000/vm-40000','40001/vm-40001'),
    lambda s:s+'\0',lambda s:s*10000,
])
def test_unsafe_ambiguous_or_incomplete_archive_is_rejected(change):
    with pytest.raises(BackupError):parse_archive_config(change(RAW),source_vmid=40000)


def test_restore_mac_stable_local_and_distinct_from_source():
    params={'archive':'store:backup/vzdump-qemu-40000-2026_09_19-05_00_00.vma.zst','node':'node1','new_vmid':40001,'source_mac':'02:00:00:00:00:01'}
    mac=isolated_mac(**params)
    assert mac.startswith('02:') and mac==isolated_mac(**params)
    assert mac!=isolated_mac(**{**params,'new_vmid':40002})
    assert mac!=isolated_mac(**{**params,'source_mac':mac})


def test_restore_task_must_bind_new_vm_and_node():
    value='UPID:node1:0001:0002:0003:qmrestore:40001:test@pve!test:'
    assert task_reference(value,node_id='node1',vmid=40001)==value
    for invalid in (value.replace('40001','40000'),value.replace('node1','node2'),value.replace('qmrestore','qmcreate'),'OK'):
        with pytest.raises(BackupError):task_reference(invalid,node_id='node1',vmid=40001)


def test_restore_transport_requires_link_down_and_separate_selected_target():
    from app.backups.contracts import restore_body, restore_request_allowed
    scope={'vmids':[40000],'restore_vmids':[40001],'storages':['nfs','target'],
        'backup_storages':['nfs'],'restore_storages':['target'],'bridges':['vmbr1']}
    body=restore_body(new_vmid=40001,name='restored',archive='nfs:backup/vzdump-qemu-40000-2026_09_19-05_00_00.vma.zst',
        storage='target',bridge='vmbr1',mac='02:00:00:00:00:02',firewall='1',operation_id='vm-restore-'+'a'*64)
    assert restore_request_allowed('POST',['nodes','node1','qemu'],body,scope)
    for patch in ({'force':1},{'unique':0},{'start':1},{'onboot':1},{'live-restore':1},{'vmid':40000},
                  {'storage':'nfs'},{'archive':'/tmp/private.vma'},{'description':'other'},
                  {'net0':body['net0'].replace('link_down=1','link_down=0')},
                  {'net0':body['net0'].replace('vmbr1','vmbr0')},{'hookscript':'x'},{'start':False}):
        assert not restore_request_allowed('POST',['nodes','node1','qemu'],{**body,**patch},scope)
