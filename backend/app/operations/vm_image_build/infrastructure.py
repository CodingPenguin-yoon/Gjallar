"""Managed-only PVE image upload/import/template adapter, with bounded evidence."""
import re

from app.cloud_images.catalog import ImageError, image_by_id
from app.cloud_images.contracts import VM_PRIVILEGES, upload_filename, vm_create_payload
from app.operations.core.evidence import compact_proxmox_task
from app.operations.vm_template.facade import TemplateError, observe_prepared_template
from app.proxmox.client import ProxmoxMutationError
from app.setup_integration.contracts import SetupError
from app.setup_integration.runtime import ManagedRequests, managed_mutation_client, selected_credential


class ImageBuildClient:
    def __init__(self):
        try:
            selected = selected_credential()
            if not selected or 'image_build' not in selected['configuration']['features']:
                raise ImageError('IMAGE_BUILD_CONNECTION_REQUIRED', 'image_build를 선택한 관리형 연결을 등록·검증·전환하세요.', 403)
            self.revision = selected['revision_id']
            self.scope = selected['configuration']['scope']
            self.requests = ManagedRequests(selected)
            self.client = managed_mutation_client(selected)
        except SetupError:
            raise ImageError('IMAGE_BUILD_CONNECTION_UNAVAILABLE', '관리형 Proxmox 연결을 확인하세요.', 503) from None

    def check_selection(self, node_id, vmid):
        try:
            selected = selected_credential()
            if not selected or selected['revision_id'] != self.revision:
                raise ImageError('IMAGE_BUILD_CONNECTION_CHANGED', '연결이 변경됐습니다. 서버 재시작 후 작업 이력을 확인하세요.', 503)
            if node_id not in self.scope['nodes'] or vmid not in self.scope.get('image_vmids', []):
                raise ImageError('IMAGE_BUILD_SCOPE_DENIED', '선택한 제작 VMID·노드 범위를 확인하세요.', 403)
        except SetupError:
            raise ImageError('IMAGE_BUILD_CONNECTION_UNAVAILABLE', '관리형 연결의 선택 상태를 확인할 수 없습니다.', 503) from None

    def preflight(self, *, node_id, vmid, request):
        self.check_selection(node_id, vmid)
        image = image_by_id(request.image_id)
        if (request.storage_id not in self.scope['storages'] or request.staging_storage_id not in self.scope['storages']
                or request.bridge_id not in self.scope['bridges']):
            raise ImageError('IMAGE_BUILD_SCOPE_DENIED', '선택한 storage·bridge 범위를 확인하세요.', 403)
        try:
            self.client.assert_vmid_unused(vmid=vmid)
            if not set(VM_PRIVILEGES) <= self.client.get_vm_permissions(vmid=vmid):
                raise ImageError('IMAGE_BUILD_PERMISSION_DENIED', '새 VMID의 제작·관찰 권한이 부족합니다.', 403)
            storages = self.client.get_node_storages(node=node_id)
            for storage, types, content, needed, permissions in (
                (request.staging_storage_id, {'dir', 'nfs'}, 'import', 2 * image.download_bytes,
                 {'Datastore.Audit', 'Datastore.AllocateTemplate', 'Datastore.AllocateSpace'}),
                (request.storage_id, {'nfs'}, 'images', image.virtual_size_bytes + 4 * 1024 ** 2,
                 {'Datastore.Audit', 'Datastore.AllocateSpace'}),
            ):
                row = next((row for row in storages if row.get('storage') == storage), None)
                if request.storage_id == request.staging_storage_id:
                    needed = 2 * image.download_bytes + image.virtual_size_bytes + 4 * 1024 ** 2
                if (not row or row.get('type') not in types or row.get('active') not in (1, '1') or row.get('enabled') not in (1, '1')
                        or content not in str(row.get('content', '')).split(',') or type(row.get('avail')) is not int or row['avail'] < needed):
                    raise ImageError('IMAGE_BUILD_STORAGE_UNAVAILABLE', '활성 staging import/NFS images storage와 여유 공간을 확인하세요.', 503)
                if not permissions <= self.client.get_storage_permissions(storage=storage):
                    raise ImageError('IMAGE_BUILD_PERMISSION_DENIED', '이미지 업로드·공간 할당·storage 조회 권한을 확인하세요.', 403)
            network = self.client.get_node_network_snapshot(node=node_id)
            bridge = next((row for row in network['interfaces'] if row.get('iface') == request.bridge_id), None)
            if network['pending_changes'] or not bridge or bridge.get('type') != 'bridge' or bridge.get('active') not in (1, '1'):
                raise ImageError('IMAGE_BUILD_BRIDGE_UNAVAILABLE', '미적용 변경이 없는 활성 Linux bridge를 선택하세요.')
            if 'SDN.Use' not in self.client.get_bridge_permissions(bridge=request.bridge_id):
                raise ImageError('IMAGE_BUILD_PERMISSION_DENIED', '선택 bridge 사용 권한을 확인하세요.', 403)
        except ProxmoxMutationError:
            raise ImageError('IMAGE_BUILD_PREFLIGHT_UNAVAILABLE', 'VMID 미사용·권한·storage·bridge 조건을 확인할 수 없습니다.', 503) from None
        return {'connection_revision': self.revision, 'image': image.public(), 'name': request.name,
                'storage_id': request.storage_id, 'staging_storage_id': request.staging_storage_id, 'bridge_id': request.bridge_id}

    def assert_upload_absent(self, *, node_id, vmid, storage, filename):
        self.check_selection(node_id, vmid)
        try:
            rows = self.requests.request('GET', f'/nodes/{node_id}/storage/{storage}/content', data={'content': 'import'})
            if any(row['volid'] == f'{storage}:import/{filename}' for row in rows):
                raise ImageError('IMAGE_BUILD_STAGING_EXISTS', '이 작업의 staging 파일이 이미 있습니다. 덮어쓰거나 재업로드하지 마세요.')
        except SetupError:
            raise ImageError('IMAGE_BUILD_STAGING_UNAVAILABLE', '업로드 전 staging 파일 부재를 확인하지 못했습니다.', 503) from None

    def upload(self, *, node_id, vmid, request, operation_id, file, heartbeat):
        self.check_selection(node_id, vmid)
        try:
            value = self.requests.upload_image(node=node_id, vmid=vmid, storage=request.staging_storage_id,
                operation_id=operation_id, image_id=request.image_id, file=file, heartbeat=heartbeat)
        except SetupError:
            raise ImageError('IMAGE_BUILD_UPLOAD_UNKNOWN', '이미지 업로드 결과가 불명확합니다. 자동 재업로드하지 마세요.', 503) from None
        return task_reference(value, node_id=node_id, vmid='', kind='imgcopy')

    def observe_staging(self, *, node_id, vmid, request, operation_id):
        self.check_selection(node_id, vmid)
        volume = request.staging_storage_id + ':import/' + upload_filename(vmid, operation_id)
        try:
            info = self.client.get_volume_info(node=node_id, storage=request.staging_storage_id, volume=volume)
            if type(info.get('size')) is not int or info['size'] != image_by_id(request.image_id).virtual_size_bytes or info.get('format') != 'qcow2':
                raise ImageError('IMAGE_BUILD_STAGING_UNCONFIRMED', '검증된 staging 이미지의 실제 형식·가상 크기를 확인할 수 없습니다.', 503)
            return {'volume_id': volume, 'format': 'qcow2', 'virtual_size_bytes': info['size']}
        except ProxmoxMutationError:
            raise ImageError('IMAGE_BUILD_STAGING_UNAVAILABLE', 'staging 이미지 관찰을 완료하지 못했습니다.', 503) from None

    def create(self, *, node_id, vmid, request, operation_id):
        self.check_selection(node_id, vmid)
        payload = vm_create_payload(vmid=vmid, name=request.name, storage_id=request.storage_id, bridge_id=request.bridge_id,
            source_volume=request.staging_storage_id + ':import/' + upload_filename(vmid, operation_id), operation_id=operation_id)
        try:
            value = self.client.create_vm_from_image(node=node_id, config=payload)
        except ProxmoxMutationError:
            raise ImageError('IMAGE_BUILD_CREATE_UNKNOWN', '이미지 import 생성 결과가 불명확합니다. 자동 재생성하지 마세요.', 503) from None
        return task_reference(value, node_id=node_id, vmid=vmid, kind='qmcreate')

    def observe_vm(self, *, node_id, vmid, request, operation_id, converted=False):
        self.check_selection(node_id, vmid)
        try:
            observed = observe_prepared_template(self.client, node_id=node_id, vmid=vmid, converted=converted)
            config = self.client.get_vm_current_config(node=node_id, vmid=vmid)
            expected = {'name': request.name, 'description': operation_id, 'cores': '2', 'memory': '2048', 'bios': 'seabios',
                        'scsihw': 'virtio-scsi-pci', 'vga': 'std', 'boot': 'order=scsi0', 'onboot': '0', 'ipconfig0': 'ip=dhcp', 'ostype': 'l26'}
            # Re-read must describe the same config whose fingerprint was observed.
            if config.get('digest') != observed['digest'] or any(str(config.get(key)) != value for key, value in expected.items()):
                raise ImageError('IMAGE_BUILD_VM_UNCONFIRMED', '제작한 VM의 소유 식별자·고정 설정을 확인할 수 없습니다.')
            if str(config.get('agent')) not in {'1', 'enabled=1'}:
                raise ImageError('IMAGE_BUILD_VM_UNCONFIRMED', '제작한 VM의 guest agent 설정을 확인할 수 없습니다.')
            options = str(config.get('net0', '')).split(',')
            if (len(options) != 2 or not re.fullmatch(r'virtio=(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', options[0])
                    or options[1] != f'bridge={request.bridge_id}'):
                raise ImageError('IMAGE_BUILD_VM_UNCONFIRMED', '제작한 VM의 bridge·새 MAC 설정을 확인할 수 없습니다.')
            if (any(row['storage_id'] != request.storage_id for row in observed['volumes'])
                    or observed['volumes'][0]['size_bytes'] != image_by_id(request.image_id).virtual_size_bytes):
                raise ImageError('IMAGE_BUILD_VM_UNCONFIRMED', '제작한 VM의 대상 storage·가상 디스크 크기가 다릅니다.')
            return {**observed, 'guest_readiness': 'official_image_not_runtime_verified'}
        except (TemplateError, ProxmoxMutationError):
            raise ImageError('IMAGE_BUILD_VM_UNCONFIRMED', '정지된 제작 VM·template·volume 관찰을 완료하지 못했습니다.', 503) from None

    def convert(self, *, node_id, vmid):
        self.check_selection(node_id, vmid)
        try:
            value = self.client.convert_vm_to_template(node=node_id, vmid=vmid)
        except ProxmoxMutationError:
            raise ImageError('IMAGE_BUILD_CONVERSION_UNKNOWN', '템플릿 전환 결과가 불명확합니다. 자동 재전환하지 마세요.', 503) from None
        return task_reference(value, node_id=node_id, vmid=vmid, kind='qmtemplate')

    def task(self, *, node_id, upid, heartbeat=None):
        try:
            value = (self.client.wait_for_task(node=node_id, upid=upid, heartbeat=heartbeat) if heartbeat
                     else self.client.get_task_status(node=node_id, upid=upid))
        except ProxmoxMutationError:
            raise ImageError('IMAGE_BUILD_TASK_UNAVAILABLE', '제작 단계의 PVE task 상태를 확인할 수 없습니다.', 503) from None
        return compact_proxmox_task(value, node=node_id, upid=upid)


def task_reference(value, *, node_id, vmid, kind):
    if not isinstance(value, str) or len(value) > 512 or not re.fullmatch(
            rf'UPID:{re.escape(node_id)}:[0-9A-Fa-f]+:[0-9A-Fa-f]+:[0-9A-Fa-f]+:{kind}:{vmid}:[A-Za-z0-9_.@!+-]+:', value):
        raise ImageError('IMAGE_BUILD_TASK_UNKNOWN', '정확한 단계·노드·VMID의 task 식별자를 확인할 수 없습니다.', 503)
    return value
