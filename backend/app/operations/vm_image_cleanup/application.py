import re
from pydantic import ValidationError
from app.cloud_images.catalog import ImageError, image_by_id
from app.cloud_images.contracts import BuildRequest
from app.operations.core.domain import operation_digest
from app.operations.vm_config.task_application import TaskChangeService
from app.operations.vm_image_cleanup.domain import check_expected


class ImageCleanupService(TaskChangeService):
    operation_type = 'vm_image_cleanup'
    operation_prefix = 'vm-image-cleanup-'
    event_prefix = 'image_cleanup_'
    error_prefix = 'IMAGE_CLEANUP_'
    error_type = ImageError
    check_expected = staticmethod(check_expected)

    def owned_build(self, *, node_id, vmid, parent_operation_id):
        if not re.fullmatch(r'vm-image-build-[a-f0-9]{64}', parent_operation_id):
            raise ImageError('IMAGE_CLEANUP_OWNER_INVALID', '공식 이미지 제작 Operation ID를 확인하세요.', 422)
        parent = self.operations.get(parent_operation_id)
        recovery = self.recovery.get(parent_operation_id)
        if (parent is None or parent.operation_type != 'vm_image_build' or parent.execution_mode != 'managed_api'
                or parent.status != 'succeeded' or not recovery or recovery.status != 'completed'
                or parent.details.get('cluster_id') != self.cluster_id
                or parent.details.get('target', {}).get('node_id') != node_id
                or parent.details.get('target', {}).get('vmid') != vmid):
            raise ImageError('IMAGE_CLEANUP_OWNER_UNCONFIRMED', '완료된 동일 cluster/node/VMID 제작 기록이 필요합니다. 미확정 잠금을 강제 해제하지 않습니다.')
        try:
            request = BuildRequest.model_validate(parent.details.get('requested'))
        except ValidationError:
            raise ImageError('IMAGE_CLEANUP_OWNER_UNCONFIRMED', '제작 입력 기록을 확인할 수 없습니다.', 503) from None
        image = image_by_id(request.image_id)
        source = parent.details.get('source_integrity', {})
        if (source != {'image_id': image.image_id, 'sha256': image.sha256, 'download_bytes': image.download_bytes,
                       'virtual_size_bytes': image.virtual_size_bytes} or not parent.details.get('observed_after', {}).get('template')):
            raise ImageError('IMAGE_CLEANUP_OWNER_UNCONFIRMED', '제작한 원본·template 소유 증거를 확인할 수 없습니다.')
        return parent

    def review(self, *, node_id, vmid, parent_operation_id, resource):
        if resource not in {'template', 'source'} or type(vmid) is not int or not 100 <= vmid <= 999999999:
            raise ImageError('IMAGE_CLEANUP_INPUT_INVALID', '정리 대상 VMID와 template/source 종류를 확인하세요.', 422)
        parent = self.owned_build(node_id=node_id, vmid=vmid, parent_operation_id=parent_operation_id)
        evidence = self.client.read(node_id=node_id, vmid=vmid, parent=parent, resource=resource)
        before = {'parent_operation_id': parent_operation_id, 'resource': resource, 'vmid': vmid,
                  'name': parent.details['target']['name'], **evidence}
        before['review_digest'] = operation_digest(before)
        return {'target': {'node_id': node_id, 'vmid': vmid}, 'observed_before': before,
                'warnings': ['선택한 제작 소유 자원만 영구 삭제합니다. 자동 복구할 수 없습니다.',
                    'template 삭제는 VM 설정·연결 disk·전용 ACL/방화벽을 제거합니다. source 삭제는 업로드 원본만 제거합니다.',
                    '외부 동시 변경을 중지하세요. PVE DELETE에는 digest 조건부 실행이 없습니다.',
                    'task 성공과 실제 부재·보존 자원을 모두 확인합니다. 실패·응답 유실은 자동 재삭제하지 않습니다.']}

    def review_request(self, *, node_id, vmid, request):
        return self.review(node_id=node_id, vmid=vmid, parent_operation_id=request.parent_operation_id, resource=request.resource)

    def dispatch(self, *, node_id, vmid, request, operation):
        return self.client.apply(node_id=node_id, vmid=vmid, before=operation.details['observed_before'])

    def observe_result(self, operation):
        target = operation.details['target']
        return self.client.observe_deletion(node_id=target['node_id'], vmid=target['vmid'], before=operation.details['observed_before'])

    @staticmethod
    def matches(after, requested, before):
        return (after.get('removed') is True and not after.get('remaining_volumes') and not after.get('preservation_unconfirmed')
                and (before['resource'] != 'template' or after.get('vmid_unused') is True))
