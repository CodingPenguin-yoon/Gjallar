"""Bridge configuration rules; raw host configuration stays in memory."""
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Literal

from app.operations.core.domain import operation_digest
from app.operations.host_config.domain import target_identity


class BridgeError(RuntimeError):
    def __init__(self, code, message, status_code=409, details=None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.details = details or {}

    def to_detail(self):
        return {'code': self.code, 'message': str(self), 'details': self.details}


def vlan_ranges(value):
    """Canonical, bounded VLAN ranges without overlaps or ambiguous separators."""
    if not isinstance(value, str) or len(value) > 1024 or not value.strip():
        raise ValueError('VLAN 목록을 입력하세요.')
    values = set()
    for part in value.split():
        if not re.fullmatch(r'[1-9][0-9]{0,3}(?:-[1-9][0-9]{0,3})?', part):
            raise ValueError('VLAN은 공백으로 구분한 1~4094 ID 또는 범위여야 합니다.')
        bounds = [int(number) for number in part.split('-')]
        start, end = bounds[0], bounds[-1]
        if not 1 <= start <= end <= 4094:
            raise ValueError('VLAN 범위는 1~4094여야 합니다.')
        values.update(range(start, end + 1))
    ordered = sorted(values)
    groups = []
    start = end = ordered[0]
    for value in ordered[1:]:
        if value == end + 1:
            end = value
        else:
            groups.append(str(start) if start == end else f'{start}-{end}')
            start = end = value
    groups.append(str(start) if start == end else f'{start}-{end}')
    return ' '.join(groups)


class BridgeChange(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    mode: Literal['create', 'update']
    autostart: bool = True
    vlan_aware: bool = False
    vlan_ids: str | None = Field(default=None, max_length=1024)

    @model_validator(mode='after')
    def check_vlan(self):
        if self.vlan_aware:
            self.vlan_ids = vlan_ranges(self.vlan_ids)
        elif self.vlan_ids is not None:
            raise ValueError('VLAN-aware가 꺼져 있으면 VLAN 목록을 지정할 수 없습니다.')
        return self


class BridgeRequest(BridgeChange):
    idempotency_key: str = Field(min_length=1, max_length=160, pattern=r'^[A-Za-z0-9_.:-]+$')
    expected_review_digest: str = Field(pattern=r'^sha256:[a-f0-9]{64}$')
    confirmation: str = Field(max_length=180)
    acknowledge_node_reload: Literal[True]

    @field_validator('acknowledge_node_reload', mode='before')
    @classmethod
    def explicit_acknowledgement(cls, value):
        if value is not True:
            raise ValueError('노드 전체 네트워크 반영에 명시적으로 동의해야 합니다.')
        return value


def validate_target(node_id, bridge_id):
    try:
        return target_identity('host_network', {'node_id': node_id, 'bridge_id': bridge_id})
    except ValueError:
        raise BridgeError('HOST_NETWORK_TARGET_INVALID', '노드와 vmbrN bridge 이름을 확인하세요.', 422) from None


def flag(value, default=False):
    if value is None:
        return default
    if type(value) is bool or type(value) is int and value in (0, 1) or type(value) is str and value in ('0', '1'):
        return bool(int(value))
    raise BridgeError('HOST_NETWORK_CONFIG_INVALID', '네트워크 설정 응답 형식을 확인할 수 없습니다.', 503)


DYNAMIC_FIELDS = frozenset({'active', 'exists', 'priority'})
MUTABLE_FIELDS = frozenset({'autostart', 'bridge_vlan_aware', 'bridge_vids'})
BRIDGE_FIELDS = frozenset({
    'iface', 'type', 'families', 'method', 'method6', 'autostart', 'bridge_vlan_aware',
    'bridge_vids', 'bridge_ports', 'bridge_stp', 'bridge_fd', 'mtu', 'comments', 'comments6',
    'active', 'exists', 'priority', 'altnames', 'is_empty_bridge',
})


def summarize_bridge(row, *, bridge_id):
    if not isinstance(row, dict) or row.get('iface') != bridge_id or row.get('type') != 'bridge':
        raise BridgeError('HOST_NETWORK_TYPE_UNSUPPORTED', '정확한 Linux bridge 설정만 지원합니다.')
    if (set(row) - BRIDGE_FIELDS or row.get('method') != 'manual'
            or row.get('method6') not in (None, 'manual') or row.get('families') != ['inet']):
        raise BridgeError('HOST_NETWORK_MANAGEMENT_UNSUPPORTED', '호스트 주소·관리망·추가 options가 없는 VM용 bridge만 지원합니다.')
    ports = row.get('bridge_ports', '')
    if (not isinstance(ports, str) or any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.:-]{0,63}', port)
                                        for port in ports.split())):
        raise BridgeError('HOST_NETWORK_CONFIG_INVALID', '기존 bridge port를 확인할 수 없습니다.', 503)
    aware = flag(row.get('bridge_vlan_aware'))
    try:
        ids = vlan_ranges(row.get('bridge_vids', '2-4094')) if aware else None
    except ValueError:
        raise BridgeError('HOST_NETWORK_CONFIG_INVALID', '기존 VLAN 목록을 확인할 수 없습니다.', 503) from None
    return {
        'bridge_id': bridge_id, 'type': 'bridge', 'ports': sorted(ports.split()),
        'autostart': flag(row.get('autostart')), 'vlan_aware': aware, 'vlan_ids': ids,
        'active': flag(row.get('active')), 'exists': flag(row.get('exists')),
        'preserved_fingerprint': operation_digest({key: value for key, value in row.items()
            if key not in DYNAMIC_FIELDS | MUTABLE_FIELDS}),
    }


def configuration_rows(snapshot):
    if (not isinstance(snapshot, dict) or not isinstance(snapshot.get('interfaces'), list)
            or not isinstance(snapshot.get('changes'), str)):
        raise BridgeError('HOST_NETWORK_OBSERVATION_INVALID', '노드 전체 네트워크 관찰이 필요합니다.', 503)
    rows = {}
    for row in snapshot['interfaces']:
        if (not isinstance(row, dict) or not isinstance(row.get('iface'), str)
                or not row['iface'] or row['iface'] in rows):
            raise BridgeError('HOST_NETWORK_OBSERVATION_INVALID', '중복 또는 잘못된 interface 관찰입니다.', 503)
        rows[row['iface']] = row
    return rows


def other_fingerprint(rows, bridge_id):
    return operation_digest({name: {key: value for key, value in row.items() if key not in DYNAMIC_FIELDS}
                             for name, row in rows.items() if name != bridge_id})


def make_review(*, node_id, bridge_id, change, snapshot):
    validate_target(node_id, bridge_id)
    rows = configuration_rows(snapshot)
    if snapshot['changes']:
        raise BridgeError('HOST_NETWORK_PENDING_CHANGES', '기존 네트워크 대기 변경의 소유자와 반영 상태를 먼저 확인하세요.')
    before = summarize_bridge(rows[bridge_id], bridge_id=bridge_id) if bridge_id in rows else None
    if (change.mode == 'create') != (before is None):
        raise BridgeError('HOST_NETWORK_EXISTENCE_CHANGED', 'bridge 존재 여부가 요청과 다릅니다. 다시 검토하세요.')
    desired = {'autostart': change.autostart, 'vlan_aware': change.vlan_aware, 'vlan_ids': change.vlan_ids,
               'ports': [] if before is None else before['ports']}
    if before is not None and all(before[key] == value for key, value in desired.items()):
        raise BridgeError('HOST_NETWORK_NO_CHANGE', '현재 설정과 같습니다.', 422)
    # Live active/exists may change while reviewing; they are displayed but are not desired config.
    plan = {'target': {'node_id': node_id, 'bridge_id': bridge_id}, 'mode': change.mode,
            'observed_before': before, 'desired': desired,
            'other_configuration_fingerprint': other_fingerprint(rows, bridge_id)}
    digest_plan = {**plan, 'observed_before': None if before is None else {
        key: value for key, value in before.items() if key not in ('active', 'exists')}}
    return {**plan, 'review_digest': operation_digest(digest_plan),
            'confirmation': f'{node_id}/{bridge_id}/{change.mode}',
            'warnings': [
                '반영은 노드 전체 네트워크와 PVE SDN 설정 생성에 영향을 줄 수 있으며 관리 접속이 끊길 수 있습니다.',
                '검토부터 완료까지 외부 네트워크 설정 변경을 중지하세요. 갈랴르는 외부 변경을 차단하지 못합니다.',
                '물리 port·주소는 추가하지 않습니다. 신규 bridge는 내부 VM 연결용이며 기존 port는 유지합니다.',
                'autostart 해제는 즉시 down을 뜻하지 않습니다. VM 통신과 실제 VLAN 경로는 별도 검사하세요.',
            ]}


def mutation_body(change, *, bridge_id):
    body = {'type': 'bridge', 'autostart': int(change.autostart), 'bridge_vlan_aware': int(change.vlan_aware)}
    if change.mode == 'create':
        body.update({'iface': bridge_id, 'bridge_ports': ''})
    if change.vlan_aware:
        body['bridge_vids'] = change.vlan_ids
    elif change.mode == 'update':
        body['delete'] = 'bridge_vids'
    return body


def _allowed_diff_line(line, *, sign, review):
    stripped = ' '.join(line.split())
    if not stripped:
        return True
    bridge_id = review['target']['bridge_id']
    config = review['desired'] if sign == '+' else review['observed_before']
    if config is None:
        return False
    if stripped == f'auto {bridge_id}':
        return config['autostart']
    if stripped == 'bridge-vlan-aware yes':
        return config['vlan_aware']
    if stripped.startswith('bridge-vids '):
        try:
            return config['vlan_aware'] and vlan_ranges(stripped[12:]) == config['vlan_ids']
        except ValueError:
            return False
    return (review['mode'] == 'create' and sign == '+' and stripped in {
        f'iface {bridge_id} inet manual', 'bridge-ports none', 'bridge-stp off', 'bridge-fd 0'})


def assert_pending_diff(changes, review):
    """Validate unified-diff framing/counts and the exact permitted changed directives.

    This is combined with a fingerprint of every other interface. Diff context and
    raw host addresses are never returned or persisted.
    """
    if not isinstance(changes, str) or len(changes) > 262144:
        raise BridgeError('HOST_NETWORK_DIFF_UNVERIFIED', '대기 변경의 범위를 확인할 수 없습니다.')
    lines = changes.splitlines()
    if (len(lines) < 3 or not lines[0].startswith('--- /etc/network/interfaces\t')
            or not lines[1].startswith('+++ /etc/network/interfaces.new\t')):
        raise BridgeError('HOST_NETWORK_DIFF_UNVERIFIED', '대기 변경의 파일과 범위를 확인할 수 없습니다.')
    remaining_old = remaining_new = 0
    changed = False
    hunks = 0
    for line in lines[2:]:
        if line.startswith('@@'):
            header = re.fullmatch(r'@@ -[0-9]+(?:,([0-9]+))? \+[0-9]+(?:,([0-9]+))? @@(?: .*)?', line)
            if header is None or remaining_old or remaining_new:
                raise BridgeError('HOST_NETWORK_DIFF_UNVERIFIED', '대기 변경의 구간을 확인할 수 없습니다.')
            remaining_old = int(header[1]) if header[1] is not None else 1
            remaining_new = int(header[2]) if header[2] is not None else 1
            hunks += 1
            continue
        if not hunks or not line or line[0] not in ' +-':
            raise BridgeError('HOST_NETWORK_DIFF_UNVERIFIED', '대기 변경의 형식을 확인할 수 없습니다.')
        sign, value = line[0], line[1:]
        if sign in ' -':
            remaining_old -= 1
        if sign in ' +':
            remaining_new -= 1
        if min(remaining_old, remaining_new) < 0:
            raise BridgeError('HOST_NETWORK_DIFF_UNVERIFIED', '대기 변경의 길이가 일치하지 않습니다.')
        if sign != ' ':
            changed = changed or bool(value.strip())
            if not _allowed_diff_line(value, sign=sign, review=review):
                raise BridgeError('HOST_NETWORK_FOREIGN_CHANGES', '검토하지 않은 네트워크 변경이 있어 전체 반영을 중지했습니다.')
    if not hunks or not changed or remaining_old or remaining_new:
        raise BridgeError('HOST_NETWORK_DIFF_UNVERIFIED', '대기 변경의 전체 범위를 확인할 수 없습니다.')


def observe_configuration(*, snapshot, review, staged):
    rows = configuration_rows(snapshot)
    bridge_id = review['target']['bridge_id']
    if bridge_id not in rows:
        raise BridgeError('HOST_NETWORK_RESULT_ABSENT', '대상 bridge 설정이 관찰되지 않습니다.')
    observed = summarize_bridge(rows[bridge_id], bridge_id=bridge_id)
    before = review['observed_before']
    if (any(observed[key] != value for key, value in review['desired'].items())
            or before is not None and observed['preserved_fingerprint'] != before['preserved_fingerprint']
            or other_fingerprint(rows, bridge_id) != review['other_configuration_fingerprint']):
        raise BridgeError('HOST_NETWORK_CONFIGURATION_CHANGED', '대상 또는 다른 interface 설정이 검토와 다릅니다.')
    if staged:
        assert_pending_diff(snapshot['changes'], review)
    elif snapshot['changes']:
        raise BridgeError('HOST_NETWORK_PENDING_CHANGES', '반영 후 대기 변경이 남아 있습니다.')
    # PVE's optional `exists` marks physical NICs, not virtual bridge presence.
    # The exact iface/type was checked above; activation comes from `active`.
    if not staged and review['desired']['autostart'] and not observed['active']:
        raise BridgeError('HOST_NETWORK_ACTIVE_UNCONFIRMED', '반영한 bridge의 실제 활성 상태를 확인하지 못했습니다.')
    return {'configuration': observed, 'pending_changes': bool(snapshot['changes']),
            'other_configuration_preserved': True, 'guest_connectivity_verified': False,
            'kernel_vlan_table_verified': False, 'immediate_down_verified': False}


def network_request_allowed(method, pieces, data, scope):
    if len(pieces) not in (3, 4) or pieces[:1] != ['nodes'] or pieces[1] not in scope['nodes'] or pieces[2] != 'network':
        return False
    if method == 'GET':
        return data is None and (len(pieces) == 3 or pieces[3] in scope.get('host_bridges', []))
    if method == 'PUT' and len(pieces) == 3:
        return data == {'regenerate-frr': 0} and type(data['regenerate-frr']) is int
    if not isinstance(data, dict):
        return False
    create = method == 'POST' and len(pieces) == 3
    update = method == 'PUT' and len(pieces) == 4
    if not (create or update):
        return False
    bridge_id = data.get('iface') if create else pieces[3]
    if bridge_id not in scope.get('host_bridges', []):
        return False
    try:
        if type(data.get('autostart')) is not int or type(data.get('bridge_vlan_aware')) is not int:
            return False
        change = BridgeChange(mode='create' if create else 'update',
            autostart=flag(data['autostart']), vlan_aware=flag(data['bridge_vlan_aware']), vlan_ids=data.get('bridge_vids'))
    except (ValueError, BridgeError):
        return False
    return data == mutation_body(change, bridge_id=bridge_id)


def task_reference(value, *, node_id):
    if not isinstance(value, str) or len(value) > 512 or not re.fullmatch(
            rf'UPID:{re.escape(node_id)}:[0-9A-Fa-f]+:[0-9A-Fa-f]+:[0-9A-Fa-f]+:srvreload:networking:[A-Za-z0-9_.@!+-]+:', value):
        raise BridgeError('HOST_NETWORK_TASK_UNKNOWN', '정확한 노드 네트워크 반영 task를 확인할 수 없습니다.', 503)
    return value
