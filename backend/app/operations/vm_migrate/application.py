from app.operations.vm_config.task_application import TaskChangeService
from app.operations.vm_migrate.domain import MigrateError, check_expected, task_reference


class MigrateService(TaskChangeService):
    operation_type='vm_migrate'
    operation_prefix='vm-migrate-'
    event_prefix='migrate_'
    error_prefix='VM_MIGRATE_'
    error_type=MigrateError
    check_expected=staticmethod(check_expected)

    def review(self, *, node_id, vmid, destination_node):
        before=self.client.review(node_id=node_id,vmid=vmid,destination_node=destination_node)
        return {'target':{'node_id':node_id,'vmid':vmid},'observed_before':before,'warnings':[
            '정지 VM의 node 위치만 옮깁니다. 같은 shared NFS volume과 게스트 설정·identity를 보존하며 자동 시작하지 않습니다.',
            '양쪽 bridge 이름 일치는 실제 L2 연결·접속 성공을 보장하지 않습니다. 목적 네트워크와 부팅 호환성을 운영자가 확인하세요.',
            '이동 전 필요한 백업을 별도로 확인하고 외부 VM·storage·network 변경을 중지하세요.',
            '연결 단절·부분 실패 때 자동 재이동/역이동·부팅·삭제하지 않습니다. 원본 node의 task와 현재 위치를 확인하세요.']}

    def review_request(self, *, node_id, vmid, request):
        return self.review(node_id=node_id,vmid=vmid,destination_node=request.destination_node)

    def extra_details(self, *, node_id, vmid, request):
        return {'destination':{'node_id':request.destination_node,'vmid':vmid}}

    def observe_result(self, operation):
        return self.client.observe(vmid=operation.details['target']['vmid'],destination_node=operation.details['requested']['destination_node'])

    def verify(self, lease, operation, task=None):
        target=operation.details['target']
        if operation.details.get('proxmox_upid'):
            try:task_reference(operation.details['proxmox_upid'],node_id=target['node_id'],vmid=target['vmid'])
            except MigrateError as exc:return self.pause(lease,operation,exc.code)
        return super().verify(lease,operation,task=task)

    @staticmethod
    def matches(after, requested, before):
        original={key:value for key,value in before['vm'].items() if key!='digest'}
        observed={key:value for key,value in after['vm'].items() if key!='digest'}
        return (after['node_id']==requested['destination_node'] and after['source_location_absent'] is True
            and observed==original and after['destination']==before['destination'])
