"""Explicit VM deletion; task success alone does not prove resource removal."""
from app.operations.vm_config.task_application import TaskChangeService
from app.operations.vm_delete.domain import DeleteError, check_expected, validate_target


class DeleteService(TaskChangeService):
    operation_type = 'vm_delete'
    operation_prefix = 'vm-delete-'
    event_prefix = 'delete_'
    error_prefix = 'VM_DELETE_'
    error_type = DeleteError
    check_expected = staticmethod(check_expected)

    def review(self, *, node_id, vmid):
        validate_target(node_id, vmid)
        before = self.client.read(node_id=node_id, vmid=vmid)
        return {'target': {'node_id': node_id, 'vmid': vmid}, 'observed_before': before,
            'warnings': ['VM 설정·연결된 소유 disk와 VM 전용 ACL·방화벽을 영구 삭제합니다. 자동 복구할 수 없습니다.',
                         'backup과 미참조 disk, 외부 backup job 설정은 삭제하지 않습니다. HA/replication이 있으면 PVE가 거부합니다.',
                         'PVE DELETE에는 digest 조건부 실행이 없습니다. 최종 조회 후에도 외부 관리자가 동시에 설정을 바꾸면 영향이 달라질 수 있습니다. 이 VM의 동시 변경을 중지한 상태에서 실행하세요.',
                         '실패·응답 유실은 자동 재삭제하지 않습니다. Operation과 실제 잔여 자원을 확인하세요.']}

    def observe_result(self, operation):
        target = operation.details['target']
        return self.client.observe_deletion(node_id=target['node_id'], vmid=target['vmid'], before=operation.details['observed_before'])

    @staticmethod
    def matches(after, requested, before):
        return (after['vmid_unused'] is True and not after['remaining_volumes'] and not after['preservation_unconfirmed']
                and set(after['deleted_volumes']) == {row['volume_id'] for row in before['deleted_volumes']}
                and set(after['preserved_volumes']) == {row['volume_id'] for row in before['preserved_volumes']})
