from app.backups.domain import BackupError
from app.operations.vm_backup.domain import check_expected, task_reference
from app.operations.vm_config.task_application import TaskChangeService


class BackupService(TaskChangeService):
    operation_type = 'vm_backup'
    operation_prefix = 'vm-backup-'
    event_prefix = 'backup_'
    error_prefix = 'VM_BACKUP_'
    error_type = BackupError
    check_expected = staticmethod(check_expected)

    def listing(self, **kwargs): return self.client.listing(**kwargs)

    def review(self, *, node_id, vmid, storage):
        before = self.client.read(node_id=node_id, vmid=vmid, storage=storage)
        return {'target': {'node_id': node_id, 'vmid': vmid}, 'observed_before': before, 'warnings': [
            '정지 VM의 새 압축 백업을 만들며 기존 백업 삭제·보존 정책 변경·알림 발송은 하지 않습니다.',
            '호스트/저장소 IO와 공간을 사용합니다. 여유 공간은 예약되지 않으며 압축률과 실제 사용량을 보장하지 않습니다.',
            'PVE에는 조건부 digest 백업 API가 없습니다. 원본·백업 기본값·기존 archive의 외부 동시 변경을 중지하세요.',
            '백업 파일과 task 성공만으로 게스트 복원·부팅·접속 성공을 보장하지 않습니다. 별도 VM으로 검사하세요.',
            '결과 불명 시 자동 재실행·부분 파일 삭제를 하지 않습니다. 작업 기록과 PVE task/archive를 확인하세요.']}

    def review_request(self, *, node_id, vmid, request):
        return self.review(node_id=node_id, vmid=vmid, storage=request.storage_id)

    def dispatch(self, *, node_id, vmid, request, operation):
        return self.client.apply(node_id=node_id, vmid=vmid, request=request, operation_id=operation.operation_id)

    def observe_result(self, operation):
        target = operation.details['target']
        task_reference(operation.details['proxmox_upid'], node_id=target['node_id'], vmid=target['vmid'])
        after = self.client.read(node_id=target['node_id'], vmid=target['vmid'], storage=operation.details['requested']['storage_id'], require_space=False)
        old = {row['volume_id']: row for row in operation.details['observed_before']['archives']}
        matches = [row for row in after['archives'] if row['operation_marker'] == operation.operation_id and row['volume_id'] not in old]
        return {**after, 'created_archive': matches[0] if len(matches) == 1 else None,
                'previous_archives_preserved': all(row in after['archives'] for row in old.values()),
                'restore_verified': False}

    def verify(self, lease, operation, task=None):
        target = operation.details['target']
        if operation.details.get('proxmox_upid'):
            try:
                task_reference(operation.details['proxmox_upid'], node_id=target['node_id'], vmid=target['vmid'])
            except BackupError as exc:
                return self.pause(lease, operation, exc.code)
        return super().verify(lease, operation, task=task)

    @staticmethod
    def matches(after, requested, before):
        return (after['created_archive'] is not None and after['previous_archives_preserved'] is True
                and after['config_fingerprint'] == before['config_fingerprint'] and after['volumes'] == before['volumes']
                and after['name'] == before['name'] and after['status'] == 'stopped')
