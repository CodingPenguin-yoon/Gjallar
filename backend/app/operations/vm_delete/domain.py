"""Reviewed whole-VM deletion with an explicit, bounded resource manifest."""
import re

from pydantic import BaseModel, ConfigDict, Field
from app.operations.core.domain import operation_digest

ID = r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}'


class DeleteError(RuntimeError):
    def __init__(self, code, message, status_code=409, details=None):
        super().__init__(message)
        self.code, self.status_code, self.details = code, status_code, details or {}

    def to_detail(self):
        return {'code': self.code, 'message': str(self), 'details': self.details}


class DeleteRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    idempotency_key: str = Field(min_length=1, max_length=160, pattern=r'^[A-Za-z0-9_.:-]+$')
    expected_digest: str = Field(pattern=r'^[a-fA-F0-9]{40}$')
    expected_name: str = Field(min_length=1, max_length=255)
    expected_resources_digest: str = Field(pattern=r'^sha256:[a-f0-9]{64}$')
    confirmation: str = Field(min_length=1, max_length=300)
    delete_acknowledged: bool


def validate_target(node_id, vmid):
    if not re.fullmatch(ID, node_id) or not 100 <= vmid <= 999999999:
        raise DeleteError('VM_DELETE_INVALID_TARGET', '노드·VMID 형식을 확인하세요.', 422)


def deletion_identity(config, status, pending, snapshots, *, vmid):
    if status.get('status') != 'stopped':
        raise DeleteError('VM_DELETE_NOT_STOPPED', '정지된 VM만 삭제할 수 있습니다. 강제 종료하지 않습니다.')
    if str(config.get('template', 0)) != '0' or config.get('lock'):
        raise DeleteError('VM_DELETE_LOCKED_OR_TEMPLATE', '템플릿 또는 잠긴 VM은 삭제하지 않습니다.')
    if str(config.get('protection', 0)) != '0':
        raise DeleteError('VM_DELETE_PROTECTED', '삭제 보호가 설정된 VM입니다. 보호를 자동 해제하지 않습니다.')
    if any('pending' in row or row.get('delete') for row in pending):
        raise DeleteError('VM_DELETE_PENDING_CONFIG', '대기 중 설정 변경을 먼저 확인하세요.')
    if [row.get('name') for row in snapshots] != ['current']:
        raise DeleteError('VM_DELETE_SNAPSHOT_UNCONFIRMED', 'snapshot이 있거나 snapshot 목록을 확인할 수 없습니다. 첫 범위에서는 삭제하지 않습니다.')
    if any(re.fullmatch(r'(?:unused|hostpci|usb|virtiofs)[0-9]+', key)
           or key in {'args', 'hookscript', 'efidisk0', 'tpmstate0', 'ivshmem', 'cicustom'} for key in config):
        raise DeleteError('VM_DELETE_CONFIG_UNSUPPORTED', '미사용 disk·외부 장치/스크립트·EFI/TPM·custom cloud-init은 첫 삭제 범위에서 제외합니다.')
    digest = config.get('digest')
    if not isinstance(digest, str) or not re.fullmatch(r'[a-fA-F0-9]{40}', digest):
        raise DeleteError('VM_DELETE_DIGEST_UNAVAILABLE', '현재 설정 변경 감지값을 확인할 수 없습니다.', 503)
    name = config.get('name')
    if not isinstance(name, str) or not name or len(name) > 255:
        raise DeleteError('VM_DELETE_NAME_UNAVAILABLE', '삭제 확인에 사용할 VM 이름을 확인할 수 없습니다.', 503)
    disks = []
    for slot in sorted(key for key in config if re.fullmatch(r'(?:scsi|virtio|sata|ide)[0-9]+', key)):
        value = config[slot]
        if not isinstance(value, str):
            raise DeleteError('VM_DELETE_CONFIG_UNSUPPORTED', '디스크 설정을 확인할 수 없습니다.')
        parts = value.split(',')
        pairs = [part.split('=', 1) for part in parts[1:]]
        if any(len(row) != 2 or not row[0] or not row[1] for row in pairs) or len(dict(pairs)) != len(pairs):
            raise DeleteError('VM_DELETE_CONFIG_UNSUPPORTED', '중복·불명확한 disk 옵션은 지원하지 않습니다.')
        options = dict(pairs)
        if slot == 'ide2' and parts[0] == 'none' and options.get('media') == 'cdrom':
            continue
        if slot == 'scsi0' and options.get('media') != 'cdrom' and options.get('shared', '0') == '0':
            suffix = r'disk-[0-9]+'
        elif slot == 'ide2' and options.get('media') == 'cdrom':
            suffix = 'cloudinit'
        else:
            raise DeleteError('VM_DELETE_CONFIG_UNSUPPORTED', 'scsi0와 선택적 ide2 cloud-init만 지원합니다. 추가 disk·외부 ISO·공유 disk를 확인하세요.')
        match = re.fullmatch(rf'({ID}):{vmid}/vm-{vmid}-{suffix}\.(raw|qcow2)', parts[0])
        if not match:
            raise DeleteError('VM_DELETE_VOLUME_OWNERSHIP', '삭제할 volume이 이 VM 소유의 raw/qcow2인지 확인할 수 없습니다.')
        disks.append({'slot': slot, 'volume_id': parts[0], 'storage_id': match[1], 'format': match[2]})
    if not any(row['slot'] == 'scsi0' for row in disks):
        raise DeleteError('VM_DELETE_CONFIG_UNSUPPORTED', '첫 삭제 범위는 NFS scsi0가 있는 VM입니다.')
    return {'vmid': vmid, 'name': name, 'status': 'stopped', 'digest': digest, 'deleted_volumes': disks}


def validate_storage(storages, storage_id):
    row = next((item for item in storages if item.get('storage') == storage_id), None)
    if (not row or row.get('type') != 'nfs' or row.get('active') not in (1, '1') or row.get('enabled') not in (1, '1')
            or 'images' not in str(row.get('content', '')).split(',')):
        raise DeleteError('VM_DELETE_STORAGE_UNAVAILABLE', '선택한 NFS images storage의 활성 상태를 확인할 수 없습니다.', 503)


def volume_rows(rows, *, storage_id, vmid):
    result = []
    for row in rows:
        volid = row.get('volid')
        if (not isinstance(volid, str) or not re.fullmatch(rf'{re.escape(storage_id)}:{vmid}/[^/]+', volid)
                or type(row.get('vmid')) is not int or row['vmid'] != vmid
                or type(row.get('size')) is not int or row['size'] <= 0 or not isinstance(row.get('format'), str)):
            raise DeleteError('VM_DELETE_VOLUME_OBSERVATION_UNCONFIRMED', '정확한 VM 소유 volume 목록·용량을 확인할 수 없습니다.', 503)
        result.append({'volume_id': volid, 'storage_id': storage_id, 'size_bytes': row['size'], 'format': row['format']})
    if len({row['volume_id'] for row in result}) != len(result):
        raise DeleteError('VM_DELETE_VOLUME_OBSERVATION_UNCONFIRMED', '중복 volume 목록을 삭제 근거로 사용할 수 없습니다.', 503)
    return sorted(result, key=lambda row: row['volume_id'])


def manifest(identity, observed_rows, volume_info):
    volumes = {row['volume_id']: row for row in observed_rows}
    deleted = []
    for disk in identity['deleted_volumes']:
        actual = volume_info[disk['volume_id']]
        row = volumes.get(disk['volume_id'])
        if (row is None or type(actual.get('size')) is not int or actual['size'] <= 0
                or actual['size'] != row['size_bytes'] or actual.get('format') != disk['format'] or row['format'] != disk['format']):
            raise DeleteError('VM_DELETE_VOLUME_OBSERVATION_UNCONFIRMED', '삭제할 volume의 실제 크기·형식을 확인할 수 없습니다.', 503)
        deleted.append({**disk, 'size_bytes': actual['size']})
    ids = {row['volume_id'] for row in deleted}
    resources = {'deleted_volumes': deleted, 'preserved_volumes': [row for row in observed_rows if row['volume_id'] not in ids]}
    return {**identity, **resources, 'resources_digest': operation_digest(resources)}


def check_expected(before, request):
    if not request.delete_acknowledged or request.confirmation != f"{before['vmid']}/{before['name']}":
        raise DeleteError('VM_DELETE_CONFIRMATION_REQUIRED', 'VMID/이름을 그대로 입력하고 복구 불가 삭제 영향을 확인하세요.', 422)
    if (before['digest'], before['name'], before['resources_digest']) != (
            request.expected_digest, request.expected_name, request.expected_resources_digest):
        raise DeleteError('VM_DELETE_STATE_CHANGED', '검토 후 VM 또는 삭제·보존 자원이 변경됐습니다. 다시 검토하세요.')


def verified_task_reference(value, *, node_id, vmid):
    if not isinstance(value, str) or len(value) > 512 or not re.fullmatch(
            rf'UPID:{re.escape(node_id)}:[0-9A-Fa-f]+:[0-9A-Fa-f]+:[0-9A-Fa-f]+:qmdestroy:{vmid}:[A-Za-z0-9_.@!+-]+:', value):
        raise DeleteError('VM_DELETE_DISPATCH_UNKNOWN', '삭제 작업 식별자를 확인하지 못했습니다. 자동 재실행하지 마세요.', 503)
    return value


def deletion_result(before, rows, *, vmid_unused):
    present = {row['volume_id']: row for row in rows}
    deleted = [row['volume_id'] for row in before['deleted_volumes'] if row['volume_id'] not in present]
    remaining = [row['volume_id'] for row in before['deleted_volumes'] if row['volume_id'] in present]
    preserved = [row['volume_id'] for row in before['preserved_volumes'] if present.get(row['volume_id']) == row]
    unconfirmed = [row['volume_id'] for row in before['preserved_volumes'] if present.get(row['volume_id']) != row]
    return {'vmid_unused': vmid_unused, 'deleted_volumes': deleted, 'remaining_volumes': remaining,
            'preserved_volumes': preserved, 'preservation_unconfirmed': unconfirmed}
