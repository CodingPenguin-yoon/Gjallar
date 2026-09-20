"""Review whole-VM deletion with explicit identity and resource confirmation."""
import re

from . import resource_review
from .errors import ClientError
from .workflows import identifier, request_identity, segment


def show(app, vmid, node):
    return app.request(f"nodes/{segment(node)}/vms/{vmid}/deletion", operator=True)


def validate(payload):
    fields = {'idempotency_key', 'expected_digest', 'expected_name', 'expected_resources_digest', 'confirmation', 'delete_acknowledged'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ClientError('INVALID_REVIEW', '삭제 검토 입력 필드를 확인하세요.', 2)
    request_identity(payload['idempotency_key'])
    for key, pattern in [('expected_digest', r'[a-fA-F0-9]{40}'), ('expected_resources_digest', r'sha256:[a-f0-9]{64}')]:
        if not isinstance(payload[key], str) or not re.fullmatch(pattern, payload[key]):
            raise ClientError('INVALID_REVIEW', '설정·자원 변경 감지값을 확인하세요.', 2)
    name = payload['expected_name']
    confirmation = payload['confirmation']
    if (not isinstance(name, str) or not 1 <= len(name) <= 255 or not isinstance(confirmation, str)
            or not re.fullmatch(r'[1-9][0-9]{2,8}/' + re.escape(name), confirmation)
            or payload['delete_acknowledged'] is not True):
        raise ClientError('DELETE_CONFIRMATION_REQUIRED', 'VMID/이름을 그대로 입력하고 복구 불가 삭제 영향을 확인하세요.', 2)


def plan(app, *, vmid, node, confirmation, delete_acknowledged, request_id, review_file):
    node = identifier(node)
    result = show(app, vmid, node)
    review = result['data']
    if not isinstance(review, dict) or review.get('target') != {'node_id': node, 'vmid': vmid}:
        raise ClientError('TARGET_CHANGED', '조회한 대상이 선택한 VM과 다릅니다.', 8)
    before = review.get('observed_before', {})
    payload = {'idempotency_key': request_id, 'expected_digest': before.get('digest'), 'expected_name': before.get('name'),
               'expected_resources_digest': before.get('resources_digest'), 'confirmation': confirmation, 'delete_acknowledged': delete_acknowledged}
    validate(payload)
    if confirmation != f"{vmid}/{before['name']}":
        raise ClientError('DELETE_CONFIRMATION_REQUIRED', '조회한 VMID/이름을 그대로 입력하세요.', 2)
    resource_review.save(app, schema='gjallar.cli.delete.v1', review=review, payload=payload, path=review_file)
    return {**result, 'review_file': str(review_file), 'exit_code': 0,
            'message': '삭제 검토를 저장했습니다. 아직 삭제하지 않았습니다. 삭제·보존 자원과 경고를 확인하세요.',
            'next': 'gjallar vm delete execute --review-file <파일>로 검토한 삭제를 실행하세요.'}


def execute(app, review_file, confirm):
    return resource_review.execute(app, review_file, confirm, schema='gjallar.cli.delete.v1', validate=validate,
                                   action='delete', label='VM 전체 영구 삭제 (자동 복구 불가·연결 소유 disk/ACL/방화벽 포함)')
