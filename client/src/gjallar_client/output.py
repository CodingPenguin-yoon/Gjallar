"""Human terminal output and stable JSON envelopes without terminal controls."""
import json
import unicodedata


def text(value):
    value = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    return ''.join(c if unicodedata.category(c)[0] != 'C' else f'\\u{ord(c):04x}' for c in value)


HINTS = {
    'NO_CONNECTION': 'gjallar connection list로 저장된 서버를 확인하고 gjallar login --connection <별칭>을 실행하세요.',
    'LOGIN_FAILED': '설치 시 만든 Gjallar 계정(예: admin)으로 다시 로그인하세요. Proxmox 계정과 다릅니다.',
    'SESSION_EXPIRED': 'gjallar login --connection <별칭>으로 로그인한 뒤 원래 명령을 다시 실행하세요.',
    'KEYRING_UNAVAILABLE': 'OS keyring 잠금을 확인하세요. 비저장 세션은 gjallar --session-mode memory shell을 사용하세요.',
    'COMMUNICATION_FAILED': '서버 주소·실행 상태를 확인하세요. 로컬 설치는 gjallar service status로 확인할 수 있습니다.',
    'PROXMOX_INVENTORY_UNCONFIGURED': 'Gjallar 관리자로 gjallar proxmox-setup을 실행해 Proxmox 연결을 등록하세요.',
    'PROXMOX_INVENTORY_DEGRADED': 'gjallar connection status에서 관찰 실패 원인을 확인하세요.',
}


def cell_width(value):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in value)


def table(rows):
    if not rows:
        return '조회된 항목이 없습니다.'
    if not all(isinstance(row, dict) for row in rows):
        return '\n'.join(text(row) for row in rows)
    preferred = ('selected', 'name', 'Service', 'State', 'Health', 'vmid', 'node_id', 'status', 'state', 'role', 'origin',
                 'operation_id', 'operation_type', 'target_id', 'observed_at')
    keys = [key for key in preferred if any(key in row for row in rows)]
    if not keys:
        return json.dumps(rows, ensure_ascii=True, indent=2)
    cells = [[text(row.get(key, '—')) for key in keys] for row in rows]
    sizes = [max(cell_width(key), *(cell_width(row[i]) for row in cells)) for i, key in enumerate(keys)]
    return '\n'.join('  '.join(value + ' ' * (sizes[i] - cell_width(value)) for i, value in enumerate(row)).rstrip()
                     for row in [list(keys), *cells])


def human(result):
    if 'error' in result:
        error = result['error']
        message = f"오류 [{text(error['code'])}] {text(error['message'])}"
        if error['code'] in HINTS:
            message += '\n다음: ' + HINTS[error['code']]
        return message
    output = []
    if result.get('server'):
        output.append(f"서버  {text(result.get('connection', ''))}  {text(result['server'])}")
    if result.get('user'):
        user = result['user']
        output.append(f"계정  {text(user.get('username'))} ({text(user.get('role'))})")
    if result.get('message'):
        output.append(text(result['message']))
    if 'services' in result:
        output.append(table(result['services']))
    if 'connections' in result:
        output.append(table([{'selected': '*' if name == result.get('selected') else '', 'name': name,
                              'origin': profile['origin']} for name, profile in result['connections'].items()]))
    if 'data' in result:
        data = result['data']
        if isinstance(data, list):
            output.append(table(data))
        elif isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    output.append(text(key) + ':')
                    output.extend('  ' + text(line) for line in json.dumps(value, ensure_ascii=False, indent=2).splitlines())
                else:
                    output.append(f'{text(key)}: {text(value)}')
        else:
            output.append(text(data))
    for key in ('installation_state', 'state', 'url', 'status', 'warning', 'next', 'review_file'):
        if result.get(key):
            output.append(f'{key}: {text(result[key])}')
    if result.get('meta'):
        output.append('관찰: ' + text(result['meta']))
    if not output:
        output.append('완료' if result.get('ok') else '요청을 완료하지 못했습니다.')
    return '\n'.join(output)


def emit(result, *, as_json, stream):
    print(json.dumps(result, ensure_ascii=True) if as_json else human(result), file=stream)
