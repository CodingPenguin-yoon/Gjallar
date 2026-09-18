"""Full-screen terminal presentation over the shared synchronous application."""
import json

from .errors import ClientError


def show(value, output=print):
    output(json.dumps(value, ensure_ascii=True, indent=2))


class Cancelled(Exception):
    """Leave a dialog without submitting its current input."""


class TerminalController:
    sections = [("home", "시작"), ("vms", "가상 머신"), ("nodes", "노드"),
                ("templates", "템플릿"), ("connection", "연결 상태"), ("connections", "서버 연결")]

    def __init__(self, app, ui, local_start=None):
        self.app, self.ui, self.local_start = app, ui, local_start
        self.section = "home"
        self.identity = None
        self.result = None
        self.message = "서버에 로그인하면 자원을 조회할 수 있습니다."

    def refresh(self):
        self.result = None
        if self.section == "connections":
            self.result = self.app.connections.read()
        elif self.section != "home":
            self.ui.busy("서버에서 상태를 조회하고 있습니다…")
            self.result = self.app.read(self.section)
            self.identity = self.result
            self.message = self.result.get("warning") or "조회 완료 · r 키로 새로고침"

    def choose_connection(self):
        data = self.app.connections.read()
        names = list(data["connections"])
        if not names:
            raise ClientError("NO_CONNECTION", "저장된 서버가 없습니다. a 키로 서버를 추가하거나 시작 화면에서 로컬 설치를 선택하세요.", 2)
        index = self.ui.choose("로그인할 Gjallar 서버", [f'{name}   {data["connections"][name]["origin"]}' for name in names])
        return names[index]

    def login(self, name=None):
        name = name or self.choose_connection()
        username = self.ui.prompt(f"Gjallar 계정 · {name}\n설치할 때 만든 관리자 계정을 입력하세요 (예: admin).")
        password = self.ui.prompt("Gjallar 비밀번호", secret=True)
        self.ui.busy("로그인 중…")
        self.identity = self.app.login(username, password, name)
        self.result = None
        self.message = "로그인했습니다. 왼쪽에서 가상 머신·노드·템플릿을 선택하세요."

    def action(self, action):
        if action in dict(self.sections):
            self.section = action
            self.refresh()
        elif action == "refresh":
            self.refresh()
        elif action == "login":
            self.login()
        elif action == "add":
            name = self.ui.prompt("연결 별칭\n서버를 구분할 이름입니다. 계정명과 별개입니다 (예: home).")
            origin = self.ui.prompt("Gjallar 서버 주소\n예: https://gjallar.example.com 또는 http://127.0.0.1:8000")
            self.app.connections.add(name, origin)
            self.login(name)
        elif action == "switch":
            name = self.choose_connection()
            self.ui.busy("서버 session 확인 중…")
            self.identity = self.app.use(name)
            self.result = None
            self.message = "서버 연결을 전환했습니다."
        elif action == "logout":
            self.ui.busy("로그아웃 중…")
            self.app.logout()
            self.identity = self.result = None
            self.message = "로그아웃했습니다. l 키로 다시 로그인하세요."
        elif action == "install":
            self.ui.view("로컬 Gjallar 설치", "Docker 앱·DB를 기동합니다. 새 설치는 관리자 계정을 만듭니다.\n설치 경로와 이미지를 확인한 뒤 진행하세요.\nTUI를 종료해도 서비스는 계속 실행됩니다.")
            if self.local_start:
                self.local_start(self.app, self.ui.prompt,
                                 lambda message: self.ui.prompt(message, secret=True), self.ui.output)
                self.identity = self.app.status()
                self.message = "로컬 서버 설치·로그인을 완료했습니다."
        elif action == "setup":
            from .proxmox_setup import wizard
            self.ui.output(self.app.proxmox_setup("list"))
            attempt = self.ui.prompt("등록 ID\n새 Proxmox 등록은 빈 값으로 계속하세요.") or None
            result = wizard(self.app, read=self.ui.prompt,
                            password=lambda message: self.ui.prompt(message, secret=True),
                            output=self.ui.output, attempt_id=attempt)
            self.ui.output(result)

    def run(self):
        while True:
            try:
                action = self.ui.next_action(self)
                if action == "quit":
                    return 0
                self.action(action)
            except Cancelled:
                self.message = "입력을 취소했습니다. 이미 완료된 단계는 유지됩니다."
            except ClientError as exc:
                # Do not retain another server's inventory or an expired identity.
                self.result = None
                if exc.exit_code == 3:
                    self.identity = None
                self.message = f"{exc.code} · {exc.message}"
                self.error("작업을 완료하지 못했습니다", self.message)
            except OSError:
                self.result = None
                self.error("로컬 입출력 오류", "파일 또는 입력을 사용할 수 없습니다. 경로와 권한을 확인하세요.")

    def error(self, title, message):
        try:
            self.ui.view(title, message)
        except Cancelled:
            return


def run(app, *, local_start=None):
    from .terminal import run_screen
    return run_screen(lambda ui: TerminalController(app, ui, local_start).run())
