"""Bounded PVE clone reads, permission checks and one full-clone request."""
from app.operations.core.evidence import compact_proxmox_task
from app.operations.vm_clone.domain import CloneError, clone_identity, confirm_volume, nfs_storage, verified_task_reference
from app.proxmox.client import ProxmoxMutationError


class CloneClient:
    def __init__(self, client):
        self.client = client

    def read(self, *, node_id, vmid):
        try:
            identity = clone_identity(self.client.get_vm_current_config(node=node_id, vmid=vmid),
                self.client.get_vm_status(node=node_id, vmid=vmid), self.client.get_vm_pending(node=node_id, vmid=vmid), vmid=vmid)
            return confirm_volume(identity, self.client.get_node_storages(node=node_id),
                self.client.get_volume_info(node=node_id, storage=identity['storage_id'], volume=identity['volume_id']))
        except ProxmoxMutationError:
            raise CloneError('VM_CLONE_OBSERVATION_UNAVAILABLE', 'VM·storage·실제 volume을 확인하지 못했습니다.', 503) from None

    def review(self, *, node_id, vmid, new_vmid, storage_id):
        source = self.read(node_id=node_id, vmid=vmid)
        try:
            original = self.client.get_vm_permissions(vmid=vmid)
            destination = self.client.get_vm_permissions(vmid=new_vmid)
            storage = self.client.get_storage_permissions(storage=storage_id)
            bridge = self.client.get_bridge_permissions(bridge=source['nic']['bridge'])
            if (not {'VM.Audit', 'VM.Clone', 'VM.Config.Disk'} <= original or not {'VM.Audit', 'VM.Allocate', 'VM.Config.Disk'} <= destination
                    or not {'Datastore.Audit', 'Datastore.AllocateSpace'} <= storage or 'SDN.Use' not in bridge):
                raise CloneError('VM_CLONE_PERMISSION_DENIED', '원본 Clone·새 VMID Allocate/Audit·양쪽 Config.Disk·storage 할당·bridge 사용 권한을 갱신하세요.', 403)
            target_storage = nfs_storage(self.client.get_node_storages(node=node_id), storage_id)
            resources = self.client.list_vm_resources()
            if any(row.get('vmid') == new_vmid for row in resources):
                raise CloneError('VM_CLONE_TARGET_EXISTS', '새 VMID가 이미 사용 중입니다. 기존 VM을 덮어쓰지 않습니다.')
        except ProxmoxMutationError:
            raise CloneError('VM_CLONE_OBSERVATION_UNAVAILABLE', '복제 범위·권한·새 VMID 사용 여부를 확인하지 못했습니다.', 503) from None
        return {'source': source, 'destination': {'node_id': node_id, 'vmid': new_vmid, **target_storage}}

    def apply(self, *, node_id, vmid, request, marker):
        try:
            response = self.client.clone_vm_reviewed(node=node_id, vmid=vmid, new_vmid=request.new_vmid,
                name=request.name, storage=request.storage_id, disk_format=request.expected_volume.rsplit('.', 1)[-1],
                description=marker)
        except ProxmoxMutationError:
            raise CloneError('VM_CLONE_DISPATCH_UNKNOWN', '복제 요청 결과가 불명확합니다. 자동 재실행하지 마세요.', 503) from None
        return verified_task_reference(response, node_id=node_id, vmid=vmid)

    def task(self, *, node_id, upid, heartbeat=None):
        try:
            value = (self.client.wait_for_task(node=node_id, upid=upid, heartbeat=heartbeat) if heartbeat
                     else self.client.get_task_status(node=node_id, upid=upid))
        except ProxmoxMutationError:
            raise CloneError('VM_CLONE_TASK_OBSERVATION_UNAVAILABLE', '복제 작업 결과를 확인하지 못했습니다.', 503) from None
        return compact_proxmox_task(value, node=node_id, upid=upid)
