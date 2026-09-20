"""Full clone on the shared task flow with source and destination coordination."""
from app.operations.vm_config.task_application import TaskChangeService
from app.operations.vm_clone.domain import CloneError, check_expected, matches, validate_target


class CloneService(TaskChangeService):
    operation_type = 'vm_clone'
    operation_prefix = 'vm-clone-'
    event_prefix = 'clone_'
    error_prefix = 'VM_CLONE_'
    error_type = CloneError
    check_expected = staticmethod(check_expected)
    matches = staticmethod(matches)

    def review(self, *, node_id, vmid, new_vmid, storage_id):
        validate_target(node_id, vmid, new_vmid, storage_id)
        before = self.client.review(node_id=node_id, vmid=vmid, new_vmid=new_vmid, storage_id=storage_id)
        return {'target': {'node_id': node_id, 'vmid': vmid}, 'observed_before': before,
                'warnings': ['같은 node에서 NFS scsi0 한 개와 선택적 cloud-init을 full clone합니다. 복제본은 정지 상태로 남깁니다.',
                             '게스트 IP·hostname·SSH host key와 디스크 내용은 복사됩니다. 충돌을 정리하기 전에 원본과 함께 시작하지 마세요.',
                             '복제본 설명에는 이 Operation 식별자를 기록합니다. 원본 설명은 변경하지 않습니다.',
                             '실패 잔여 자원을 자동 삭제하거나 복제를 재실행하지 않습니다. Operation에서 결과를 확인하세요.']}

    def review_request(self, *, node_id, vmid, request):
        return self.review(node_id=node_id, vmid=vmid, new_vmid=request.new_vmid, storage_id=request.storage_id)

    def target(self, *, node_id, vmid, request):
        return {'node_id': node_id, 'vmid': request.new_vmid, 'name': request.name}

    def extra_details(self, *, node_id, vmid, request):
        return {'source': {'node_id': node_id, 'vmid': vmid, 'name': request.expected_name}}

    def admit(self, spec, *, node_id, vmid, request):
        return self.admission.prepare(spec, cluster_id=self.cluster_id, vmid=request.new_vmid, related_vmids=(vmid,))

    def observe_result(self, operation):
        source, target = operation.details['source'], operation.details['target']
        return {'expected_marker': operation.operation_id,
                'source': self.client.read(node_id=source['node_id'], vmid=source['vmid']),
                'destination': self.client.read(node_id=target['node_id'], vmid=target['vmid'])}

    def dispatch(self, *, node_id, vmid, request, operation):
        return self.client.apply(node_id=node_id, vmid=vmid, request=request, marker=operation.operation_id)
