"""First full-clone contract: stopped single-disk NFS VM, unchanged source."""
from decimal import Decimal
import re
import uuid

from pydantic import BaseModel, ConfigDict, Field

ID = r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}'
VOLUME = re.compile(rf'({ID}):([0-9]+)/vm-([0-9]+)-disk-[0-9]+\.(raw|qcow2)')


class CloneError(RuntimeError):
    def __init__(self, code, message, status_code=409, details=None):
        super().__init__(message)
        self.code, self.status_code, self.details = code, status_code, details or {}

    def to_detail(self):
        return {'code': self.code, 'message': str(self), 'details': self.details}


class CloneRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    idempotency_key: str = Field(min_length=1, max_length=160, pattern=r'^[A-Za-z0-9_.:-]+$')
    expected_digest: str = Field(pattern=r'^[a-fA-F0-9]{40}$')
    expected_name: str = Field(max_length=255)
    expected_volume: str = Field(min_length=1, max_length=255)
    expected_size_bytes: int = Field(gt=0)
    new_vmid: int = Field(ge=100, le=999999999)
    name: str = Field(min_length=1, max_length=63, pattern=r'^[A-Za-z0-9][A-Za-z0-9.-]*$')
    storage_id: str = Field(pattern=rf'^{ID}$')
    guest_identity_acknowledged: bool


def validate_target(node_id, vmid, new_vmid, storage_id):
    if (not re.fullmatch(ID, node_id) or not 100 <= vmid <= 999999999
            or not 100 <= new_vmid <= 999999999 or not re.fullmatch(ID, storage_id) or vmid == new_vmid):
        raise CloneError('VM_CLONE_INVALID_TARGET', '서로 다른 원본·대상 VMID와 node/storage를 확인하세요.', 422)


def options(value, *, volume=False):
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise CloneError('VM_CLONE_CONFIG_UNSUPPORTED', '원본 장치 설정을 확인할 수 없습니다.')
    parts = value.split(',')
    rows = [part.split('=', 1) for part in (parts[1:] if volume else parts)]
    if any(len(row) != 2 or not row[0] or not row[1] for row in rows) or len(dict(rows)) != len(rows):
        raise CloneError('VM_CLONE_CONFIG_UNSUPPORTED', '중복·불명확한 장치 옵션은 지원하지 않습니다.')
    return (parts[0], dict(rows)) if volume else dict(rows)


def nfs_storage(storages, storage_id):
    row = next((item for item in storages if item.get('storage') == storage_id), None)
    if (not row or row.get('type') != 'nfs' or row.get('active') not in (1, '1')
            or row.get('enabled') not in (1, '1') or 'images' not in str(row.get('content', '')).split(',')):
        raise CloneError('VM_CLONE_STORAGE_UNSUPPORTED', 'VM images를 지원하는 활성 NFS storage를 선택하세요.')
    return {'storage_id': storage_id, 'type': 'nfs'}


def clone_identity(config, status, pending, *, vmid):
    if status.get('status') != 'stopped':
        raise CloneError('VM_CLONE_NOT_STOPPED', '정지된 VM만 복제하고 결과를 확인할 수 있습니다.')
    if str(config.get('template', 0)) != '0' or config.get('lock'):
        raise CloneError('VM_CLONE_LOCKED_OR_TEMPLATE', '일반 VM의 full clone만 지원합니다. template·잠금 상태를 확인하세요.')
    if any('pending' in row or row.get('delete') for row in pending):
        raise CloneError('VM_CLONE_PENDING_CONFIG', '대기 중 VM 설정을 먼저 확인하세요.')
    if str(config.get('onboot', 0)) != '0':
        raise CloneError('VM_CLONE_AUTOSTART_ENABLED', '원본의 자동 시작(onboot)을 먼저 끄고 다시 검토하세요. 복제본은 정지 상태로 유지합니다.')
    digest = config.get('digest')
    if not isinstance(digest, str) or not re.fullmatch(r'[a-fA-F0-9]{40}', digest):
        raise CloneError('VM_CLONE_DIGEST_UNAVAILABLE', '현재 설정 변경 감지값을 확인하지 못했습니다.', 503)
    if any(re.fullmatch(r'(?:hostpci|usb|virtiofs|unused|net)[0-9]+', key) and key != 'net0'
           or key in {'args', 'hookscript', 'efidisk0', 'tpmstate0', 'ivshmem', 'cicustom'} for key in config):
        raise CloneError('VM_CLONE_CONFIG_UNSUPPORTED', '추가 NIC·미사용 disk·외부 장치/스크립트·EFI/TPM·custom cloud-init은 첫 복제 범위에서 제외합니다.')
    if 'custom-' in str(config.get('cpu', '')):
        raise CloneError('VM_CLONE_CONFIG_UNSUPPORTED', '사용자 정의 CPU 모델은 첫 복제 범위에서 제외합니다.')
    volume_id, disk_options = options(config.get('scsi0'), volume=True)
    volume = VOLUME.fullmatch(volume_id)
    if not volume or int(volume[2]) != vmid or int(volume[3]) != vmid:
        raise CloneError('VM_CLONE_VOLUME_OWNERSHIP', '이 VM 소유의 NFS raw/qcow2 scsi0만 지원합니다.')
    if disk_options.get('media') == 'cdrom' or disk_options.get('shared', '0') != '0' or disk_options.get('ro', '0') != '0':
        raise CloneError('VM_CLONE_CONFIG_UNSUPPORTED', '공유·읽기 전용·CDROM scsi0는 지원하지 않습니다.')
    size = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)([KMGT]?)', disk_options.get('size', ''))
    if not size:
        raise CloneError('VM_CLONE_SIZE_UNAVAILABLE', '설정의 디스크 용량을 확인할 수 없습니다.', 503)
    size_bytes = Decimal(size[1]) * 1024 ** {'': 0, 'K': 1, 'M': 2, 'G': 3, 'T': 4}[size[2]]
    if size_bytes <= 0 or size_bytes != int(size_bytes):
        raise CloneError('VM_CLONE_SIZE_UNAVAILABLE', '정확한 디스크 bytes를 확인할 수 없습니다.', 503)
    cloudinit = None
    for key in config:
        if re.fullmatch(r'(?:scsi|virtio|sata|ide)[0-9]+', key) and key != 'scsi0':
            media, fields = options(config[key], volume=True)
            match = re.fullmatch(rf'({ID}):{vmid}/vm-{vmid}-cloudinit\.(raw|qcow2)', media)
            if key != 'ide2' or not match or fields.get('media') != 'cdrom':
                raise CloneError('VM_CLONE_CONFIG_UNSUPPORTED', 'scsi0와 선택적 ide2 cloud-init만 지원합니다. 추가 disk·외부 ISO를 제거한 범위를 사용하세요.')
            cloudinit = {'storage_id': match[1], 'volume_id': media}
    nic = options(config.get('net0'))
    model, mac = next(iter(nic.items()))
    if (model not in {'virtio', 'e1000', 'rtl8139', 'vmxnet3'}
            or not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', mac)
            or not re.fullmatch(ID, nic.get('bridge', '')) or 'trunks' in nic):
        raise CloneError('VM_CLONE_CONFIG_UNSUPPORTED', '기존 단일 net0의 모델·MAC·bridge를 확인하세요. VLAN trunk는 지원하지 않습니다.')
    smbios = options(config['smbios1']) if config.get('smbios1') else {}
    try:
        cores, memory = int(config['cores']), int(config['memory'])
        sockets = int(config.get('sockets', 1))
    except (KeyError, TypeError, ValueError):
        raise CloneError('VM_CLONE_CONFIG_UNSUPPORTED', 'CPU·메모리 설정을 확인할 수 없습니다.') from None
    return {'vmid': vmid, 'name': str(config.get('name', '')), 'digest': digest, 'status': 'stopped', 'onboot': 0,
            'volume_id': volume_id, 'storage_id': volume[1], 'format': volume[4], 'size_bytes': int(size_bytes),
            'disk_options': disk_options, 'cloudinit': cloudinit, 'nic': nic, 'model': model, 'mac': mac,
            'cores': cores, 'memory_mib': memory, 'sockets': sockets, 'smbios_uuid': smbios.get('uuid'),
            'operation_marker': config.get('description') if re.fullmatch(r'vm-clone-[a-f0-9]{64}', str(config.get('description', ''))) else None}


def confirm_volume(identity, storages, volume):
    nfs_storage(storages, identity['storage_id'])
    if (type(volume.get('size')) is not int or volume['size'] != identity['size_bytes']
            or volume.get('format') != identity['format']):
        raise CloneError('VM_CLONE_SIZE_UNCONFIRMED', '현재 config와 실제 volume 용량·형식이 일치하지 않습니다.', 503)
    if identity['cloudinit']:
        nfs_storage(storages, identity['cloudinit']['storage_id'])
    return identity


def check_expected(before, request):
    source = before['source']
    if not request.guest_identity_acknowledged:
        raise CloneError('VM_CLONE_IDENTITY_ACK_REQUIRED', '복제되는 guest IP·hostname·SSH host key 충돌 위험을 확인하세요.', 422)
    if (source['digest'], source['name'], source['volume_id'], source['size_bytes']) != (
            request.expected_digest, request.expected_name, request.expected_volume, request.expected_size_bytes):
        raise CloneError('VM_CLONE_STATE_CHANGED', '검토 후 원본이 변경됐습니다. 다시 검토하세요.')


def verified_task_reference(value, *, node_id, vmid):
    if not isinstance(value, str) or len(value) > 512 or not re.fullmatch(
            rf'UPID:{re.escape(node_id)}:[0-9A-Fa-f]+:[0-9A-Fa-f]+:[0-9A-Fa-f]+:qmclone:{vmid}:[A-Za-z0-9_.@!+-]+:', value):
        raise CloneError('VM_CLONE_DISPATCH_UNKNOWN', '원본 VM에 연결된 복제 작업 식별자를 확인하지 못했습니다.', 503)
    return value


def matches(after, requested, before):
    original, source, target = before['source'], after['source'], after['destination']
    try:
        new_uuid = str(uuid.UUID(target['smbios_uuid']))
    except (ValueError, AttributeError, TypeError):
        return False
    expected_nic = {**original['nic'], original['model']: target['mac']}
    return (source == original and target['vmid'] == requested['new_vmid'] and target['name'] == requested['name']
            and target['operation_marker'] == after['expected_marker']
            and target['storage_id'] == requested['storage_id'] and target['volume_id'] != original['volume_id']
            and all(target[key] == original[key] for key in ('format', 'size_bytes', 'cores', 'memory_mib', 'sockets', 'disk_options'))
            and target['mac'].lower() != original['mac'].lower() and target['nic'] == expected_nic
            and new_uuid.lower() != str(original['smbios_uuid']).lower()
            and bool(target['cloudinit']) == bool(original['cloudinit'])
            and (not target['cloudinit'] or target['cloudinit']['storage_id'] == requested['storage_id']))
