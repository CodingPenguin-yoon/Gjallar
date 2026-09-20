"""Atomic admission and a sanitized Proxmox adapter for compute changes."""
from app.operations.vm_admission import VmMutationAdmission
from app.operations.vm_compute.domain import ComputeError
from app.proxmox.client import ProxmoxMutationError


class ComputeAdmission(VmMutationAdmission):
    def __init__(self):
        super().__init__(recovery_kind="vm_compute_observation")


class ComputeClient:
    def __init__(self, client):
        self.client = client

    def read(self, *, node_id, vmid):
        try:
            config = self.client.get_vm_current_config(node=node_id, vmid=vmid)
            pending = self.client.get_vm_pending(node=node_id, vmid=vmid)
            status = self.client.get_vm_status(node=node_id, vmid=vmid)
            return config, status, pending
        except ProxmoxMutationError:
            raise ComputeError("VM_COMPUTE_OBSERVATION_UNAVAILABLE", "현재 VM 설정·전원을 확인하지 못했습니다.", 503) from None

    def check_permissions(self, *, vmid):
        try:
            permissions = self.client.get_vm_permissions(vmid=vmid)
        except ProxmoxMutationError:
            raise ComputeError("VM_COMPUTE_PERMISSION_UNAVAILABLE", "VM 권한을 확인하지 못했습니다.", 503) from None
        missing = sorted({"VM.Audit", "VM.Config.CPU", "VM.Config.Memory"} - permissions)
        if missing:
            raise ComputeError("VM_COMPUTE_PERMISSION_DENIED", "연결의 CPU·메모리 권한을 갱신하세요.", 403,
                               {"missing_privileges": missing})

    def apply(self, *, node_id, vmid, request):
        try:
            response = self.client.set_vm_config(node=node_id, vmid=vmid, config={
                "cores": request.cores, "memory": request.memory_mib, "digest": request.expected_digest,
            })
        except ProxmoxMutationError:
            raise ComputeError("VM_COMPUTE_DISPATCH_UNKNOWN", "변경 요청 결과가 불명확합니다. 자동 재실행하지 마세요.", 503) from None
        if response is not None:
            raise ComputeError("VM_COMPUTE_DISPATCH_UNKNOWN", "변경 응답 형식을 확인하지 못했습니다. 결과 조회가 필요합니다.", 503)
