from app.backups.domain import BackupError, archives, source, storage_available, target
from app.operations.core.domain import operation_digest
from app.operations.core.evidence import compact_proxmox_task
from app.operations.vm_backup.domain import task_reference
from app.proxmox.client import ProxmoxMutationError


class BackupClient:
    def __init__(self, client): self.client = client

    def listing(self, *, node_id, vmid, storage):
        target(node_id, vmid, storage)
        try:
            if ('VM.Backup' not in self.client.get_vm_permissions(vmid=vmid)
                    or not {'Datastore.Audit', 'Datastore.AllocateSpace'} <= self.client.get_storage_permissions(storage=storage)):
                raise BackupError('VM_BACKUP_PERMISSION_DENIED', '원본 VM.Backup·선택 storage Audit/AllocateSpace 권한을 확인하세요.', 403)
            store = storage_available(self.client.get_node_storages(node=node_id), storage)
            rows = archives(self.client.list_vm_backups(node=node_id, vmid=vmid, storage=storage), storage=storage, vmid=vmid)
            return {'target': {'node_id': node_id, 'vmid': vmid, 'storage_id': storage}, 'archives': rows,
                    'available_bytes': store.get('avail'), 'read_only': True,
                    'limitation': 'PVE 목록의 파일 시점·크기입니다. 복원 가능성은 별도 복원·부팅 검사로 확인하세요.'}
        except ProxmoxMutationError:
            raise BackupError('VM_BACKUP_OBSERVATION_UNAVAILABLE', '백업 목록·storage·권한을 확인하지 못했습니다.', 503) from None

    def read(self, *, node_id, vmid, storage, require_space=True):
        listing = self.listing(node_id=node_id, vmid=vmid, storage=storage)
        try:
            if 'VM.Audit' not in self.client.get_vm_permissions(vmid=vmid) or not self.client.has_node_task_audit(node=node_id):
                raise BackupError('VM_BACKUP_PERMISSION_DENIED', '원본 VM.Audit·노드 Sys.Audit 권한을 확인하세요.', 403)
            before = source(self.client.get_vm_current_config(node=node_id, vmid=vmid), self.client.get_vm_status(node=node_id, vmid=vmid),
                            self.client.get_vm_pending(node=node_id, vmid=vmid), self.client.get_vm_snapshots(node=node_id, vmid=vmid), vmid=vmid)
            stores = self.client.get_node_storages(node=node_id)
            for volume in before['volumes']: storage_available(stores, volume['storage_id'], content='images')
            defaults = self.client.get_backup_defaults(node=node_id, storage=storage)
            if defaults.get('script'):
                raise BackupError('VM_BACKUP_HOOK_UNSUPPORTED', '호스트 기본 백업 hook이 있으면 이 첫 지원 흐름에서 실행하지 않습니다.')
            available = listing['available_bytes']
            if require_space and (type(available) is not int or available < before['required_free_bytes']):
                raise BackupError('VM_BACKUP_SPACE_UNCONFIRMED', '가상 disk 용량과 여유 공간을 확보한 NFS storage가 필요합니다.')
            manifest = {**before, 'storage_id': storage, 'archives': listing['archives'], 'defaults_digest': operation_digest(defaults)}
            return {**manifest, 'review_digest': operation_digest(manifest), 'available_bytes': available}
        except ProxmoxMutationError:
            raise BackupError('VM_BACKUP_OBSERVATION_UNAVAILABLE', '원본 VM·백업 기본값을 확인하지 못했습니다.', 503) from None

    def apply(self, *, node_id, vmid, request, operation_id):
        try:
            response = self.client.create_vm_backup(node=node_id, vmid=vmid, storage=request.storage_id, operation_id=operation_id)
        except ProxmoxMutationError:
            raise BackupError('VM_BACKUP_DISPATCH_UNKNOWN', '백업 요청 결과가 불명확합니다. 자동 재백업하지 마세요.', 503) from None
        return task_reference(response, node_id=node_id, vmid=vmid)

    def task(self, *, node_id, upid, heartbeat=None):
        try:
            value = (self.client.wait_for_task(node=node_id, upid=upid, heartbeat=heartbeat) if heartbeat
                     else self.client.get_task_status(node=node_id, upid=upid))
        except ProxmoxMutationError:
            raise BackupError('VM_BACKUP_TASK_UNAVAILABLE', '백업 task 상태를 읽지 못했습니다.', 503) from None
        return compact_proxmox_task(value, node=node_id, upid=upid)
