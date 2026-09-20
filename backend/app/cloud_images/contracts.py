"""Pure contracts shared by image preparation and managed transport policy."""
import re

from pydantic import BaseModel, ConfigDict, Field
from app.cloud_images.catalog import ImageError, image_by_id

IDENTIFIER = r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'
VM_PRIVILEGES = ['VM.Allocate', 'VM.Audit', 'VM.Config.CPU', 'VM.Config.Memory',
                 'VM.Config.HWType', 'VM.Config.Options', 'VM.Config.Disk', 'VM.Config.Network']


class BuildInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    image_id: str = Field(min_length=1, max_length=100)
    name: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9.-]{0,62}$')
    storage_id: str = Field(pattern=IDENTIFIER)
    staging_storage_id: str = Field(pattern=IDENTIFIER)
    bridge_id: str = Field(pattern=IDENTIFIER)


class BuildRequest(BuildInput):
    idempotency_key: str = Field(min_length=1, max_length=160, pattern=r'^[A-Za-z0-9_.:-]+$')
    expected_review_digest: str = Field(pattern=r'^sha256:[a-f0-9]{64}$')
    confirmation: str = Field(min_length=1, max_length=300)
    image_build_acknowledged: bool


def validate_build(node_id, vmid, request):
    image_by_id(request.image_id)
    if not re.fullmatch(IDENTIFIER, node_id) or type(vmid) is not int or not 100 <= vmid <= 999999999:
        raise ImageError('IMAGE_BUILD_INVALID_TARGET', '노드·VMID를 확인하세요.', 422)
    if isinstance(request, BuildRequest) and (not request.image_build_acknowledged or request.confirmation != f'{vmid}/{request.name}'):
        raise ImageError('IMAGE_BUILD_CONFIRMATION_REQUIRED', '새 VMID/이름과 이미지 제작 영향을 확인하세요.', 422)


def upload_filename(vmid, operation_id):
    if not re.fullmatch(r'vm-image-build-[a-f0-9]{64}', operation_id):
        raise ImageError('IMAGE_BUILD_IDENTITY_INVALID', '제작 작업의 소유 식별자를 확인할 수 없습니다.', 503)
    return f'gjallar-image-{vmid}-{operation_id.removeprefix("vm-image-build-")}.qcow2'


def vm_create_payload(*, vmid, name, storage_id, bridge_id, source_volume, operation_id):
    return {'vmid': vmid, 'name': name, 'description': operation_id, 'cores': 2, 'memory': 2048,
            'ostype': 'l26', 'bios': 'seabios', 'scsihw': 'virtio-scsi-pci', 'vga': 'std',
            'scsi0': f'{storage_id}:0,import-from={source_volume},format=qcow2',
            'ide2': f'{storage_id}:cloudinit', 'net0': f'virtio,bridge={bridge_id}',
            'boot': 'order=scsi0', 'agent': 'enabled=1', 'onboot': 0, 'ipconfig0': 'ip=dhcp'}


def selected_import(volume, scope, *, include_existing=False):
    if not isinstance(volume, str):
        return False
    match = re.fullmatch(r'([A-Za-z0-9_.-]+):import/gjallar-image-([1-9][0-9]{2,8})-([a-f0-9]{64})\.qcow2', volume)
    return bool(match and match[1] in scope['storages'] and int(match[2]) in (scope.get('image_vmids', []) + (scope['vmids'] if include_existing else [])))


def request_allowed(method, pieces, data, scope):
    if method != 'POST':
        return False
    if (len(pieces) == 5 and pieces[2] == 'qemu' and pieces[3].isdigit() and pieces[4] == 'template'
            and int(pieces[3]) in scope.get('image_vmids', [])):
        return data == {}
    if len(pieces) != 3 or pieces[2] != 'qemu' or not isinstance(data, dict):
        return False
    vmid, name, operation_id = data.get('vmid'), data.get('name'), data.get('description')
    if (type(vmid) is not int or vmid not in scope.get('image_vmids', [])
            or not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,62}', name)
            or not isinstance(operation_id, str) or not re.fullmatch(r'vm-image-build-[a-f0-9]{64}', operation_id)):
        return False
    scsi = data.get('scsi0', '')
    if not isinstance(scsi, str):
        return False
    match = re.fullmatch(r'([A-Za-z0-9_.-]+):0,import-from=([^,]+),format=qcow2', scsi)
    bridge = data.get('net0', '').removeprefix('virtio,bridge=') if isinstance(data.get('net0'), str) else ''
    if not match or match[1] not in scope['storages'] or bridge not in scope['bridges'] or not selected_import(match[2], scope):
        return False
    if match[2].split(':', 1)[1] != 'import/' + upload_filename(vmid, operation_id):
        return False
    expected = vm_create_payload(vmid=vmid, name=name, storage_id=match[1], bridge_id=bridge,
                                 source_volume=match[2], operation_id=operation_id)
    return data == expected and all(type(data[key]) is type(value) for key, value in expected.items())
