"""One isolated restore task with durable source and destination coordination."""
import uuid
from app.backups.domain import BackupError
from app.operations.vm_config.task_application import TaskChangeService
from app.operations.vm_restore.domain import check_expected, task_reference


class RestoreService(TaskChangeService):
    operation_type = 'vm_restore'
    operation_prefix = 'vm-restore-'
    event_prefix = 'restore_'
    error_prefix = 'VM_RESTORE_'
    error_type = BackupError
    check_expected = staticmethod(check_expected)

    def review(self, *, node_id, vmid, archive, new_vmid, storage_id, bridge_id):
        before = self.client.review(node_id=node_id, vmid=vmid, archive=archive, new_vmid=new_vmid,
            storage_id=storage_id, bridge_id=bridge_id)
        return {'target': {'node_id': node_id, 'vmid': vmid}, 'observed_before': before, 'warnings': [
            '새 VMID로 복원하며 원본 VM과 백업 파일을 보존합니다. storage 공간과 호스트 IO를 사용합니다.',
            '자동 시작을 끄고 새 MAC과 끊어진 NIC 링크로 복원합니다. 게스트 IP·hostname·SSH key는 복사됩니다.',
            '원본·archive·호스트 설정의 외부 동시 변경을 중지하세요. 공간과 VMID는 PVE에 사전 예약되지 않습니다.',
            '복원 성공과 게스트 부팅·접속 검증은 별개입니다. 이 요청은 부팅하거나 NIC를 연결하지 않습니다.',
            '결과 불명 시 자동 재복원·잔여 VM/파일 삭제를 하지 않습니다. Operation에서 결과를 확인하세요.']}

    def review_request(self, *, node_id, vmid, request):
        return self.review(node_id=node_id, vmid=vmid, archive=request.archive, new_vmid=request.new_vmid,
            storage_id=request.storage_id, bridge_id=request.bridge_id)

    def target(self, *, node_id, vmid, request):
        return {'node_id': node_id, 'vmid': request.new_vmid, 'name': request.name}

    def extra_details(self, *, node_id, vmid, request):
        return {'source': {'node_id': node_id, 'vmid': vmid, 'name': request.expected_name}}

    def admit(self, spec, *, node_id, vmid, request):
        return self.admission.prepare(spec, cluster_id=self.cluster_id, vmid=request.new_vmid, related_vmids=(vmid,))

    def dispatch(self, *, node_id, vmid, request, operation):
        return self.client.apply(node_id=node_id, vmid=vmid, request=request,
            before=operation.details['observed_before'], operation_id=operation.operation_id)

    def observe_result(self, operation):
        original, destination, requested = operation.details['source'], operation.details['target'], operation.details['requested']
        return {**self.client.observe(node_id=original['node_id'], vmid=original['vmid'],
            new_vmid=destination['vmid'], archive=requested['archive']), 'expected_marker': operation.operation_id}

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
        target, expected, archived = after['destination'], before['destination'], before['archive']['configuration']
        for field in ('smbios_uuid', 'vmgenid'):
            original = archived[field]
            if original and original != '0':
                try:
                    value = str(uuid.UUID(target[field]))
                except (ValueError, TypeError, AttributeError):
                    return False
                if value.lower() == original.lower(): return False
        return (after['source'] == before['source'] and after['archive'] == before['archive']
            and target['vmid'] == requested['new_vmid'] and target['name'] == requested['name']
            and target['status'] == 'stopped' and target['onboot_disabled'] and target['nic_supported']
            and target['operation_marker'] == after['expected_marker']
            and target['hardware_fingerprint'] == archived['hardware_fingerprint']
            and target['nic'] == {'virtio': expected['mac'], 'bridge': requested['bridge_id'], 'link_down': '1', 'firewall': expected['firewall']}
            and all(volume['storage_id'] == requested['storage_id'] for volume in target['volumes'])
            and target['volumes'][0]['size_bytes'] == archived['size_bytes'])
