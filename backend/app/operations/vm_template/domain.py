"""Bounded prepared-VM conversion; guest readiness is an explicit attestation."""
import re

from pydantic import BaseModel, ConfigDict, Field
from app.operations.core.domain import operation_digest

ID = r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}'


class TemplateError(RuntimeError):
    def __init__(self, code, message, status_code=409, details=None):
        super().__init__(message)
        self.code, self.status_code, self.details = code, status_code, details or {}

    def to_detail(self):
        return {'code': self.code, 'message': str(self), 'details': self.details}


class TemplateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    idempotency_key: str = Field(min_length=1, max_length=160, pattern=r'^[A-Za-z0-9_.:-]+$')
    expected_digest: str = Field(pattern=r'^[a-fA-F0-9]{40}$')
    expected_name: str = Field(min_length=1, max_length=255)
    expected_resources_digest: str = Field(pattern=r'^sha256:[a-f0-9]{64}$')
    confirmation: str = Field(min_length=1, max_length=300)
    guest_prepared: bool
    conversion_acknowledged: bool


def validate_target(node_id, vmid):
    if not re.fullmatch(ID, node_id) or type(vmid) is not int or not 100 <= vmid <= 999999999:
        raise TemplateError('VM_TEMPLATE_INVALID_TARGET', '노드·VMID 형식을 확인하세요.', 422)


def drive(value):
    if not isinstance(value, str):
        raise TemplateError('VM_TEMPLATE_DISK_UNSUPPORTED', 'disk 설정을 확인할 수 없습니다.')
    parts = value.split(',')
    pairs = [part.split('=', 1) for part in parts[1:]]
    if any(len(row) != 2 or not row[0] or not row[1] for row in pairs) or len(dict(pairs)) != len(pairs):
        raise TemplateError('VM_TEMPLATE_DISK_UNSUPPORTED', '불명확한 disk 옵션은 지원하지 않습니다.')
    return parts[0], dict(pairs)


def inspect_vm(config, status, pending, snapshots, *, vmid, converted=False):
    if status.get('status') != 'stopped' or config.get('lock'):
        raise TemplateError('VM_TEMPLATE_NOT_STOPPED', '정지 상태이고 잠금이 없는 VM만 확인할 수 있습니다.')
    if str(config.get('template', 0)) != ('1' if converted else '0'):
        raise TemplateError('VM_TEMPLATE_STATE_UNCONFIRMED', '기대하는 VM/템플릿 상태가 아닙니다.')
    if any('pending' in row or row.get('delete') for row in pending):
        raise TemplateError('VM_TEMPLATE_PENDING_CONFIG', '대기 중 설정 변경을 먼저 확인하세요.')
    if [row.get('name') for row in snapshots] != ['current']:
        raise TemplateError('VM_TEMPLATE_SNAPSHOT_UNCONFIRMED', 'snapshot이 있거나 목록을 확인할 수 없습니다.')
    forbidden = any(re.fullmatch(r'(?:unused|hostpci|usb|virtiofs)[0-9]+', key)
                    or key in {'args', 'hookscript', 'efidisk0', 'tpmstate0', 'ivshmem', 'cicustom'} for key in config)
    slots = {key for key in config if re.fullmatch(r'(?:scsi|virtio|sata|ide)[0-9]+', key)}
    if forbidden or slots != {'scsi0', 'ide2'}:
        raise TemplateError('VM_TEMPLATE_CONFIG_UNSUPPORTED', '첫 전환 범위는 scsi0와 ide2 cloud-init만 있는 VM입니다. 외부 장치/스크립트는 제외합니다.')
    agent = str(config.get('agent', '0')).split(',')
    if not ('enabled=1' in agent or agent[0] == '1'):
        raise TemplateError('VM_TEMPLATE_AGENT_REQUIRED', '배포 검증을 위해 guest agent 설정을 활성화한 VM을 준비하세요.')
    digest, name = config.get('digest'), config.get('name')
    if (not isinstance(digest, str) or not re.fullmatch(r'[a-fA-F0-9]{40}', digest)
            or not isinstance(name, str) or not 1 <= len(name) <= 255):
        raise TemplateError('VM_TEMPLATE_IDENTITY_UNAVAILABLE', '설정 변경 감지값과 이름을 확인할 수 없습니다.', 503)
    volumes = []
    normalized = {key: value for key, value in config.items() if key not in {'digest', 'template'}}
    for slot in ('scsi0', 'ide2'):
        volume, options = drive(config[slot])
        prefix = 'base' if converted and slot == 'scsi0' else 'vm'
        suffix = r'disk-[0-9]+' if slot == 'scsi0' else 'cloudinit'
        match = re.fullmatch(rf'({ID}):{vmid}/{prefix}-{vmid}-{suffix}\.(raw|qcow2)', volume)
        if (not match or options.get('shared', '0') != '0'
                or slot == 'scsi0' and options.get('media') == 'cdrom'
                or slot == 'ide2' and options.get('media') != 'cdrom'):
            raise TemplateError('VM_TEMPLATE_VOLUME_OWNERSHIP', '정확한 VM 소유 scsi0와 cloud-init volume을 확인할 수 없습니다.')
        volumes.append({'slot': slot, 'volume_id': volume, 'storage_id': match[1], 'format': match[2]})
        normalized[slot] = {'volume': '<converted-root>' if slot == 'scsi0' else volume, 'options': options}
    # Never persist raw cloud-init passwords, public keys, or guest customization.
    return {'vmid': vmid, 'name': name, 'digest': digest, 'status': 'stopped', 'template': converted,
            'volumes': volumes, 'config_fingerprint': operation_digest(normalized), 'guest_readiness': 'operator_attestation_required'}


def check_expected(before, request):
    if not request.guest_prepared or not request.conversion_acknowledged or request.confirmation != f"{before['vmid']}/{before['name']}":
        raise TemplateError('VM_TEMPLATE_CONFIRMATION_REQUIRED', 'VMID/이름과 게스트 준비·전환 영향을 모두 확인하세요.', 422)
    if (before['digest'], before['name'], before['resources_digest']) != (
            request.expected_digest, request.expected_name, request.expected_resources_digest):
        raise TemplateError('VM_TEMPLATE_STATE_CHANGED', '검토 후 설정 또는 volume이 변경됐습니다. 다시 검토하세요.')


def verified_task_reference(value, *, node_id, vmid):
    if not isinstance(value, str) or len(value) > 512 or not re.fullmatch(
            rf'UPID:{re.escape(node_id)}:[0-9A-Fa-f]+:[0-9A-Fa-f]+:[0-9A-Fa-f]+:qmtemplate:{vmid}:[A-Za-z0-9_.@!+-]+:', value):
        raise TemplateError('VM_TEMPLATE_DISPATCH_UNKNOWN', '전환 작업 식별자를 확인하지 못했습니다. 자동 재실행하지 마세요.', 503)
    return value
