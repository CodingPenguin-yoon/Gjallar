"""Review and explicitly remove one resource owned by a completed image build."""
import re
from urllib.parse import urlencode
from . import resource_review
from .errors import ClientError
from .workflows import identifier, request_identity, segment


def show(app, *, vmid, node, parent_operation_id, resource):
    identifier(node)
    if not re.fullmatch(r'vm-image-build-[a-f0-9]{64}', parent_operation_id) or resource not in {'template', 'source'}:
        raise ClientError('INVALID_REVIEW', '제작 Operation ID와 template/source 정리 종류를 확인하세요.', 2)
    return app.request(f'nodes/{segment(node)}/vms/{vmid}/image-cleanup?' + urlencode({
        'parent_operation_id': parent_operation_id, 'resource': resource}), operator=True)


def validate(payload):
    fields = {'parent_operation_id', 'resource', 'expected_name', 'expected_review_digest', 'idempotency_key', 'confirmation', 'cleanup_acknowledged'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ClientError('INVALID_REVIEW', '정리 검토 입력 필드를 확인하세요.', 2)
    request_identity(payload['idempotency_key'])
    for key, pattern in [('parent_operation_id', r'vm-image-build-[a-f0-9]{64}'),
                          ('expected_review_digest', r'sha256:[a-f0-9]{64}'), ('expected_name', r'[A-Za-z0-9][A-Za-z0-9.-]{0,62}')]:
        if not isinstance(payload[key], str) or not re.fullmatch(pattern, payload[key]):
            raise ClientError('INVALID_REVIEW', '소유 작업·이름·자원 검토값을 확인하세요.', 2)
    if (payload['resource'] not in {'template', 'source'} or payload['cleanup_acknowledged'] is not True
            or not isinstance(payload['confirmation'], str) or not re.fullmatch(
                r'[1-9][0-9]{2,8}/' + re.escape(payload['expected_name']) + '/' + payload['resource'], payload['confirmation'])):
        raise ClientError('IMAGE_CLEANUP_CONFIRMATION_REQUIRED', 'VMID/이름/정리 종류와 영구 삭제 영향을 확인하세요.', 2)


def plan(app, *, vmid, node, parent_operation_id, resource, confirmation, acknowledged, request_id, review_file):
    result = show(app, vmid=vmid, node=node, parent_operation_id=parent_operation_id, resource=resource)
    review = result['data']
    if not isinstance(review, dict) or review.get('target') != {'node_id': node, 'vmid': vmid}:
        raise ClientError('TARGET_CHANGED', '조회한 대상이 선택한 정리 대상과 다릅니다.', 8)
    before = review.get('observed_before', {})
    if before.get('parent_operation_id') != parent_operation_id or before.get('resource') != resource:
        raise ClientError('TARGET_CHANGED', '조회한 제작 소유 기록·정리 종류가 다릅니다.', 8)
    payload = {'parent_operation_id': parent_operation_id, 'resource': resource, 'expected_name': before.get('name'),
        'expected_review_digest': before.get('review_digest'), 'idempotency_key': request_id,
        'confirmation': confirmation, 'cleanup_acknowledged': acknowledged}
    validate(payload)
    if confirmation != f"{vmid}/{before['name']}/{resource}":
        raise ClientError('IMAGE_CLEANUP_CONFIRMATION_REQUIRED', 'VMID/이름/정리 종류를 그대로 입력하세요.', 2)
    resource_review.save(app, schema='gjallar.cli.image-cleanup.v1', review=review, payload=payload, path=review_file)
    return {**result, 'review_file': str(review_file), 'exit_code': 0,
        'message': '소유 자원 정리 검토를 저장했습니다. 아직 삭제하지 않았습니다.',
        'next': 'gjallar vm image-cleanup execute --review-file <파일>로 선택 자원만 정리하세요.'}


def execute(app, review_file, confirm):
    return resource_review.execute(app, review_file, confirm, schema='gjallar.cli.image-cleanup.v1', validate=validate,
        action='image-cleanup', label='제작 Operation의 선택 소유 자원 영구 삭제 (자동 복구 불가)')
