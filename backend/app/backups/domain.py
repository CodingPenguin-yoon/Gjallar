"""Secret-free backup inventory and narrowly supported stopped source checks."""
import re
from datetime import datetime
from app.backups.contracts import ARCHIVE, ID, OPERATION
from app.operations.core.domain import operation_digest


class BackupError(RuntimeError):
    def __init__(self, code, message, status_code=409, details=None):
        super().__init__(message)
        self.code, self.status_code, self.details = code, status_code, details or {}
    def to_detail(self):
        return {'code': self.code, 'message': str(self), 'details': self.details}


def target(node_id, vmid, storage):
    if (not isinstance(node_id, str) or not re.fullmatch(ID, node_id) or type(vmid) is not int or not 100 <= vmid <= 999999999
            or not isinstance(storage, str) or not re.fullmatch(ID, storage)):
        raise BackupError('VM_BACKUP_TARGET_INVALID', '노드·VMID·storage를 확인하세요.', 422)


def archives(rows, *, storage, vmid):
    if not isinstance(rows, list) or len(rows) > 10000 or any(not isinstance(row, dict) for row in rows):
        raise BackupError('VM_BACKUP_LIST_UNAVAILABLE', '백업 목록 형식 또는 크기를 확인할 수 없습니다.', 503)
    result, seen = [], set()
    for row in rows:
        volume = row.get('volid')
        match = re.fullmatch(ARCHIVE, volume) if isinstance(volume, str) else None
        if (not match or match[1] != storage or int(match[2]) != vmid or type(row.get('vmid')) is not int or row['vmid'] != vmid
                or type(row.get('size')) is not int or row['size'] <= 0 or type(row.get('ctime')) is not int or row['ctime'] <= 0
                or row.get('content') != 'backup' or volume in seen):
            raise BackupError('VM_BACKUP_LIST_UNCONFIRMED', '정확한 소유 VMID·시점·크기의 백업 목록을 확인할 수 없습니다.', 503)
        try: datetime.strptime(match[3], '%Y_%m_%d-%H_%M_%S')
        except ValueError: raise BackupError('VM_BACKUP_LIST_UNCONFIRMED', '백업 파일의 시점을 확인할 수 없습니다.', 503) from None
        marker = row.get('notes')
        result.append({'volume_id': volume, 'vmid': vmid, 'storage_id': storage, 'size_bytes': row['size'],
            'created_at': row['ctime'], 'format': 'vma' + ('.' + match[4] if match[4] else ''),
            'operation_marker': marker if isinstance(marker, str) and re.fullmatch(OPERATION, marker) else None})
        seen.add(volume)
    return sorted(result, key=lambda row: (row['created_at'], row['volume_id']), reverse=True)


def source(config, status, pending, snapshots, *, vmid):
    if status.get('status') != 'stopped' or config.get('lock') or str(config.get('template', 0)) != '0':
        raise BackupError('VM_BACKUP_NOT_STOPPED', '정지 상태이고 잠금이 없는 일반 VM만 백업합니다.')
    if any('pending' in row or row.get('delete') for row in pending) or [row.get('name') for row in snapshots] != ['current']:
        raise BackupError('VM_BACKUP_PENDING_OR_SNAPSHOTS', '대기 설정·snapshot이 없는 VM만 지원합니다.')
    if (any(re.fullmatch(r'(?:unused|hostpci|usb|virtiofs)[0-9]+', key) or key in {'args', 'hookscript', 'efidisk0', 'tpmstate0', 'ivshmem', 'cicustom'} for key in config)
            or {key for key in config if re.fullmatch(r'(?:scsi|virtio|sata|ide)[0-9]+', key)} != {'scsi0', 'ide2'}):
        raise BackupError('VM_BACKUP_CONFIG_UNSUPPORTED', '첫 백업 범위는 외부 장치/스크립트 없이 scsi0와 ide2 cloud-init만 있는 VM입니다.')
    digest, name = config.get('digest'), config.get('name')
    if not isinstance(digest, str) or not re.fullmatch(r'[a-fA-F0-9]{40}', digest) or not isinstance(name, str) or not 1 <= len(name) <= 255:
        raise BackupError('VM_BACKUP_IDENTITY_UNAVAILABLE', '원본 VM 이름·설정 digest를 확인할 수 없습니다.', 503)
    volumes = []
    for slot in ('scsi0', 'ide2'):
        parts = config[slot].split(',') if isinstance(config[slot], str) else []
        pairs = [part.split('=', 1) for part in parts[1:]]
        if not parts or any(len(pair) != 2 or not pair[0] or not pair[1] for pair in pairs) or len(dict(pairs)) != len(pairs):
            raise BackupError('VM_BACKUP_DISK_UNSUPPORTED', 'disk 옵션을 확인할 수 없습니다.')
        opts = dict(pairs)
        suffix = r'disk-[0-9]+' if slot == 'scsi0' else 'cloudinit'
        match = re.fullmatch(rf'({ID}):{vmid}/vm-{vmid}-{suffix}\.(raw|qcow2)', parts[0])
        if (not match or opts.get('shared', '0') != '0' or opts.get('backup', '1') != '1'
                or slot == 'scsi0' and opts.get('media') == 'cdrom' or slot == 'ide2' and opts.get('media') != 'cdrom'):
            raise BackupError('VM_BACKUP_DISK_UNSUPPORTED', '정확한 VM 소유 disk와 백업 포함 설정을 확인하세요.')
        volumes.append({'slot': slot, 'volume_id': parts[0], 'storage_id': match[1], 'format': match[2]})
        if slot == 'scsi0':
            size = re.fullmatch(r'([1-9][0-9]*)([MGT])', opts.get('size', ''))
            if not size: raise BackupError('VM_BACKUP_SIZE_UNAVAILABLE', '원본 disk의 가상 용량을 확인할 수 없습니다.')
            size_bytes = int(size[1]) * 1024 ** {'M': 2, 'G': 3, 'T': 4}[size[2]]
    return {'vmid': vmid, 'name': name, 'status': 'stopped', 'digest': digest, 'volumes': volumes,
            'config_fingerprint': operation_digest({key: value for key, value in config.items() if key != 'digest'}),
            'required_free_bytes': size_bytes + max(1024 ** 3, size_bytes // 10)}


def storage_available(rows, storage, *, content='backup'):
    selected = [row for row in rows if row.get('storage') == storage]
    if (len(selected) != 1 or selected[0].get('type') != 'nfs' or selected[0].get('active') not in (1, '1')
            or selected[0].get('enabled') not in (1, '1') or content not in str(selected[0].get('content', '')).split(',')):
        raise BackupError('VM_BACKUP_STORAGE_UNSUPPORTED', '선택한 활성 NFS storage의 지원 content를 확인하세요.')
    return selected[0]
