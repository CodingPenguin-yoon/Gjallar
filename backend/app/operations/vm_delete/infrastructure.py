"""Deletion adapter: constrained request and independent post-ACL absence proof."""
from app.operations.core.evidence import compact_proxmox_task
from app.operations.vm_delete.domain import (
    DeleteError, deletion_identity, deletion_result, manifest, validate_storage, verified_task_reference, volume_rows,
)
from app.proxmox.client import ProxmoxMutationError


class DeleteClient:
    def __init__(self, client):
        self.client = client

    def storage_rows(self, *, node_id, vmid, storage_ids):
        storages = self.client.get_node_storages(node=node_id)
        rows = []
        for storage in sorted(storage_ids):
            validate_storage(storages, storage)
            if not {'Datastore.Audit', 'Datastore.Allocate'} <= self.client.get_storage_permissions(storage=storage):
                raise DeleteError('VM_DELETE_PERMISSION_DENIED', 'VM ACL 삭제 뒤에도 volume 부재를 확인할 storage Audit·Allocate 권한이 필요합니다. 선택 storage의 더 넓은 권한을 검토하세요.', 403)
            rows.extend(volume_rows(self.client.list_vm_storage_images(node=node_id, storage=storage, vmid=vmid), storage_id=storage, vmid=vmid))
        return sorted(rows, key=lambda row: row['volume_id'])

    def read(self, *, node_id, vmid):
        try:
            if not {'VM.Audit', 'VM.Allocate'} <= self.client.get_vm_permissions(vmid=vmid):
                raise DeleteError('VM_DELETE_PERMISSION_DENIED', '선택한 VM의 Audit·Allocate 권한을 확인하세요.', 403)
            identity = deletion_identity(self.client.get_vm_current_config(node=node_id, vmid=vmid),
                self.client.get_vm_status(node=node_id, vmid=vmid), self.client.get_vm_pending(node=node_id, vmid=vmid),
                self.client.get_vm_snapshots(node=node_id, vmid=vmid), vmid=vmid)
            rows = self.storage_rows(node_id=node_id, vmid=vmid, storage_ids={row['storage_id'] for row in identity['deleted_volumes']})
            info = {row['volume_id']: self.client.get_volume_info(node=node_id, storage=row['storage_id'], volume=row['volume_id'])
                    for row in identity['deleted_volumes']}
            return manifest(identity, rows, info)
        except ProxmoxMutationError:
            raise DeleteError('VM_DELETE_OBSERVATION_UNAVAILABLE', '삭제 대상·실제 disk·snapshot·권한을 확인하지 못했습니다.', 503) from None

    def apply(self, *, node_id, vmid, request):
        try:
            response = self.client.delete_vm_reviewed(node=node_id, vmid=vmid)
        except ProxmoxMutationError:
            raise DeleteError('VM_DELETE_DISPATCH_UNKNOWN', '삭제 요청 결과가 불명확합니다. 자동 재삭제하지 마세요.', 503) from None
        return verified_task_reference(response, node_id=node_id, vmid=vmid)

    def observe_deletion(self, *, node_id, vmid, before):
        try:
            rows = self.storage_rows(node_id=node_id, vmid=vmid, storage_ids={row['storage_id'] for row in before['deleted_volumes']})
            free = self.client.assert_vmid_unused(vmid=vmid)
            return deletion_result(before, rows, vmid_unused=free)
        except ProxmoxMutationError:
            raise DeleteError('VM_DELETE_ABSENCE_UNCONFIRMED', 'VMID 미사용 또는 실제 volume 부재를 확인하지 못했습니다. 조회 실패를 삭제 성공으로 처리하지 않습니다.', 503) from None

    def task(self, *, node_id, upid, heartbeat=None):
        try:
            value = (self.client.wait_for_task(node=node_id, upid=upid, heartbeat=heartbeat) if heartbeat
                     else self.client.get_task_status(node=node_id, upid=upid))
        except ProxmoxMutationError:
            raise DeleteError('VM_DELETE_TASK_OBSERVATION_UNAVAILABLE', '삭제 작업 결과를 확인하지 못했습니다.', 503) from None
        return compact_proxmox_task(value, node=node_id, upid=upid)
