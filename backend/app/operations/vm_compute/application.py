"""Compute-specific review and result comparison on the shared config flow."""
from app.operations.vm_config.application import ConfigChangeService
from app.operations.vm_compute.domain import ComputeError, check_expected, observed_compute, validate_target


class ComputeService(ConfigChangeService):
    operation_type = "vm_compute"
    operation_prefix = "vm-compute-"
    event_prefix = "compute_"
    error_prefix = "VM_COMPUTE_"
    error_type = ComputeError
    validate_target = staticmethod(validate_target)
    check_expected = staticmethod(check_expected)

    def observe(self, *, node_id, vmid):
        return observed_compute(*self.client.read(node_id=node_id, vmid=vmid))

    def review(self, *, node_id, vmid):
        validate_target(node_id, vmid)
        self.client.check_permissions(vmid=vmid)
        before = self.observe(node_id=node_id, vmid=vmid)
        return {"target": {"node_id": node_id, "vmid": vmid}, "observed_before": before,
                "limits": {"cores_min": 1, "cores_max": 128, "memory_mib_min": 128, "memory_mib_max": 1048576},
                "warnings": ["정지 상태에서 단일 socket의 코어 수와 메모리만 변경합니다.",
                             "balloon·CPU 종류·디스크·네트워크는 유지합니다. 게스트 성능은 별도 확인이 필요합니다."]}


    @staticmethod
    def matches(observed, requested, before):
        return all((observed["name"] == requested["expected_name"], observed["cores"] == requested["cores"],
                    observed["memory_mib"] == requested["memory_mib"], observed["balloon_mib"] == before["balloon_mib"]))
