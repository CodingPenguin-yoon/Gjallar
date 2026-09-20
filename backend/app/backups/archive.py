"""Read only the supported QEMU backup configuration; never expose raw secrets."""
import re
from app.backups.domain import BackupError, source
from app.operations.core.domain import operation_digest

# Unsupported host integrations must not be carried into a restored VM implicitly.
ALLOWED = frozenset('agent balloon bios boot bootdisk ciuser cipassword sshkeys citype ciupgrade cores cpu description ide2 ipconfig0 machine memory meta name nameserver net0 numa onboot ostype protection scsi0 scsihw searchdomain serial0 smbios1 sockets startup tablet tags template vga vmgenid'.split())


def options(value):
    parts = value.split(',') if isinstance(value, str) else []
    pairs = [part.split('=', 1) for part in parts]
    if not parts or any(len(pair) != 2 or not pair[0] or not pair[1] for pair in pairs) or len(dict(pairs)) != len(pairs):
        raise BackupError('VM_RESTORE_CONFIG_UNSUPPORTED', 'archive 장치 옵션을 확인할 수 없습니다.')
    return dict(pairs)


def parse_archive_config(raw, *, source_vmid):
    if not isinstance(raw, str) or not raw or len(raw.encode('utf-8')) > 262144 or '\x00' in raw:
        raise BackupError('VM_RESTORE_ARCHIVE_CONFIG_INVALID', '백업 설정 원문 형식·크기를 확인할 수 없습니다.', 503)
    config, hints = {}, {}
    for line in raw.splitlines():
        if line.startswith('#qmdump#map:'):
            match = re.fullmatch(r'#qmdump#map:(scsi0):(drive-scsi0):([A-Za-z0-9][A-Za-z0-9_.-]{0,63}):(raw|qcow2):', line)
            if not match or match[1] in hints:
                raise BackupError('VM_RESTORE_ARCHIVE_MAP_INVALID', '첫 지원 root disk mapping만 있는 백업을 선택하세요.')
            hints[match[1]] = {'storage_id':match[3], 'format':match[4]}
            continue
        if not line.strip() or line.startswith('#'): continue
        match = re.fullmatch(r'([a-z][a-z0-9_-]*):\s*(.*)', line)
        if not match or match[1] not in ALLOWED or match[1] in config:
            raise BackupError('VM_RESTORE_CONFIG_UNSUPPORTED', '지원하지 않는 설정·section·중복 key가 있는 백업입니다.')
        config[match[1]] = match[2]
    # Reuse the source ownership/drive policy. The archive has no runtime digest.
    config['digest'] = '0' * 40
    identity = source(config, {'status':'stopped'}, [], [{'name':'current'}], vmid=source_vmid)
    root = identity['volumes'][0]
    if hints != {'scsi0': {'storage_id':root['storage_id'], 'format':root['format']}}:
        raise BackupError('VM_RESTORE_ARCHIVE_MAP_INVALID', '백업 root disk와 archive mapping이 일치하지 않습니다.')
    nic = options(config.get('net0'))
    if (not {'virtio','bridge'} <= set(nic) <= {'virtio','bridge','firewall','link_down'}
            or not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}',nic['virtio'])
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',nic['bridge'])
            or nic.get('firewall','0') not in {'0','1'} or nic.get('link_down','0') not in {'0','1'}):
        raise BackupError('VM_RESTORE_NETWORK_UNSUPPORTED', '첫 복원은 VLAN/trunk/추가 옵션 없는 virtio net0 하나를 지원합니다.')
    if config.get('serial0','socket') != 'socket' or config.get('vga','std') not in {'std','serial0','qxl','virtio','none'}:
        raise BackupError('VM_RESTORE_DEVICE_UNSUPPORTED', 'host 장치 경로가 없는 표준 화면/serial만 지원합니다.')
    if config.get('bios','seabios') != 'seabios':
        raise BackupError('VM_RESTORE_DEVICE_UNSUPPORTED', '첫 복원은 별도 EFI disk가 없는 SeaBIOS VM입니다.')
    size = re.search(r'(?:^|,)size=([1-9][0-9]*)([MGT])(?:,|$)', config['scsi0'])
    return config, {**identity, 'size_bytes': int(size[1]) * 1024 ** {'M':2,'G':3,'T':4}[size[2]],
                    'smbios_uuid': options(config['smbios1']).get('uuid') if config.get('smbios1') else None,
                    'vmgenid': config.get('vmgenid'), 'archive_config_fingerprint': operation_digest({'archive_config':raw}),
                    'hardware_fingerprint': hardware_fingerprint(config), 'source_mac':nic['virtio'].upper(),
                    'source_bridge':nic['bridge'], 'firewall':nic.get('firewall','0')}


def hardware_fingerprint(config):
    """PVE restores IDs and volume paths; compare every other supported property."""
    excluded = {'digest','name','description','net0','onboot','vmgenid','lock'}
    normalized = {key:str(value) for key,value in config.items() if key not in excluded}
    for slot in ('scsi0','ide2'):
        value = config.get(slot)
        if not isinstance(value,str):
            raise BackupError('VM_RESTORE_HARDWARE_UNCONFIRMED','복원 disk 구성을 확인할 수 없습니다.',503)
        parts = value.split(',')
        opts = options(','.join(parts[1:])) if len(parts)>1 else {}
        opts.pop('format',None)  # PVE chooses the supported storage format.
        normalized[slot] = opts
    if 'smbios1' in normalized:
        smbios=options(normalized['smbios1']);smbios.pop('uuid',None)
        normalized['smbios1']=smbios
    return operation_digest(normalized)
