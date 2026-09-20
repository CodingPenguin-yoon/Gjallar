"""CLI workflows using existing server actions; never retry mutations."""
import json
import os
from pathlib import Path
import re
from urllib.parse import quote, urlencode

from .errors import ClientError


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', value):
        raise ClientError('INVALID_ID', 'ID는 영문·숫자로 시작하는 1~128자의 영문·숫자·점·밑줄·콜론·대시입니다.', 2)
    return value


def segment(value):
    return quote(identifier(value), safe='')


def request_identity(value):
    value = identifier(value)
    if len(value) > 64:
        raise ClientError('INVALID_ID', '요청 ID는 64자 이하로 지정하세요.', 2)
    return value


def read_json(path):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError, UnicodeError):
        raise ClientError('INVALID_FILE', 'JSON 파일을 읽을 수 없습니다. 경로와 형식을 확인하세요.', 2) from None
    if not isinstance(value, dict):
        raise ClientError('INVALID_FILE', 'JSON 객체가 필요합니다.', 2)
    return value


def result_status(result):
    data = result.get('data', {})
    operation = data.get('operation', {}) if isinstance(data, dict) else {}
    if not isinstance(operation, dict):
        raise ClientError('PROTOCOL_ERROR', 'Operation 응답 계약이 맞지 않습니다.', 5)
    status = operation.get('status')
    # HTTP success is not proof of a successful mutation.
    complete = status == 'succeeded' and not operation.get('coordination_incomplete', False) and not data.get('coordination_incomplete', False)
    prefix = f"gjallar --connection {result['connection']}" if result.get('connection') else 'gjallar'
    return {**result, 'exit_code': 0 if complete else 8,
            'next': f"{prefix} operations show {operation['operation_id']}" if operation.get('operation_id') else f'{prefix} operations list'}


def mutation(app, path, payload, lookup, *, expected_operation=None, operation_id_field=None):
    response_received = False
    try:
        result = app.request(path, method='POST', body=payload, operator=True)
        response_received = True
        data = result['data']
        operation = data.get('operation') if isinstance(data, dict) else None
        if operation is None and operation_id_field and isinstance(data, dict):
            operation = {'operation_id': data.get(operation_id_field)}
        if not isinstance(operation, dict) or not operation.get('operation_id'):
            raise ClientError('PROTOCOL_ERROR', '실행 결과에 Operation ID가 없습니다.', 5)
        if operation_id_field and data.get(operation_id_field) not in (None, operation['operation_id']):
            raise ClientError('PROTOCOL_ERROR', '실행 결과의 작업 ID가 서로 다릅니다.', 5)
        observed = app.request('operations/' + segment(operation['operation_id']))['data']
        if not isinstance(observed, dict) or not isinstance(observed.get('operation'), dict):
            raise ClientError('PROTOCOL_ERROR', '작업 결과를 확인할 수 없습니다.', 5)
        canonical = observed['operation']
        if canonical.get('operation_id') != operation['operation_id']:
            raise ClientError('PROTOCOL_ERROR', '작업 결과 ID가 실행 응답과 다릅니다.', 5)
        if expected_operation:
            details = canonical.get('details', {})
            target_matches = (canonical.get('target_type') == expected_operation['target_type']
                and canonical.get('target_id') == expected_operation['target_id'] and details.get('target') == expected_operation['target']) if 'target_type' in expected_operation else (
                canonical.get('target_type') == 'proxmox_vm' and canonical.get('target_id') == f"vmid:{expected_operation['vmid']}"
                and details.get('target', {}).get('node_id') == expected_operation['node'])
            request_matches = (canonical.get('idempotency_key') == expected_operation['idempotency_key']
                               if 'idempotency_key' in expected_operation else details.get('requested') == payload)
            if canonical.get('operation_type') != expected_operation['type'] or not target_matches or not request_matches:
                raise ClientError('PROTOCOL_ERROR', '작업 결과가 검토한 대상·종류·요청과 다릅니다.', 5)
        result = {**result, 'data': observed}
    except ClientError as exc:
        if response_received or exc.code in {'COMMUNICATION_FAILED', 'SERVER_ERROR', 'PROTOCOL_ERROR'}:
            raise ClientError('MUTATION_UNCONFIRMED', f'실행 결과를 확정하지 못했습니다. 자동 재전송하지 않았습니다. 먼저 {lookup}으로 확인하세요. 동일 요청 ID를 보존하세요.', 8) from None
        raise
    return result_status(result)


def power(app, action, vmid, node, request_id, confirm):
    node, request_id = identifier(node), request_identity(request_id)
    result = app.request(f'vms/{vmid}')
    vm = result['data']
    if not isinstance(vm, dict) or vm.get('node_id') != node or vm.get('vmid') != vmid:
        raise ClientError('TARGET_CHANGED', '조회한 VM의 node/VMID가 지정한 대상과 다릅니다. 다시 조회하세요.', 8)
    confirm({'server': result['server'], 'node': node, 'vmid': vmid, 'name': vm.get('name'),
             'current_status': vm.get('status'), 'action': action, 'request_id': request_id})
    payload = {'idempotency_key': request_id, f'vm_{action}_acknowledged': True,
               'expected_name': vm.get('name', ''), 'expected_status': 'stopped' if action == 'start' else 'running'}
    return mutation(app, f'nodes/{segment(node)}/vms/{vmid}/actions/{action}', payload,
                    f'gjallar operations list --vmid {vmid}', operation_id_field='job_id',
                    expected_operation={'type': 'vm_' + action, 'target_type': 'proxmox_vm',
                        'target_id': f'vmid:{vmid}', 'target': {'node_id': node, 'vmid': vmid},
                        'idempotency_key': request_id})


SPEC_KEYS = {'creation_mode', 'profile_id', 'vmid', 'vm_name', 'target_node_id', 'storage_id',
             'bridge_id', 'static_ip', 'prefix', 'gateway', 'ip_mode', 'template_id',
             'template_vmid', 'template_node_id', 'hardware_overrides', 'access', 'power_policy'}
NESTED_KEYS = {'hardware_overrides': {'cpu', 'memory_mb', 'disk_gb'},
               'access': {'cloud_init_user', 'ssh_public_key', 'password_login'}}


def validate_spec(payload):
    if set(payload) - SPEC_KEYS:
        raise ClientError('INVALID_SPEC', '생성 입력에 지원하지 않는 필드가 있습니다. vm create example을 확인하세요.', 2)
    for field, allowed in NESTED_KEYS.items():
        if field in payload and (not isinstance(payload[field], dict) or set(payload[field]) - allowed):
            raise ClientError('INVALID_SPEC', f'{field} 입력 필드를 확인하세요.', 2)
    if payload.get('creation_mode') not in ('template', 'profile'):
        raise ClientError('INVALID_SPEC', 'creation_mode은 template 또는 profile이어야 합니다.', 2)
    for field in ('target_node_id', 'storage_id', 'bridge_id', 'vm_name'):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ClientError('INVALID_SPEC', f'{field}를 명시하세요.', 2)
    if isinstance(payload.get('vmid'), bool) or not isinstance(payload.get('vmid'), int) or not 100 <= payload['vmid'] <= 999999999:
        raise ClientError('INVALID_SPEC', '생성 VMID를 100~999999999 정수로 명시하세요. 추천 ID는 예약이 아닙니다.', 2)
    if payload.get('power_policy') not in ('stopped', 'boot_and_verify'):
        raise ClientError('INVALID_SPEC', 'power_policy는 stopped 또는 boot_and_verify로 명시하세요.', 2)


def create_plan(app, spec_file, request_id, review_file):
    spec = read_json(spec_file)
    validate_spec(spec)
    request_id = request_identity(request_id)
    payload = {**spec, 'job_id': request_id}
    _, profile = app.connections.get(app.connection_name)
    # Reserve the destination before recording any server-side draft.
    try:
        fd = os.open(review_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError:
        raise ClientError('REVIEW_FILE_EXISTS', '검토 파일을 새로 만들 수 없습니다. 기존 파일을 덮어쓰지 말고 새 경로를 지정하세요.', 7) from None
    with os.fdopen(fd, 'w') as stream:
        draft = app.request('vm-create/drafts', method='POST', body=payload, operator=True)['data']
        draft_id = draft.get('draft_id') if isinstance(draft, dict) else None
        if not draft_id:
            raise ClientError('PROTOCOL_ERROR', '서버가 draft ID를 반환하지 않았습니다.', 5)
        path = f'vm-create/{segment(draft_id)}'
        app.request(path + '/preflight', method='POST', body=payload, operator=True)
        result = app.request(path + '/plan', method='POST', body=payload, operator=True)
        plan = result['data']
        review = plan.get('review_confirm', {}) if isinstance(plan, dict) else {}
        if not isinstance(review, dict) or not review.get('plan_artifact_id') or not review.get('review_summary_checksum'):
            raise ClientError('PROTOCOL_ERROR', '서버 계획의 검토 ID/checksum이 없습니다.', 5)
        record = {'schema': 'gjallar.cli.create.v1', 'origin': profile['origin'], 'connection_id': profile['id'],
                  'draft_id': draft_id, 'payload': payload, 'review': review}
        json.dump(record, stream, ensure_ascii=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    blocked = plan.get('risk_summary', {}).get('level') == 'red'
    # Original access input stays only in the user's private file; the server review is redacted.
    return {**result, 'data': {'operation_id': request_id, 'review': review,
                              'preflight': plan.get('preflight', {})},
            'review_file': str(review_file), 'exit_code': 8 if blocked else 0,
            'message': '서버에 생성 계획을 기록했습니다. 아직 VM을 생성하지 않았습니다.',
            'next': '검토 파일과 위험 항목을 확인한 뒤 gjallar vm create execute --review-file <파일>을 실행하세요.'}


def create_execute(app, review_file, ack_yellow, confirm):
    record = read_json(review_file)
    _, profile = app.connections.get(app.connection_name)
    if (record.get('schema') != 'gjallar.cli.create.v1' or record.get('origin') != profile['origin']
            or record.get('connection_id') != profile['id']):
        raise ClientError('REVIEW_CONNECTION_MISMATCH', '검토 파일을 만든 서버 연결을 선택하세요.', 2)
    payload, review = record.get('payload'), record.get('review')
    if not isinstance(payload, dict) or not isinstance(review, dict):
        raise ClientError('INVALID_REVIEW', '검토 파일의 payload/review가 올바르지 않습니다.', 2)
    job_id = request_identity(payload.get('job_id'))
    validate_spec({key: value for key, value in payload.items() if key != 'job_id'})
    path = f"vm-create/{segment(record.get('draft_id'))}"
    for key in ('plan_artifact_id', 'review_summary_checksum'):
        if not isinstance(review.get(key), str) or not review[key]:
            raise ClientError('INVALID_REVIEW', '검토 파일의 승인 ID/checksum을 확인하세요.', 2)
    risk_summary = review.get('risk_summary')
    if not isinstance(risk_summary, dict) or risk_summary.get('level') not in ('green', 'yellow', 'red'):
        raise ClientError('INVALID_REVIEW', '검토 파일의 위험 평가가 올바르지 않습니다.', 2)
    risk = risk_summary['level']
    if risk == 'red':
        raise ClientError('PLAN_BLOCKED', 'red 위험 항목을 해결한 뒤 새 요청 ID로 계획을 검토하세요.', 8)
    if risk == 'yellow' and not ack_yellow:
        raise ClientError('ACK_REQUIRED', '계획의 yellow 위험을 검토한 뒤 --ack-yellow로 명시적으로 확인하세요.', 2)
    confirm({'server': profile['origin'], 'action': 'create', 'review': review, 'request_id': job_id})
    body = {**payload, 'plan_artifact_id': review['plan_artifact_id'],
            'review_summary_checksum': review['review_summary_checksum'], 'yellow_risk_acknowledged': ack_yellow}
    approved = app.request(path + '/approve', method='POST', body=body, operator=True)['data']
    if not isinstance(approved, dict) or approved.get('can_approve') is not True:
        return {'ok': False, 'data': approved, 'exit_code': 8, 'message': '서버가 생성을 승인하지 않았습니다.'}
    preview = app.request(path + '/proxmox-preview', method='POST', body=body, operator=True)['data']
    if not isinstance(preview, dict) or not isinstance(preview.get('approval'), dict) or preview['approval'].get('can_execute') is not True:
        raise ClientError('CREATE_DISABLED', '서버 생성 미리보기에서 실행이 허용되지 않았습니다.', 8)
    return mutation(app, path + '/proxmox-create', {**body, 'proxmox_mutation_acknowledged': True},
                    f'gjallar operations show {job_id}')


def operations(app, *, operation_id=None, vmid=None, status=None, limit=50):
    if operation_id:
        return app.request('operations/' + segment(operation_id))
    query = {'limit': limit}
    if vmid is not None:
        query.update(target_type='proxmox_vm', target_id=f'vmid:{vmid}')
    if status:
        query['status'] = status
    return app.request('operations?' + urlencode(query))


EXAMPLE = {
    'creation_mode': 'template', 'vmid': 101, 'vm_name': 'app-01',
    'template_node_id': 'pve', 'template_vmid': 9000, 'target_node_id': 'pve',
    'storage_id': 'local-lvm', 'bridge_id': 'vmbr0', 'ip_mode': 'dhcp',
    'hardware_overrides': {'cpu': 2, 'memory_mb': 2048, 'disk_gb': 20},
    'access': {'cloud_init_user': 'ubuntu', 'ssh_public_key': 'REPLACE_WITH_YOUR_SSH_PUBLIC_KEY', 'password_login': False},
    'power_policy': 'stopped',
}
