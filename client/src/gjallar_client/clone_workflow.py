"""Review a source VM and a distinct stopped full-clone destination."""
import re
from urllib.parse import urlencode

from . import resource_review
from .errors import ClientError
from .workflows import identifier, request_identity, segment


def show(app, vmid, node, new_vmid, storage):
    query = urlencode({'new_vmid': new_vmid, 'storage_id': identifier(storage)})
    return app.request(f'nodes/{segment(node)}/vms/{vmid}/clone?{query}', operator=True)


def validate(payload):
    fields = {'idempotency_key', 'expected_digest', 'expected_name', 'expected_volume', 'expected_size_bytes',
              'new_vmid', 'name', 'storage_id', 'guest_identity_acknowledged'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ClientError('INVALID_REVIEW', '복제 검토 필드를 확인하세요.', 2)
    request_identity(payload['idempotency_key'])
    if not isinstance(payload['expected_digest'], str) or not re.fullmatch(r'[a-fA-F0-9]{40}', payload['expected_digest']):
        raise ClientError('INVALID_REVIEW', '원본 설정 변경 감지값을 확인하세요.', 2)
    if (not isinstance(payload['expected_name'], str) or len(payload['expected_name']) > 255
            or not isinstance(payload['expected_volume'], str) or not 1 <= len(payload['expected_volume']) <= 255
            or type(payload['expected_size_bytes']) is not int or payload['expected_size_bytes'] <= 0):
        raise ClientError('INVALID_REVIEW', '원본 이름·volume·실제 용량을 확인하세요.', 2)
    if (type(payload['new_vmid']) is not int or not 100 <= payload['new_vmid'] <= 999999999
            or not isinstance(payload['name'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,62}', payload['name'])):
        raise ClientError('INVALID_REVIEW', '복제할 새 VMID·이름을 확인하세요.', 2)
    identifier(payload['storage_id'])
    if payload['guest_identity_acknowledged'] is not True:
        raise ClientError('IDENTITY_ACK_REQUIRED', '게스트 IP·hostname·SSH host key 복사 위험을 검토하고 --ack-guest-identity를 지정하세요.', 2)


def plan(app, *, vmid, node, new_vmid, name, storage, request_id, review_file, ack_guest_identity):
    node = identifier(node)
    if new_vmid == vmid:
        raise ClientError('INVALID_REVIEW', '새 VMID는 원본과 달라야 합니다.', 2)
    result = show(app, vmid, node, new_vmid, storage)
    review = result['data']
    if not isinstance(review, dict) or review.get('target') != {'node_id': node, 'vmid': vmid}:
        raise ClientError('TARGET_CHANGED', '조회한 원본이 선택한 VM과 다릅니다.', 8)
    before = review.get('observed_before', {})
    source = before.get('source', {})
    if before.get('destination', {}).get('vmid') != new_vmid or before.get('destination', {}).get('storage_id') != storage:
        raise ClientError('TARGET_CHANGED', '조회한 복제 대상이 선택한 VMID·storage와 다릅니다.', 8)
    payload = {'idempotency_key': request_id, 'expected_digest': source.get('digest'), 'expected_name': source.get('name'),
               'expected_volume': source.get('volume_id'), 'expected_size_bytes': source.get('size_bytes'),
               'new_vmid': new_vmid, 'name': name, 'storage_id': storage, 'guest_identity_acknowledged': ack_guest_identity}
    validate(payload)
    resource_review.save(app, schema='gjallar.cli.clone.v1', review=review, payload=payload, path=review_file)
    return {**result, 'data': {'source': source, 'destination': {**before['destination'], 'name': name, 'status': 'stopped'},
                              'warnings': review.get('warnings', [])}, 'review_file': str(review_file),
            'message': '복제 검토를 저장했습니다. 아직 VM을 복제하지 않았습니다.', 'exit_code': 0,
            'next': 'gjallar vm clone execute --review-file <파일>로 검토한 full clone을 실행하세요.'}


def execute(app, review_file, confirm):
    return resource_review.execute(app, review_file, confirm, schema='gjallar.cli.clone.v1', validate=validate,
        action='clone', label='정지 VM full clone (게스트 identity 복사·자동 시작 없음)',
        operation_vmid_from_payload=lambda payload: payload['new_vmid'])
