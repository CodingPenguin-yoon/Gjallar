"""Read, convert once, then observe actual template/base-volume state."""
from app.operations.core.domain import operation_digest
from app.operations.core.evidence import compact_proxmox_task
from app.operations.vm_template.domain import TemplateError, inspect_vm, verified_task_reference
from app.proxmox.client import ProxmoxMutationError


class TemplateClient:
    def __init__(self, client):
        self.client = client

    def read(self, *, node_id, vmid, converted=False, storage_authority=False):
        try:
            required_vm = {'VM.Audit', 'VM.Allocate'} | (set() if storage_authority else {'VM.Config.Disk'})
            if not required_vm <= self.client.get_vm_permissions(vmid=vmid):
                raise TemplateError('VM_TEMPLATE_PERMISSION_DENIED', '선택 VM의 Audit·Allocate·volume 조회용 Config.Disk 권한을 확인하세요.', 403)
            before = inspect_vm(self.client.get_vm_current_config(node=node_id, vmid=vmid),
                self.client.get_vm_status(node=node_id, vmid=vmid), self.client.get_vm_pending(node=node_id, vmid=vmid),
                self.client.get_vm_snapshots(node=node_id, vmid=vmid), vmid=vmid, converted=converted)
            storages = self.client.get_node_storages(node=node_id)
            for volume in before['volumes']:
                storage = volume['storage_id']
                row = next((row for row in storages if row.get('storage') == storage), None)
                if (not row or row.get('type') != 'nfs' or row.get('active') not in (1, '1') or row.get('enabled') not in (1, '1')
                        or 'images' not in str(row.get('content', '')).split(',')):
                    raise TemplateError('VM_TEMPLATE_STORAGE_UNAVAILABLE', '활성 NFS images storage만 지원합니다.', 503)
                required_storage = {'Datastore.Audit'} | ({'Datastore.Allocate'} if storage_authority else set())
                if not required_storage <= self.client.get_storage_permissions(storage=storage):
                    raise TemplateError('VM_TEMPLATE_PERMISSION_DENIED', 'volume 확인을 위한 storage Audit 권한을 확인하세요.', 403)
                actual = self.client.get_volume_info(node=node_id, storage=storage, volume=volume['volume_id'])
                if type(actual.get('size')) is not int or actual['size'] <= 0 or actual.get('format') != volume['format']:
                    raise TemplateError('VM_TEMPLATE_VOLUME_UNCONFIRMED', '실제 volume 용량·형식을 확인할 수 없습니다.', 503)
                volume['size_bytes'] = actual['size']
            return {**before, 'resources_digest': operation_digest({'volumes': before['volumes'], 'config': before['config_fingerprint']})}
        except ProxmoxMutationError:
            raise TemplateError('VM_TEMPLATE_OBSERVATION_UNAVAILABLE', 'VM·volume·권한 관찰을 완료하지 못했습니다.', 503) from None

    def apply(self, *, node_id, vmid, request):
        try:
            response = self.client.convert_vm_to_template(node=node_id, vmid=vmid)
        except ProxmoxMutationError:
            raise TemplateError('VM_TEMPLATE_DISPATCH_UNKNOWN', '전환 요청 결과가 불명확합니다. 자동 재실행하지 마세요.', 503) from None
        return verified_task_reference(response, node_id=node_id, vmid=vmid)

    def task(self, *, node_id, upid, heartbeat=None):
        try:
            value = (self.client.wait_for_task(node=node_id, upid=upid, heartbeat=heartbeat) if heartbeat
                     else self.client.get_task_status(node=node_id, upid=upid))
        except ProxmoxMutationError:
            raise TemplateError('VM_TEMPLATE_TASK_OBSERVATION_UNAVAILABLE', '전환 작업 결과를 확인하지 못했습니다.', 503) from None
        return compact_proxmox_task(value, node=node_id, upid=upid)
