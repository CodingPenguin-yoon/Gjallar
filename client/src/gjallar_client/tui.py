"""Minimal synchronous terminal UI sharing the command application."""
import getpass
import json

from .errors import ClientError


def show(value, output=print):
    # JSON escaping prevents control sequences from remote names reaching the terminal.
    output(json.dumps(value, ensure_ascii=True, indent=2))


def run(app, *, read=input, password=getpass.getpass, output=print, local_start=None):
    output("Gjallar · 이 메뉴 종료는 Gjallar 서비스를 중지하지 않습니다.")
    if app.sessions.mode == "memory":
        output("process-memory 모드: session은 이 프로세스에서만 유지됩니다.")
    while True:
        try:
            selected = app.connections.read()["selected"]
            output(f"현재 연결: {selected or '없음'}")
            if selected:
                try:
                    show(app.status(), output)
                except ClientError as exc:
                    show(exc.output(), output)
            output("1 이 컴퓨터에서 Gjallar 실행 | 2 기존 Gjallar 서버에 연결 | 3 저장된 연결 선택")
            output("4 로그인 | 5 상태 | 6 노드 | 7 VM | 8 템플릿 | 9 연결 관찰 | 0 logout | q TUI 종료")
            choice = read("선택: ").strip()
            if choice == "q":
                return 0
            if choice == "1":
                if local_start:
                    local_start(app, read, password, output)
                else:
                    output("로컬 bootstrap은 아직 제공되지 않습니다.")
            elif choice == "2":
                name, origin = read("연결 별칭: "), read("Gjallar 서버 주소: ")
                app.connections.add(name, origin)
                show(app.login(read("Gjallar 계정: "), password("비밀번호: "), name), output)
            elif choice == "3":
                show(app.connections.read(), output)
                show(app.use(read("선택할 별칭: ")), output)
            elif choice == "4":
                show(app.login(read("Gjallar 계정: "), password("비밀번호: "), read("연결 별칭 (현재 연결은 Enter): ") or None), output)
            elif choice == "5":
                show(app.status(), output)
            elif choice in {"6", "7", "8", "9"}:
                show(app.read({"6": "nodes", "7": "vms", "8": "templates", "9": "connection"}[choice]), output)
            elif choice == "0":
                show(app.logout(), output)
        except ClientError as exc:
            show(exc.output(), output)
        except (EOFError, KeyboardInterrupt):
            output("TUI를 종료합니다. Gjallar 서비스는 계속 실행됩니다.")
            return 0
