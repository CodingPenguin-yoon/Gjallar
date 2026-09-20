"""Review prepared-VM conversion with explicit identity and resource confirmation."""
import re

from . import resource_review
from .errors import ClientError
from .workflows import identifier, request_identity, segment


def show(app, vmid, node):
    return app.request(f"nodes/{segment(node)}/vms/{vmid}/template-conversion", operator=True)


def validate(payload):
    fields = {'idempotency_key', 'expected_digest', 'expected_name', 'expected_resources_digest', 'confirmation', 'conversion_acknowledged', 'guest_prepared'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ClientError('INVALID_REVIEW', '전환 검토 입력 필드를 확인하세요.', 2)
    request_identity(payload['idempotency_key'])
    for key, pattern in [('expected_digest', r'[a-fA-F0-9]{40}'), ('expected_resources_digest', r'sha256:[a-f0-9]{64}')]:
        if not isinstance(payload[key], str) or not re.fullmatch(pattern, payload[key]):
            raise ClientError('INVALID_REVIEW', '설정·자원 변경 감지값을 확인하세요.', 2)
    name = payload['expected_name']
    confirmation = payload['confirmation']
    if (not isinstance(name, str) or not 1 <= len(name) <= 255 or not isinstance(confirmation, str)
            or not re.fullmatch(r'[1-9][0-9]{2,8}/' + re.escape(name), confirmation)
            or payload['conversion_acknowledged'] is not True or payload['guest_prepared'] is not True):
        raise ClientError('TEMPLATE_CONFIRMATION_REQUIRED', 'VMID/이름을 그대로 입력하고 게스트 준비와 원본 부팅 불가 영향을 확인하세요.', 2)


def plan(app, *, vmid, node, confirmation, conversion_acknowledged, guest_prepared, request_id, review_file):
    node = identifier(node)
    result = show(app, vmid, node)
    review = result['data']
    if not isinstance(review, dict) or review.get('target') != {'node_id': node, 'vmid': vmid}:
        raise ClientError('TARGET_CHANGED', '조회한 대상이 선택한 VM과 다릅니다.', 8)
    before = review.get('observed_before', {})
    payload = {'idempotency_key': request_id, 'expected_digest': before.get('digest'), 'expected_name': before.get('name'),
               'expected_resources_digest': before.get('resources_digest'), 'confirmation': confirmation, 'conversion_acknowledged': conversion_acknowledged, 'guest_prepared': guest_prepared}
    validate(payload)
    if confirmation != f"{vmid}/{before['name']}":
        raise ClientError('TEMPLATE_CONFIRMATION_REQUIRED', '조회한 VMID/이름을 그대로 입력하세요.', 2)
    resource_review.save(app, schema='gjallar.cli.template.v1', review=review, payload=payload, path=review_file)
    return {**result, 'review_file': str(review_file), 'exit_code': 0,
            'message': '전환 검토를 저장했습니다. 아직 전환하지 않았습니다. 전환 volume과 게스트 준비와 경고를 확인하세요.',
            'next': 'gjallar vm template execute --review-file <파일>로 검토한 전환을 실행하세요.'}


def execute(app, review_file, confirm):
    return resource_review.execute(app, review_file, confirm, schema='gjallar.cli.template.v1', validate=validate,
                                   action='template', label='준비된 VM의 템플릿 전환 (직접 부팅 불가·게스트 자동 정리 없음)')
