"""PVE adapter exposing bounded disk and task evidence."""
from app.operations.core.evidence import compact_proxmox_task
from app.operations.vm_disk.domain import DiskError, disk_identity, observed_disk, verified_task_reference
from app.proxmox.client import ProxmoxMutationError


class DiskClient:
    def __init__(self, client):
        self.client = client

    def read(self, *, node_id, vmid):
        try:
            identity = disk_identity(self.client.get_vm_current_config(node=node_id, vmid=vmid),
                self.client.get_vm_status(node=node_id, vmid=vmid),
                self.client.get_vm_pending(node=node_id, vmid=vmid), vmid=vmid)
            storages = self.client.get_node_storages(node=node_id)
            volume = self.client.get_volume_info(node=node_id, storage=identity["storage_id"], volume=identity["volume_id"])
        except ProxmoxMutationError:
            raise DiskError("VM_DISK_OBSERVATION_UNAVAILABLE", "VM·storage·실제 디스크 용량을 확인하지 못했습니다.", 503) from None
        return observed_disk(identity, storages, volume)

    def check_permissions(self, *, vmid, storage):
        try:
            vm_permissions = self.client.get_vm_permissions(vmid=vmid)
            storage_permissions = self.client.get_storage_permissions(storage=storage)
        except ProxmoxMutationError:
            raise DiskError("VM_DISK_PERMISSION_UNAVAILABLE", "VM·storage 권한을 확인하지 못했습니다.", 503) from None
        if not {"VM.Audit", "VM.Config.Disk"} <= vm_permissions or not {"Datastore.Audit", "Datastore.AllocateSpace"} <= storage_permissions:
            raise DiskError("VM_DISK_PERMISSION_DENIED", "선택 VM의 디스크 변경과 storage 공간 할당 권한을 갱신하세요.", 403)

    def apply(self, *, node_id, vmid, request):
        try:
            response = self.client.resize_vm_disk_reviewed(node=node_id, vmid=vmid,
                size_gib=request.size_gib, digest=request.expected_digest)
        except ProxmoxMutationError:
            raise DiskError("VM_DISK_DISPATCH_UNKNOWN", "확장 요청 결과가 불명확합니다. 자동 재실행하지 마세요.", 503) from None
        return verified_task_reference(response, node_id=node_id, vmid=vmid)

    def task(self, *, node_id, upid, heartbeat=None):
        try:
            value = (self.client.wait_for_task(node=node_id, upid=upid, heartbeat=heartbeat) if heartbeat
                     else self.client.get_task_status(node=node_id, upid=upid))
        except ProxmoxMutationError:
            raise DiskError("VM_DISK_TASK_OBSERVATION_UNAVAILABLE", "확장 작업 결과를 확인하지 못했습니다.", 503) from None
        return compact_proxmox_task(value, node=node_id, upid=upid)
