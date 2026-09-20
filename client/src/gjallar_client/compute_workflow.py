"""Review-file-bound compute changes using the shared mutation result flow."""
import re

from .errors import ClientError
from .workflows import identifier, request_identity, segment
from . import resource_review


def show(app, vmid, node):
    return app.request(f'nodes/{segment(node)}/vms/{vmid}/compute', operator=True)


def validate(payload):
    if not isinstance(payload, dict) or set(payload) != {'idempotency_key', 'expected_digest', 'expected_name', 'cores', 'memory_mib'}:
        raise ClientError('INVALID_REVIEW', 'CPU·메모리 검토 입력 필드를 확인하세요.', 2)
    request_identity(payload['idempotency_key'])
    if not isinstance(payload['expected_digest'], str) or not re.fullmatch(r'[a-fA-F0-9]{40}', payload['expected_digest']):
        raise ClientError('INVALID_REVIEW', '설정 변경 감지값이 올바르지 않습니다.', 2)
    if not isinstance(payload['expected_name'], str) or len(payload['expected_name']) > 255:
        raise ClientError('INVALID_REVIEW', 'VM 이름을 확인하세요.', 2)
    for key, minimum, maximum in [('cores', 1, 128), ('memory_mib', 128, 1048576)]:
        if type(payload[key]) is not int or not minimum <= payload[key] <= maximum:
            raise ClientError('INVALID_COMPUTE', f'{key} 값은 {minimum}~{maximum} 정수여야 합니다.', 2)


def plan(app, *, vmid, node, cores, memory_mib, request_id, review_file):
    node = identifier(node)
    result = show(app, vmid, node)
    review = result['data']
    if not isinstance(review, dict) or review.get('target') != {'node_id': node, 'vmid': vmid}:
        raise ClientError('TARGET_CHANGED', '조회한 대상이 선택한 VM과 다릅니다.', 8)
    before = review.get('observed_before', {})
    payload = {'idempotency_key': request_id, 'expected_digest': before.get('digest'),
               'expected_name': before.get('name'), 'cores': cores, 'memory_mib': memory_mib}
    validate(payload)
    resource_review.save(app, schema='gjallar.cli.compute.v1', review=review, payload=payload, path=review_file)
    return {**result, 'data': {'target': review['target'], 'before': before, 'after': {'cores': cores, 'memory_mib': memory_mib},
                             'warnings': review.get('warnings', [])}, 'review_file': str(review_file),
            'message': '변경 내용을 저장했습니다. 아직 VM 설정은 변경하지 않았습니다.', 'exit_code': 0,
            'next': 'gjallar vm compute execute --review-file <파일>로 검토한 변경을 실행하세요.'}


def execute(app, review_file, confirm):
    return resource_review.execute(app, review_file, confirm, schema='gjallar.cli.compute.v1',
                                   validate=validate, action='compute', label='CPU·메모리 변경')
