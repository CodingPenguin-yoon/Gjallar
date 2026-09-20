from app.operations.vm_config.task_application import TaskChangeService
from app.operations.vm_template.domain import TemplateError, check_expected, validate_target


class TemplateService(TaskChangeService):
    operation_type = 'vm_template'
    operation_prefix = 'vm-template-'
    event_prefix = 'template_'
    error_prefix = 'VM_TEMPLATE_'
    error_type = TemplateError
    check_expected = staticmethod(check_expected)

    def review(self, *, node_id, vmid):
        validate_target(node_id, vmid)
        before = self.client.read(node_id=node_id, vmid=vmid)
        return {'target': {'node_id': node_id, 'vmid': vmid}, 'observed_before': before, 'warnings': [
            '원본 VM을 제자리에서 템플릿으로 전환합니다. 직접 부팅할 수 없으며 자동 역변환하지 않습니다.',
            '계정·인증키, machine-id·SSH host key 재생성, cloud-init 상태, 고정 IP와 민감 파일을 배포용으로 준비하세요. 이 작업은 게스트를 청소하지 않습니다.',
            'PVE API에 digest 조건부 실행이 없습니다. 외부 관리자의 동시 변경을 중지하세요.',
            '실패 후에도 template flag나 일부 volume이 변경됐을 수 있습니다. 자동 재요청하지 않습니다.',
            '전환 성공은 배포 준비 검증이 아닙니다. 생성용 template scope를 명시적으로 갱신하고 별도 테스트 배포를 수행하세요.']}

    def observe_result(self, operation):
        target = operation.details['target']
        after = self.client.read(node_id=target['node_id'], vmid=target['vmid'], converted=True)
        return {**after, 'guest_readiness': 'operator_attested_not_runtime_verified'}

    @staticmethod
    def matches(after, requested, before):
        expected = [{**row, 'volume_id': row['volume_id'].replace('/vm-', '/base-', 1) if row['slot'] == 'scsi0' else row['volume_id']}
                    for row in before['volumes']]
        return (after['template'] is True and after['status'] == 'stopped' and after['name'] == before['name']
                and after['config_fingerprint'] == before['config_fingerprint'] and after['volumes'] == expected)
