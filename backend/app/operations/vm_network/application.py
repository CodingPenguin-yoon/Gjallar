"""Network review and comparison on the shared synchronous config flow."""
from app.operations.vm_config.application import ConfigChangeService
from app.operations.vm_network.domain import NetworkError, check_expected, observed_network, parse_net0, replace_network, validate_target


class NetworkService(ConfigChangeService):
    operation_type = "vm_network"
    operation_prefix = "vm-network-"
    event_prefix = "network_"
    error_prefix = "VM_NETWORK_"
    error_type = NetworkError
    validate_target = staticmethod(validate_target)
    check_expected = staticmethod(check_expected)

    def observe(self, *, node_id, vmid):
        return observed_network(*self.client.read(node_id=node_id, vmid=vmid))

    def review(self, *, node_id, vmid):
        validate_target(node_id, vmid)
        self.client.check_permissions(vmid=vmid)
        before = self.observe(node_id=node_id, vmid=vmid)
        return {"target": {"node_id": node_id, "vmid": vmid}, "observed_before": before,
                "warnings": ["정지 VM의 기존 net0 bridge와 단일 VLAN tag만 변경합니다. 모델·MAC·나머지 옵션은 유지합니다.",
                             "게스트 IP·경로는 바꾸지 않습니다. 변경 후 게스트 통신은 별도로 확인하세요."]}

    @staticmethod
    def matches(observed, requested, before):
        expected = replace_network(before["net0"], requested["bridge_id"], requested["vlan_tag"])
        bridge = next((row for row in observed["bridges"] if row["bridge_id"] == requested["bridge_id"]), None)
        return (observed["name"] == requested["expected_name"] and parse_net0(observed["net0"]) == parse_net0(expected)
                and bridge is not None and (requested["vlan_tag"] is None or bridge["vlan_aware"]))
