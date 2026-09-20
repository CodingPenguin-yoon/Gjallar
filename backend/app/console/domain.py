"""Console target and credential response validation, without persistence."""
import re
from dataclasses import dataclass, field


class ConsoleError(RuntimeError):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code, self.status = code, status


def validate_target(node_id, vmid):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', node_id) or type(vmid) is not int or not 100 <= vmid <= 999999999:
        raise ConsoleError('CONSOLE_INVALID_TARGET', '노드·VMID를 확인하세요.', 422)


def review_vm(config, status, permissions, *, node_id, vmid):
    if not {'VM.Audit', 'VM.Console'} <= set(permissions):
        raise ConsoleError('CONSOLE_PERMISSION_DENIED', '선택한 VM의 Audit·Console 권한을 확인하세요.', 403)
    if status.get('status') != 'running' or str(config.get('template', 0)) != '0':
        raise ConsoleError('CONSOLE_NOT_RUNNING', '실행 중인 일반 VM만 화면 콘솔에 연결할 수 있습니다. 자동 시작하지 않습니다.')
    vga = str(config.get('vga', 'std')).split(',')[0].removeprefix('type=')
    if vga == 'none' or vga.startswith('serial'):
        raise ConsoleError('CONSOLE_DISPLAY_UNSUPPORTED', '화면 장치가 필요합니다. serial-only 콘솔은 첫 지원 범위가 아닙니다.')
    return {'target': {'node_id': node_id, 'vmid': vmid}, 'name': str(config.get('name', vmid)),
            'status': 'running', 'max_duration_seconds': 900,
            'warnings': ['게스트 화면과 키보드·마우스 입력에 접근합니다. 입력은 게스트 상태를 바꿀 수 있습니다.',
                         '15분 뒤 연결을 종료합니다. 다시 접속하려면 직접 연결하세요. 클립보드는 자동 공유하지 않습니다.']}


@dataclass(frozen=True)
class ProxyTicket:
    port: int
    ticket: str = field(repr=False)
    password: str = field(repr=False)

    @classmethod
    def parse(cls, data):
        if not isinstance(data, dict):
            raise ConsoleError('CONSOLE_PROXY_INVALID', 'PVE 콘솔 응답을 확인할 수 없습니다.', 502)
        port, ticket = data.get('port'), data.get('ticket')
        # PVE may encode the allocated port as a decimal string.
        if isinstance(port, str) and re.fullmatch(r'59[0-9]{2}', port):
            port = int(port)
        # PVE 9 provides password separately; older versions use the ticket as the RFB password.
        password = data.get('password', ticket)
        if (type(port) is not int or not 5900 <= port <= 5999
                or not isinstance(ticket, str) or not 1 <= len(ticket) <= 512
                or not isinstance(password, str) or not 1 <= len(password) <= 512
                or any(not 33 <= ord(char) <= 126 for char in ticket + password)):
            raise ConsoleError('CONSOLE_PROXY_INVALID', 'PVE 콘솔 응답을 확인할 수 없습니다.', 502)
        return cls(port=port, ticket=ticket, password=password)
