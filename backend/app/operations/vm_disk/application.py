"""Disk review and actual-volume comparison on the shared PVE task flow."""
import re

from app.operations.vm_config.task_application import TaskChangeService
from app.operations.vm_disk.domain import GIB, DiskError, check_expected


class DiskService(TaskChangeService):
    operation_type = "vm_disk_resize"
    operation_prefix = "vm-disk-"
    event_prefix = "disk_"
    error_prefix = "VM_DISK_"
    error_type = DiskError
    check_expected = staticmethod(check_expected)

    def review(self, *, node_id, vmid):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", node_id) or not 100 <= vmid <= 999999999:
            raise DiskError("VM_DISK_INVALID_TARGET", "노드·VMID 형식을 확인하세요.", 422)
        before = self.client.read(node_id=node_id, vmid=vmid)
        self.client.check_permissions(vmid=vmid, storage=before["storage_id"])
        return {"target": {"node_id": node_id, "vmid": vmid}, "observed_before": before,
                "warnings": ["정지 VM의 NFS scsi0 raw/qcow2 디스크를 확장합니다. 축소는 지원하지 않습니다.",
                             "게스트 partition·filesystem 확장은 별도로 수행해야 합니다."]}


    @staticmethod
    def matches(after, requested, before):
        return (after["name"] == requested["expected_name"] and after["volume_id"] == requested["expected_volume"]
                and after["size_bytes"] == requested["size_gib"] * GIB)
