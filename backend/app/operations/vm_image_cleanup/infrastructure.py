"""Exact build ownership, backing-reference checks, and independent absence proof."""
from urllib.parse import quote

from app.cloud_images.catalog import ImageError
from app.cloud_images.contracts import upload_filename
from app.operations.core.evidence import compact_proxmox_task
from app.operations.vm_delete.facade import DeleteError, observe_owned_storage_volumes, observe_reviewed_volume_removal
from app.operations.vm_template.facade import TemplateError, observe_cleanup_template
from app.operations.vm_image_cleanup.domain import task_reference
from app.proxmox.client import ProxmoxMutationError
from app.setup_integration.contracts import SetupError
from app.setup_integration.runtime import ManagedRequests, managed_mutation_client, selected_credential


class ImageCleanupClient:
    def __init__(self):
        try:
            selected = selected_credential()
            if not selected or 'image_cleanup' not in selected['configuration']['features']:
                raise ImageError('IMAGE_CLEANUP_CONNECTION_REQUIRED', '기존 VMID와 명시적 정리 storage로 image_cleanup 연결을 등록·검증·전환하세요.', 403)
            self.revision, self.scope = selected['revision_id'], selected['configuration']['scope']
            self.requests, self.client = ManagedRequests(selected), managed_mutation_client(selected)
        except SetupError:
            raise ImageError('IMAGE_CLEANUP_CONNECTION_UNAVAILABLE', '관리형 연결을 확인하세요.', 503) from None

    def check_selection(self, *, node_id, vmid, storage):
        try:
            selected = selected_credential()
            if not selected or selected['revision_id'] != self.revision:
                raise ImageError('IMAGE_CLEANUP_CONNECTION_CHANGED', '선택한 연결이 변경됐습니다. 원래 Operation을 확인하세요.', 503)
            if node_id not in self.scope['nodes'] or vmid not in self.scope['vmids'] or storage not in self.scope.get('image_cleanup_storages', []):
                raise ImageError('IMAGE_CLEANUP_SCOPE_DENIED', '명시적으로 선택한 정리 VMID·storage 범위가 아닙니다.', 403)
            if not {'Datastore.Audit', 'Datastore.Allocate'} <= self.client.get_storage_permissions(storage=storage):
                raise ImageError('IMAGE_CLEANUP_PERMISSION_DENIED', '권한 때문에 volume이 숨겨지지 않도록 storage Audit·Allocate가 필요합니다.', 403)
        except (SetupError, ProxmoxMutationError):
            raise ImageError('IMAGE_CLEANUP_CONNECTION_UNAVAILABLE', '관리형 연결·정리 권한을 확인할 수 없습니다.', 503) from None

    def import_rows(self, *, node_id, vmid, storage):
        self.check_selection(node_id=node_id, vmid=vmid, storage=storage)
        rows = self.requests.request('GET', f'/nodes/{node_id}/storage/{storage}/content', data={'content': 'import'})
        if (not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get('volid'), str)
                or type(row.get('size')) is not int or row['size'] <= 0 or not isinstance(row.get('format'), str) for row in rows)):
            raise ImageError('IMAGE_CLEANUP_SOURCE_UNCONFIRMED', '업로드 원본 목록·크기·형식을 확인할 수 없습니다.', 503)
        return rows

    def read(self, *, node_id, vmid, parent, resource):
        source_request = parent.details['requested']
        storage = source_request['storage_id' if resource == 'template' else 'staging_storage_id']
        self.check_selection(node_id=node_id, vmid=vmid, storage=storage)
        try:
            if resource == 'source':
                volume = storage + ':import/' + upload_filename(vmid, parent.operation_id)
                rows = self.import_rows(node_id=node_id, vmid=vmid, storage=storage)
                matches = [row for row in rows if row['volid'] == volume]
                info = self.client.get_volume_info(node=node_id, storage=storage, volume=volume)
                expected_size = parent.details['source_integrity']['virtual_size_bytes']
                if (len(matches) != 1 or matches[0]['format'] != 'qcow2' or info.get('format') != 'qcow2'
                        or matches[0]['size'] != expected_size or info.get('size') != expected_size):
                    raise ImageError('IMAGE_CLEANUP_SOURCE_CHANGED', '제작한 업로드 원본과 현재 파일이 일치하지 않습니다.')
                return {'storage_id': storage, 'deleted_volumes': [{'volume_id': volume, 'format': 'qcow2', 'size_bytes': expected_size}],
                        'preserved_volumes': [], 'source_sha256': parent.details['source_integrity']['sha256']}
            config = self.client.get_vm_current_config(node=node_id, vmid=vmid)
            if str(config.get('protection', 0)) != '0':
                raise ImageError('IMAGE_CLEANUP_PROTECTED', '삭제 보호를 자동 해제하지 않습니다.')
            observed = observe_cleanup_template(self.client, node_id=node_id, vmid=vmid)
            original = parent.details['observed_after']
            if (config.get('digest') != observed['digest'] or config.get('description') != parent.operation_id
                    or observed['name'] != parent.details['target']['name']
                    or observed['config_fingerprint'] != original.get('config_fingerprint')
                    or observed['volumes'] != original.get('volumes')):
                raise ImageError('IMAGE_CLEANUP_TEMPLATE_CHANGED', '현재 template이 제작 완료 시 소유 자원·설정과 다릅니다. 자동 삭제하지 않습니다.')
            root = next(row for row in observed['volumes'] if row['slot'] == 'scsi0')
            dependents = self.requests.image_base_dependents(node=node_id, vmid=vmid, storage=storage, volume=root['volume_id'])
            if dependents['dependent_count']:
                raise ImageError('IMAGE_CLEANUP_TEMPLATE_IN_USE', '이 base disk를 참조하는 linked clone이 있습니다. 템플릿을 삭제할 수 없습니다.')
            rows = observe_owned_storage_volumes(self.client, node_id=node_id, vmid=vmid, storage_ids={storage})
            by_id = {row['volume_id']: row for row in rows}
            deleted = observed['volumes']
            if any(row['volume_id'] not in by_id or by_id[row['volume_id']]['size_bytes'] != row['size_bytes'] for row in deleted):
                raise ImageError('IMAGE_CLEANUP_TEMPLATE_CHANGED', '삭제할 실제 소유 volume 목록을 확인할 수 없습니다.')
            ids = {row['volume_id'] for row in deleted}
            return {'storage_id': storage, 'digest': observed['digest'], 'config_fingerprint': observed['config_fingerprint'],
                    'deleted_volumes': deleted, 'preserved_volumes': [row for row in rows if row['volume_id'] not in ids],
                    'dependent_count': 0}
        except (SetupError, ProxmoxMutationError, TemplateError, DeleteError):
            raise ImageError('IMAGE_CLEANUP_OBSERVATION_UNAVAILABLE', '정리 소유 자원·권한·참조 상태를 확인하지 못했습니다.', 503) from None

    def apply(self, *, node_id, vmid, before):
        self.check_selection(node_id=node_id, vmid=vmid, storage=before['storage_id'])
        try:
            if before['resource'] == 'template':
                value = self.client.delete_vm_reviewed(node=node_id, vmid=vmid)
            else:
                volume = quote(before['deleted_volumes'][0]['volume_id'], safe='')
                value = self.requests.request('DELETE', f"/nodes/{node_id}/storage/{before['storage_id']}/content/{volume}", data={})
        except (SetupError, ProxmoxMutationError):
            raise ImageError('IMAGE_CLEANUP_DISPATCH_UNKNOWN', '삭제 요청 결과가 불명확합니다. 자동 재삭제하지 마세요.', 503) from None
        return task_reference(value, node_id=node_id, vmid=vmid, resource=before['resource'], storage=before['storage_id'])

    def observe_deletion(self, *, node_id, vmid, before):
        self.check_selection(node_id=node_id, vmid=vmid, storage=before['storage_id'])
        try:
            if before['resource'] == 'template':
                result = observe_reviewed_volume_removal(self.client, node_id=node_id, vmid=vmid, before=before)
                return {**result, 'removed': result['vmid_unused'] and not result['remaining_volumes']}
            volume = before['deleted_volumes'][0]['volume_id']
            rows = self.import_rows(node_id=node_id, vmid=vmid, storage=before['storage_id'])
            present = any(row['volid'] == volume for row in rows)
            return {'removed': not present, 'remaining_volumes': [volume] if present else [], 'preservation_unconfirmed': []}
        except (SetupError, ProxmoxMutationError, DeleteError):
            raise ImageError('IMAGE_CLEANUP_ABSENCE_UNCONFIRMED', '실제 삭제 자원 부재를 확인할 수 없습니다. 조회 실패를 성공으로 처리하지 않습니다.', 503) from None

    def task(self, *, node_id, upid, heartbeat=None):
        try:
            value = (self.client.wait_for_task(node=node_id, upid=upid, heartbeat=heartbeat) if heartbeat
                     else self.client.get_task_status(node=node_id, upid=upid))
        except ProxmoxMutationError:
            raise ImageError('IMAGE_CLEANUP_TASK_UNAVAILABLE', '정리 task 상태를 확인할 수 없습니다.', 503) from None
        return compact_proxmox_task(value, node=node_id, upid=upid)
