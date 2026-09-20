"""Review files for existing net0 bridge and single VLAN changes."""
import re

from . import resource_review
from .errors import ClientError
from .workflows import identifier, request_identity, segment


def show(app, vmid, node):
    return app.request(f"nodes/{segment(node)}/vms/{vmid}/network", operator=True)


def validate(payload):
    fields = {'idempotency_key', 'expected_digest', 'expected_name', 'expected_net0', 'bridge_id', 'vlan_tag'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ClientError('INVALID_REVIEW', '네트워크 검토 입력 필드를 확인하세요.', 2)
    request_identity(payload['idempotency_key'])
    if not isinstance(payload['expected_digest'], str) or not re.fullmatch(r'[a-fA-F0-9]{40}', payload['expected_digest']):
        raise ClientError('INVALID_REVIEW', '설정 변경 감지값이 올바르지 않습니다.', 2)
    if (not isinstance(payload['expected_name'], str) or len(payload['expected_name']) > 255
            or not isinstance(payload['expected_net0'], str) or not 1 <= len(payload['expected_net0']) <= 2048):
        raise ClientError('INVALID_REVIEW', 'VM 이름·기존 net0 설정을 확인하세요.', 2)
    identifier(payload['bridge_id'])
    tag = payload['vlan_tag']
    if tag is not None and (type(tag) is not int or not 1 <= tag <= 4094):
        raise ClientError('INVALID_VLAN', 'VLAN tag는 1~4094 정수 또는 untagged여야 합니다.', 2)


def plan(app, *, vmid, node, bridge_id, vlan_tag, request_id, review_file):
    node = identifier(node)
    result = show(app, vmid, node)
    review = result['data']
    if not isinstance(review, dict) or review.get('target') != {'node_id': node, 'vmid': vmid}:
        raise ClientError('TARGET_CHANGED', '조회한 대상이 선택한 VM과 다릅니다.', 8)
    before = review.get('observed_before', {})
    payload = {'idempotency_key': request_id, 'expected_digest': before.get('digest'), 'expected_name': before.get('name'),
               'expected_net0': before.get('net0'), 'bridge_id': bridge_id, 'vlan_tag': vlan_tag}
    validate(payload)
    selected = next((row for row in before.get('bridges', []) if row.get('bridge_id') == bridge_id), None)
    if not selected or vlan_tag is not None and selected.get('vlan_aware') is not True:
        raise ClientError('BRIDGE_UNAVAILABLE', 'bridge 사용 권한·active 상태·VLAN-aware 여부를 확인하세요.', 2)
    if (bridge_id, vlan_tag) == (before.get('bridge_id'), before.get('vlan_tag')):
        raise ClientError('NO_CHANGE', '현재 네트워크 설정과 같습니다.', 2)
    resource_review.save(app, schema='gjallar.cli.network.v1', review=review, payload=payload, path=review_file)
    return {**result, 'data': {'target': review['target'], 'before': before, 'after': {'bridge_id': bridge_id, 'vlan_tag': vlan_tag},
                              'warnings': review.get('warnings', [])}, 'review_file': str(review_file),
            'message': '검토를 저장했습니다. 아직 NIC를 변경하지 않았습니다. 게스트 통신 확인은 별도입니다.',
            'exit_code': 0, 'next': 'gjallar vm network execute --review-file <파일>로 검토한 변경을 실행하세요.'}


def execute(app, review_file, confirm):
    return resource_review.execute(app, review_file, confirm, schema='gjallar.cli.network.v1',
        validate=validate, action='network', label='기존 net0 bridge/VLAN 변경 (게스트 통신 별도 확인)')
