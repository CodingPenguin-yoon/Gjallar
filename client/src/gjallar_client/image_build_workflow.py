"""Pinned official-image review and explicit creation of a future template VMID."""
import re
from urllib.parse import urlencode

from . import resource_review
from .errors import ClientError
from .workflows import identifier, request_identity, segment

INPUT_FIELDS = {'image_id', 'name', 'storage_id', 'staging_storage_id', 'bridge_id'}


def catalog(app):
    return app.request('templates/cloud-images', operator=True)


def show(app, *, vmid, node, configuration):
    node = identifier(node)
    validate_configuration(configuration)
    return app.request(f'nodes/{segment(node)}/vms/{vmid}/image-build?' + urlencode(configuration), operator=True)


def validate_configuration(configuration):
    if not isinstance(configuration, dict) or set(configuration) != INPUT_FIELDS:
        raise ClientError('INVALID_REVIEW', '이미지·이름·storage·bridge 입력 필드를 확인하세요.', 2)
    for key, value in configuration.items():
        pattern = r'[A-Za-z0-9][A-Za-z0-9.-]{0,62}' if key == 'name' else r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}' if key == 'image_id' else r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}'
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            raise ClientError('INVALID_REVIEW', '제작 입력의 이름과 식별자를 확인하세요.', 2)


def validate(payload):
    fields = INPUT_FIELDS | {'idempotency_key', 'expected_review_digest', 'confirmation', 'image_build_acknowledged'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ClientError('INVALID_REVIEW', '제작 검토 입력 필드를 확인하세요.', 2)
    validate_configuration({key: payload[key] for key in INPUT_FIELDS})
    request_identity(payload['idempotency_key'])
    if not isinstance(payload['expected_review_digest'], str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', payload['expected_review_digest']):
        raise ClientError('INVALID_REVIEW', '제작 검토 변경 감지값을 확인하세요.', 2)
    if (payload['image_build_acknowledged'] is not True or not isinstance(payload['confirmation'], str)
            or not re.fullmatch(r'[1-9][0-9]{2,8}/' + re.escape(payload['name']), payload['confirmation'])):
        raise ClientError('IMAGE_BUILD_CONFIRMATION_REQUIRED', '새 VMID/이름과 이미지 제작 영향을 확인하세요.', 2)


def plan(app, *, vmid, node, configuration, confirmation, acknowledged, request_id, review_file):
    node = identifier(node)
    result = show(app, vmid=vmid, node=node, configuration=configuration)
    review = result['data']
    if not isinstance(review, dict) or review.get('target') != {'node_id': node, 'vmid': vmid, 'name': configuration['name']}:
        raise ClientError('TARGET_CHANGED', '조회한 대상이 선택한 제작 대상과 다릅니다.', 8)
    payload = {**configuration, 'idempotency_key': request_id, 'expected_review_digest': review.get('review_digest'),
               'confirmation': confirmation, 'image_build_acknowledged': acknowledged}
    validate(payload)
    if confirmation != f"{vmid}/{configuration['name']}":
        raise ClientError('IMAGE_BUILD_CONFIRMATION_REQUIRED', '새 VMID/이름을 그대로 입력하세요.', 2)
    resource_review.save(app, schema='gjallar.cli.image-build.v1',
        review={**review, 'target': {'node_id': node, 'vmid': vmid}}, payload=payload, path=review_file)
    return {**result, 'review_file': str(review_file), 'exit_code': 0,
            'message': '제작 검토를 저장했습니다. 이미지 업로드·VM 생성은 아직 하지 않았습니다.',
            'next': 'gjallar vm image-build execute --review-file <파일>로 실행하고 Operation을 확인하세요.'}


def execute(app, review_file, confirm):
    return resource_review.execute(app, review_file, confirm, schema='gjallar.cli.image-build.v1', validate=validate,
        action='image-build', label='공식 이미지 업로드·새 VM 생성·템플릿 전환 (부팅 없음·staging 파일 유지)')
