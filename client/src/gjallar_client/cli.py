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
    return app.login(read("Gjallar 로그인 계정: "), password("Gjallar 비밀번호: "), name)


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


def parser():
    result = argparse.ArgumentParser(description="Gjallar 서버 연결·조회·설치")
    result.add_argument("--config-dir", type=Path, default=Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "gjallar")
    result.add_argument("--session-mode", choices=["keyring", "memory"], default="keyring")
    commands = result.add_subparsers(dest="command")
    connect = commands.add_parser("connect", help="기존 Gjallar 서버 연결 저장")
    connect.add_argument("name")
    connect.add_argument("origin")
    connect.add_argument("--ca-file")
    connect.add_argument("--cookie-name", default="gjallar_session")
    connection = commands.add_parser("connection")
    connection.add_argument("action", choices=["list", "use", "status"])
    connection.add_argument("name", nargs="?")
    for name in ("login", "logout", "status"):
        command = commands.add_parser(name)
        command.add_argument("--connection")
    for name in ("nodes", "vms", "templates", "tui"):
        commands.add_parser(name)
    setup = commands.add_parser("proxmox-setup", help="관리자용 Proxmox 로그인·권한 계획·연결 등록")
    setup.add_argument("--resume", help="기존 등록 ID로 상태 확인·재개")
    setup.add_argument("--list", action="store_true", help="내 등록 ID·단계 조회")
    install = commands.add_parser("bootstrap", help="로컬 신규 설치 또는 기존 설치 재개·시작")
    install.add_argument("--install-dir", type=Path, default=Path.home() / ".local/share/gjallar")
    install.add_argument("--image")
    install.add_argument("--port", type=int, default=8000)
    service = commands.add_parser("service", help="TUI 종료와 별개인 로컬 서비스 관리")
    service.add_argument("action", choices=["start", "status", "stop"])
    service.add_argument("--install-dir", type=Path, default=Path.home() / ".local/share/gjallar")
    upgrade = commands.add_parser("upgrade", help="schema가 같은 이미지로만 명시적 업그레이드")
    upgrade.add_argument("--install-dir", type=Path, default=Path.home() / ".local/share/gjallar")
    upgrade.add_argument("--image", required=True)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        connections = Connections(args.config_dir)
        if args.command == "connect":
            connections.add(args.name, args.origin, args.cookie_name, args.ca_file)
            result = {"ok": True, "message": "연결을 저장했습니다. login --connection으로 로그인하세요."}
        elif args.command == "connection" and args.action == "list":
            result = {"ok": True, **connections.read()}
        elif args.command in {"service", "upgrade"}:
            from .bootstrap import Bootstrap
            bootstrap = Bootstrap(args.install_dir)
            result = bootstrap.service(args.action) if args.command == "service" else bootstrap.upgrade(args.image)
        else:
            sessions = MemoryStore() if args.session_mode == "memory" else KeyringStore()
            app = Application(connections, sessions)
            if args.command in {None, "tui"}:
                return tui.run(app, password=secure_password, local_start=local_start)
            if args.session_mode == "memory":
                print("process-memory 모드: 명령 종료 후 session을 보관하지 않습니다. 연속 사용은 tui를 실행하세요.", file=sys.stderr)
            if args.command == "bootstrap":
                from .bootstrap import Bootstrap
                result = Bootstrap(args.install_dir).install(image=args.image, port=args.port, administrator=administrator)
                print(f'웹 접속: {result["url"]}', file=sys.stderr)
                result["login"] = login_local(app, result)
                result["observation"] = app.read("connection")
            elif args.command == "login":
                result = app.login(prompt("Gjallar 계정: "), secure_password("비밀번호: "), args.connection)
            elif args.command == "proxmox-setup":
                from .proxmox_setup import wizard
                result = app.proxmox_setup("list") if args.list else wizard(app, read=prompt, password=secure_password,
                                output=lambda message: print(message, file=sys.stderr), attempt_id=args.resume)
            elif args.command == "logout":
                result = app.logout(args.connection)
            elif args.command == "status":
                result = app.status(args.connection)
            elif args.command == "connection":
                if args.action == "use":
                    if not args.name:
                        raise ClientError("MISSING_NAME", "선택할 연결 별칭이 필요합니다.", 2)
                    result = app.use(args.name)
                else:
                    result = app.read("connection")
            else:
                result = app.read(args.command)
        print(json.dumps(result, ensure_ascii=True))
        return result.get("exit_code", 0)
    except ClientError as exc:
        print(json.dumps(exc.output(), ensure_ascii=True))
        return exc.exit_code
    except (KeyboardInterrupt, EOFError):
        print(json.dumps({"ok": False, "error": {"code": "INTERRUPTED", "message": "작업이 중단되었습니다."}}))
        return 130
    except OSError:
        print(json.dumps(ClientError("LOCAL_IO_FAILED", "로컬 파일 또는 입력을 사용할 수 없습니다.").output()))
        return 7


if __name__ == "__main__":
    raise SystemExit(main())
