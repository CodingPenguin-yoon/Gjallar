"""CLI entry point; secrets are prompted, never accepted as arguments."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import warnings

from .application import Application
from .connections import Connections
from .errors import ClientError
from .sessions import KeyringStore, MemoryStore
from . import tui


def prompt(message):
    print(message, end="", file=sys.stderr, flush=True)
    return input()


def secure_password(message):
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(message)
        except getpass.GetPassWarning:
            raise ClientError("SECURE_INPUT_REQUIRED", "비표시 비밀번호 입력이 가능한 터미널에서 실행하세요.", 2) from None


def administrator(read=prompt, password=secure_password):
    username = read("최초 Gjallar 관리자 계정: ")
    first = password("새 비밀번호: ")
    if not first or first != password("비밀번호 확인: "):
        raise ClientError("PASSWORD_MISMATCH", "비밀번호가 비었거나 확인 값이 다릅니다. 같은 설치 경로로 다시 실행하세요.", 2)
    return {"username": username, "password": first}


def login_local(app, result, read=prompt, password=secure_password):
    origin = result["url"]
    name = "local-" + origin.rsplit(":", 1)[-1]
    profiles = app.connections.read()["connections"]
    if name not in profiles:
        app.connections.add(name, origin)
    elif profiles[name]["origin"] != origin:
        raise ClientError("CONNECTION_CONFLICT", "로컬 연결 별칭이 다른 서버에 사용 중입니다. 새 별칭으로 직접 연결하세요.")
    return app.login(read("Gjallar 로그인 계정 (설치 시 만든 계정, 예: admin): "), password("Gjallar 비밀번호: "), name)


def local_start(app, read, password, output):
    from .bootstrap import Bootstrap
    path = read("설치 경로 (Enter: ~/.local/share/gjallar): ") or str(Path.home() / ".local/share/gjallar")
    port = read("loopback port (Enter: 8000): ") or "8000"
    if not port.isdigit():
        raise ClientError("INVALID_PORT", "숫자 port를 입력하세요.", 2)
    image = read("Gjallar 이미지 (Enter: 기존 이미지 유지 / 신규 gjallar:local): ") or None
    result = Bootstrap(Path(path)).install(image=image, port=int(port), administrator=lambda: administrator(read, password))
    tui.show(result, output)
    tui.show(login_local(app, result, read, password), output)
    tui.show(app.read("connection"), output)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ClientError("INVALID_ARGUMENT", "명령 또는 인자가 올바르지 않습니다. 해당 명령의 --help를 확인하세요.", 2)


def positive_id(value):
    try:
        number = int(value)
        if number < 100 or number > 999999999:
            raise ValueError
        return number
    except ValueError:
        raise argparse.ArgumentTypeError("VMID는 100~999999999 정수입니다.") from None


def parser():
    common = Parser(add_help=False, argument_default=argparse.SUPPRESS)
    common.add_argument("--config-dir", type=Path, help="클라이언트 연결 설정 디렉터리")
    common.add_argument("--session-mode", choices=["keyring", "memory"], help="기본 keyring; memory는 shell에서 연속 사용")
    common.add_argument("--connection", help="이번 명령에 사용할 저장된 서버 별칭")
    output = common.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="자동화용 JSON 한 개 출력")
    output.add_argument("--human", action="store_true", help="파이프에서도 사람이 읽는 출력")
    result = Parser(description="Gjallar · 설치, 연결, VM 운영", parents=[common],
                    epilog="시작: connect → login → connection status → vms. 전체 화면은 tui, 비저장 연속 사용은 shell.")
    commands = result.add_subparsers(dest="command")
    def add(group, name, **kwargs):
        return group.add_parser(name, parents=[common], **kwargs)
    connect = add(commands, "connect", help="Gjallar 서버 주소를 별칭으로 저장")
    connect.add_argument("name")
    connect.add_argument("origin")
    connect.add_argument("--ca-file")
    connect.add_argument("--cookie-name", default="gjallar_session")
    connection = add(commands, "connection", help="저장된 서버 목록·선택·Proxmox 관찰 상태")
    connection.add_argument("action", choices=["list", "use", "status"])
    connection.add_argument("name", nargs="?")
    login = add(commands, "login", help="설치 시 만든 Gjallar 계정으로 로그인")
    login.add_argument("--username", help="계정명 (비밀번호는 비표시 입력)")
    for name, help_text in [("logout", "Gjallar session 폐기"), ("status", "현재 서버·계정 확인"),
                            ("nodes", "노드 목록"), ("vms", "VM 목록"), ("templates", "템플릿 목록"),
                            ("tui", "전체 화면 TUI"), ("shell", "같은 session으로 CLI 명령 연속 실행")]:
        add(commands, name, help=help_text)
    vm = add(commands, "vm", help="VM 조회·시작·정상 종료·생성")
    actions = vm.add_subparsers(dest="action", required=True)
    add(actions, "list", help="VM 목록")
    show = add(actions, "show", help="VM 상세")
    show.add_argument("vmid", type=positive_id)
    for action, label in [("start", "VM 시작"), ("shutdown", "VM 정상 종료 (강제 종료 없음)")]:
        command = add(actions, action, help=label)
        command.add_argument("vmid", type=positive_id)
        command.add_argument("--node", required=True)
        command.add_argument("--request-id", required=True, help="한 실행 의도의 고유 ID; 응답 유실 시 보존")
        command.add_argument("--yes", action="store_true", help="표시된 대상 변경에 명시적으로 동의")
    create = add(actions, "create", help="서버 생성 계획을 검토한 뒤 별도 실행")
    stages = create.add_subparsers(dest="stage", required=True)
    add(stages, "example", help="편집할 생성 입력 JSON 예제 출력")
    plan = add(stages, "plan", help="서버에 계획 기록 (VM 변경 없음)")
    plan.add_argument("--file", type=Path, required=True, help="생성 입력 JSON")
    plan.add_argument("--request-id", required=True)
    plan.add_argument("--review-file", type=Path, required=True, help="새 검토 파일 경로 (0600, 덮어쓰기 금지)")
    execute = add(stages, "execute", help="검토 파일과 서버 승인을 검증하고 VM 생성")
    execute.add_argument("--review-file", type=Path, required=True)
    execute.add_argument("--ack-yellow", action="store_true", help="검토한 yellow 위험·IP 확인에 동의")
    execute.add_argument("--yes", action="store_true")
    operations = add(commands, "operations", help="웹과 같은 작업의 상태·결과 조회")
    queries = operations.add_subparsers(dest="action", required=True)
    listing = add(queries, "list", help="최근 작업; VM/상태로 필터")
    listing.add_argument("--vmid", type=positive_id)
    listing.add_argument("--status")
    listing.add_argument("--limit", type=int, default=50, choices=range(1,201), metavar="1..200")
    show = add(queries, "show", help="작업 결과·이벤트·복구 상태")
    show.add_argument("operation_id")
    setup = add(commands, "proxmox-setup", help="관리자용 Proxmox 연결 등록")
    setup.add_argument("--resume")
    setup.add_argument("--list", action="store_true")
    install = add(commands, "bootstrap", help="로컬 설치·시작 (로그인은 별도 login)")
    install.add_argument("--install-dir", type=Path, default=Path.home() / ".local/share/gjallar")
    install.add_argument("--image")
    install.add_argument("--port", type=int, default=8000)
    service = add(commands, "service", help="로컬 서비스 상태·시작·종료")
    service.add_argument("action", choices=["start", "status", "stop"])
    service.add_argument("--install-dir", type=Path, default=Path.home() / ".local/share/gjallar")
    upgrade = add(commands, "upgrade", help="같은 DB schema의 이미지로 업그레이드")
    upgrade.add_argument("--install-dir", type=Path, default=Path.home() / ".local/share/gjallar")
    upgrade.add_argument("--image", required=True)
    return result


def login_name(connections, requested):
    data = connections.read()
    if requested or data['selected']:
        return connections.get(requested)[0]
    names = list(data['connections'])
    if len(names) == 1:
        return names[0]
    raise ClientError('NO_CONNECTION', '로그인할 서버를 --connection으로 지정하세요. connection list에서 별칭을 확인할 수 있습니다.', 2)


def confirm_change(summary, yes):
    from .output import human
    print(human({'data': summary}), file=sys.stderr)
    if yes:
        return
    if not sys.stdin.isatty():
        raise ClientError('CONFIRMATION_REQUIRED', '대상·영향을 검토한 뒤 --yes로 실행에 동의하세요.', 2)
    if prompt('이 변경을 실행할까요? [yes/취소]: ').strip() != 'yes':
        raise ClientError('CANCELLED', '실행을 취소했습니다. 변경 요청을 보내지 않았습니다.', 2)


def shell(args, connections, sessions):
    import shlex
    if not sys.stdin.isatty():
        raise ClientError('TERMINAL_REQUIRED', 'shell은 대화형 터미널에서 실행하세요.', 2)
    print('Gjallar CLI · help 도움말 · exit 종료. 비밀번호는 로그인에서만 입력하세요.', file=sys.stderr)
    prefix = ['--config-dir', str(connections.directory), '--session-mode', args.session_mode]
    if args.connection:
        prefix += ['--connection', args.connection]
    while True:
        try:
            command = prompt('gjallar> ').strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if command in {'exit', 'quit'}:
            return 0
        if not command:
            continue
        if command == 'help':
            parser().print_help()
            continue
        try:
            argv = shlex.split(command)
        except ValueError:
            print('따옴표가 닫혔는지 확인하세요.', file=sys.stderr)
            continue
        try:
            main(prefix + argv, session_store=sessions, in_shell=True)
        except SystemExit as exc:
            if exc.code:
                print('명령 도움말을 확인하세요.', file=sys.stderr)


def execute(args, app):
    from . import workflows
    if args.command == 'login':
        name = login_name(app.connections, args.connection)
        app.connections.get(name)  # Validate before requesting credentials.
        return app.login(args.username or prompt(f'Gjallar 계정 ({name}, 예: admin): '), secure_password('비밀번호: '), name)
    if args.command == 'logout':
        return app.logout(args.connection)
    if args.command == 'status':
        return app.status(args.connection)
    if args.command == 'connection':
        if args.action == 'use':
            if not args.name:
                raise ClientError('MISSING_NAME', '선택할 연결 별칭이 필요합니다.', 2)
            return app.use(args.name)
        return app.read('connection')
    if args.command in {'nodes', 'vms', 'templates'}:
        return app.read(args.command)
    if args.command == 'operations':
        if args.action == 'show':
            return workflows.operations(app, operation_id=args.operation_id)
        return workflows.operations(app, vmid=args.vmid, status=args.status, limit=args.limit)
    if args.command == 'vm':
        if args.action == 'list':
            return app.read('vms')
        if args.action == 'show':
            return app.request(f'vms/{args.vmid}')
        if args.action in {'start', 'shutdown'}:
            return workflows.power(app, args.action, args.vmid, args.node, args.request_id,
                                   lambda value: confirm_change(value, args.yes))
        if args.stage == 'plan':
            return workflows.create_plan(app, args.file, args.request_id, args.review_file)
        return workflows.create_execute(app, args.review_file, args.ack_yellow,
                                        lambda value: confirm_change(value, args.yes))
    if args.command == 'proxmox-setup':
        from .proxmox_setup import wizard
        from .output import text
        return app.proxmox_setup('list') if args.list else wizard(
            app, read=prompt, password=secure_password,
            output=lambda message: print(text(message), file=sys.stderr), attempt_id=args.resume)
    raise ClientError('INVALID_COMMAND', '지원하지 않는 명령입니다.', 2)


def main(argv=None, *, session_store=None, in_shell=False):
    from .output import emit
    raw = list(sys.argv[1:] if argv is None else argv)
    as_json = '--json' in raw or ('--human' not in raw and not sys.stdout.isatty())
    try:
        argparser = parser()
        args = argparser.parse_args(raw)
        if args.command is None:
            argparser.print_help()
            return 0
        args.config_dir = getattr(args, 'config_dir', Path(os.getenv('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'gjallar')
        args.session_mode = getattr(args, 'session_mode', 'keyring')
        args.connection = getattr(args, 'connection', None)
        if args.command == 'tui' and args.connection:
            raise ClientError('INVALID_ARGUMENT', 'TUI에서는 화면의 저장된 서버 목록에서 연결을 선택하세요.', 2)
        if in_shell and args.command in {'shell', 'tui'}:
            raise ClientError('INVALID_COMMAND', 'shell 안에서는 CLI 명령을 사용하고 종료하려면 exit를 입력하세요.', 2)
        if in_shell and session_store is not None and args.session_mode != session_store.mode:
            raise ClientError('INVALID_SESSION_MODE', 'session 모드를 바꾸려면 shell을 종료한 뒤 다시 실행하세요.', 2)
        connections = Connections(args.config_dir)
        if args.command == 'connect':
            connections.add(args.name, args.origin, args.cookie_name, args.ca_file)
            result = {'ok': True, 'message': '서버 주소를 저장했습니다. 아직 로그인하거나 연결을 검증하지 않았습니다.',
                      'next': f'gjallar login --connection {args.name}'}
        elif args.command == 'connection' and args.action == 'list':
            result = {'ok': True, **connections.read()}
        elif args.command in {'service', 'upgrade', 'bootstrap'}:
            from .bootstrap import Bootstrap
            bootstrap = Bootstrap(args.install_dir)
            if args.command == 'bootstrap':
                result = bootstrap.install(image=args.image, port=args.port, administrator=administrator)
                name = 'local-' + result['url'].rsplit(':', 1)[-1]
                profiles = connections.read()['connections']
                if name not in profiles:
                    connections.add(name, result['url'])
                elif profiles[name]['origin'] != result['url']:
                    raise ClientError('CONNECTION_CONFLICT', '설치는 완료했지만 local 별칭이 다른 주소입니다. connect로 새 별칭을 저장하세요.', 2)
                result['next'] = f'gjallar login --connection {name} (설치 시 만든 계정)'
            else:
                result = bootstrap.service(args.action) if args.command == 'service' else bootstrap.upgrade(args.image)
        elif args.command == 'vm' and args.action == 'create' and args.stage == 'example':
            from .workflows import EXAMPLE
            print(json.dumps(EXAMPLE, ensure_ascii=True, indent=2))
            return 0
        else:
            sessions = session_store if session_store is not None else (MemoryStore() if args.session_mode == 'memory' else KeyringStore())
            app = Application(connections, sessions, connection_name=args.connection)
            if args.command == 'tui':
                return tui.run(app, local_start=local_start)
            if args.command == 'shell':
                return shell(args, connections, sessions)
            if args.session_mode == 'memory' and not in_shell:
                print('memory session은 명령 종료 시 사라집니다. 연속 사용: gjallar --session-mode memory shell', file=sys.stderr)
            result = execute(args, app)
        emit(result, as_json=as_json, stream=sys.stdout)
        return result.get('exit_code', 0)
    except ClientError as exc:
        emit(exc.output(), as_json=as_json, stream=sys.stdout if as_json else sys.stderr)
        return exc.exit_code
    except (KeyboardInterrupt, EOFError):
        emit(ClientError('INTERRUPTED', '중단됐습니다. 실행 요청을 보냈다면 Operations에서 결과를 먼저 확인하세요.', 130).output(),
             as_json=as_json, stream=sys.stdout if as_json else sys.stderr)
        return 130
    except OSError:
        emit(ClientError('LOCAL_IO_FAILED', '로컬 파일 또는 입력을 사용할 수 없습니다.').output(),
             as_json=as_json, stream=sys.stdout if as_json else sys.stderr)
        return 7


if __name__ == '__main__':
    raise SystemExit(main())
