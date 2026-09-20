"""Sanitized reads and exact single-NIC config writes."""
from app.operations.vm_admission import VmMutationAdmission
from app.operations.vm_network.domain import NetworkError, replace_network
from app.proxmox.client import ProxmoxMutationError


class NetworkAdmission(VmMutationAdmission):
    def __init__(self):
        super().__init__(recovery_kind="vm_network_observation")


class NetworkClient:
    def __init__(self, client):
        self.client = client

    def read(self, *, node_id, vmid):
        try:
            config = self.client.get_vm_current_config(node=node_id, vmid=vmid)
            pending = self.client.get_vm_pending(node=node_id, vmid=vmid)
            snapshot = self.client.get_node_network_snapshot(node=node_id)
            # Only offer explicit bridge use rights; never infer them from visibility.
            snapshot["interfaces"] = [row for row in snapshot["interfaces"]
                if row.get("type") == "bridge" and isinstance(row.get("iface"), str)
                and "SDN.Use" in self.client.get_bridge_permissions(bridge=row["iface"])]
            status = self.client.get_vm_status(node=node_id, vmid=vmid)
            return config, status, pending, snapshot
        except ProxmoxMutationError:
            raise NetworkError("VM_NETWORK_OBSERVATION_UNAVAILABLE", "현재 VM·bridge 상태 또는 권한을 확인하지 못했습니다.", 503) from None

    def check_permissions(self, *, vmid):
        try:
            permissions = self.client.get_vm_permissions(vmid=vmid)
        except ProxmoxMutationError:
            raise NetworkError("VM_NETWORK_PERMISSION_UNAVAILABLE", "VM 권한을 확인하지 못했습니다.", 503) from None
        missing = sorted({"VM.Audit", "VM.Config.Network"} - permissions)
        if missing:
            raise NetworkError("VM_NETWORK_PERMISSION_DENIED", "연결의 네트워크 권한을 갱신하세요.", 403, {"missing_privileges": missing})

    def apply(self, *, node_id, vmid, request):
        net0 = replace_network(request.expected_net0, request.bridge_id, request.vlan_tag)
        try:
            response = self.client.set_vm_config(node=node_id, vmid=vmid, config={"net0": net0, "digest": request.expected_digest})
        except ProxmoxMutationError:
            raise NetworkError("VM_NETWORK_DISPATCH_UNKNOWN", "변경 요청 결과가 불명확합니다. 자동 재실행하지 마세요.", 503) from None
        if response is not None:
            raise NetworkError("VM_NETWORK_DISPATCH_UNKNOWN", "변경 응답 형식을 확인하지 못했습니다. 결과 조회가 필요합니다.", 503)
