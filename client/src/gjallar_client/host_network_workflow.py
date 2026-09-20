"""Private bridge review and one explicit node-wide network application."""
import re

from .errors import ClientError
from .resource_review import save
from .workflows import mutation, read_json, request_identity, segment


def vlan_ranges(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise ClientError('INVALID_VLAN', 'VLAN 목록을 입력하세요.', 2)
    numbers = set()
    for part in value.split():
        if not re.fullmatch(r'[1-9][0-9]{0,3}(?:-[1-9][0-9]{0,3})?', part):
            raise ClientError('INVALID_VLAN', 'VLAN은 공백으로 구분한 1~4094 ID 또는 범위여야 합니다.', 2)
        bounds = [int(number) for number in part.split('-')]
        if not 1 <= bounds[0] <= bounds[-1] <= 4094:
            raise ClientError('INVALID_VLAN', 'VLAN 범위는 1~4094여야 합니다.', 2)
        numbers.update(range(bounds[0], bounds[-1] + 1))
    ordered = sorted(numbers)
    groups = []
    start = end = ordered[0]
    for number in ordered[1:]:
        if number == end + 1:
            end = number
        else:
            groups.append(str(start) if start == end else f'{start}-{end}')
            start = end = number
    groups.append(str(start) if start == end else f'{start}-{end}')
    return ' '.join(groups)


def validate_target(target):
    if (not isinstance(target, dict) or set(target) != {'node_id', 'bridge_id'}
            or not isinstance(target['node_id'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', target['node_id'])
            or not isinstance(target['bridge_id'], str) or not re.fullmatch(r'vmbr[0-9]{1,4}', target['bridge_id'])):
        raise ClientError('INVALID_TARGET', '노드와 vmbrN bridge 이름을 확인하세요.', 2)


def validate_change(change):
    if (not isinstance(change, dict) or set(change) != {'mode', 'autostart', 'vlan_aware', 'vlan_ids'}
            or change['mode'] not in {'create', 'update'} or type(change['autostart']) is not bool
            or type(change['vlan_aware']) is not bool):
        raise ClientError('INVALID_REVIEW', 'bridge 변경 내용을 확인하세요.', 2)
    if change['vlan_aware']:
        if vlan_ranges(change['vlan_ids']) != change['vlan_ids']:
            raise ClientError('INVALID_REVIEW', '검토 파일의 VLAN 목록은 정규화돼야 합니다.', 2)
    elif change['vlan_ids'] is not None:
        raise ClientError('INVALID_REVIEW', 'VLAN-aware가 꺼지면 VLAN 목록을 지정할 수 없습니다.', 2)


def validate(payload, target):
    fields = {'mode', 'autostart', 'vlan_aware', 'vlan_ids', 'idempotency_key', 'expected_review_digest',
              'confirmation', 'acknowledge_node_reload'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ClientError('INVALID_REVIEW', 'bridge 검토 필드를 확인하세요.', 2)
    validate_change({key: payload[key] for key in ('mode', 'autostart', 'vlan_aware', 'vlan_ids')})
    request_identity(payload['idempotency_key'])
    if (not isinstance(payload['expected_review_digest'], str)
            or not re.fullmatch(r'sha256:[a-f0-9]{64}', payload['expected_review_digest'])
            or payload['confirmation'] != f"{target['node_id']}/{target['bridge_id']}/{payload['mode']}"
            or payload['acknowledge_node_reload'] is not True):
        raise ClientError('HOST_NETWORK_CONFIRMATION_REQUIRED', '대상 확인 문구와 노드 전체 네트워크 반영에 동의하세요.', 2)


def plan(app, *, node, bridge, mode, autostart, vlan_aware, vlan_ids, request_id, confirmation, acknowledge, review_file):
    target = {'node_id': node, 'bridge_id': bridge}
    validate_target(target)
    change = {'mode': mode, 'autostart': autostart, 'vlan_aware': vlan_aware,
              'vlan_ids': vlan_ranges(vlan_ids) if vlan_aware else vlan_ids}
    validate_change(change)
    result = app.request(f'nodes/{segment(node)}/host-network/{segment(bridge)}/review', method='POST', body=change, operator=True)
    review = result['data']
    desired = review.get('desired') if isinstance(review, dict) else None
    if (not isinstance(review, dict) or review.get('target') != target or review.get('mode') != mode
            or not isinstance(desired, dict) or any(desired.get(key) != change[key] for key in ('autostart', 'vlan_aware', 'vlan_ids'))):
        raise ClientError('TARGET_CHANGED', '조회한 bridge 대상과 변경 내용이 다릅니다.', 8)
    payload = {**change, 'idempotency_key': request_id, 'expected_review_digest': review.get('review_digest'),
               'confirmation': confirmation, 'acknowledge_node_reload': acknowledge}
    validate(payload, target)
    save(app, schema='gjallar.cli.host-network.v1', review=review, payload=payload, path=review_file)
    return {**result, 'review_file': str(review_file), 'exit_code': 0,
            'message': 'bridge 검토를 저장했습니다. 아직 설정을 저장하거나 반영하지 않았습니다.',
            'next': 'gjallar host network execute --review-file <파일>'}


def execute(app, review_file, confirm):
    record = read_json(review_file)
    _, profile = app.connections.get(app.connection_name)
    if (record.get('schema') != 'gjallar.cli.host-network.v1' or record.get('origin') != profile['origin']
            or record.get('connection_id') != profile['id']):
        raise ClientError('REVIEW_CONNECTION_MISMATCH', '검토 파일을 만든 서버 연결을 선택하세요.', 2)
    target, payload = record.get('target'), record.get('payload')
    validate_target(target)
    validate(payload, target)
    review = record.get('review')
    if (not isinstance(review, dict) or review.get('target') != target or review.get('mode') != payload['mode']
            or review.get('review_digest') != payload['expected_review_digest'] or review.get('confirmation') != payload['confirmation']):
        raise ClientError('INVALID_REVIEW', '저장된 대상과 검토 기록이 다릅니다.', 2)
    confirm({'server': profile['origin'], 'action': 'bridge 저장과 노드 전체 네트워크 반영',
             'target': target, 'review': review, 'requested': payload})
    return mutation(app, f"nodes/{segment(target['node_id'])}/host-network/{segment(target['bridge_id'])}/actions/configure",
        payload, 'gjallar operations list', expected_operation={'type': 'host_network', 'target_type': 'proxmox_network',
        'target_id': f"node:{target['node_id']}/bridge:{target['bridge_id']}", 'target': target})
