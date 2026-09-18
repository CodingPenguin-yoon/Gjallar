"""Curses rendering and keyboard input; no API, credentials, or persistence."""
import curses
import json
import os
import sys
import unicodedata

from .errors import ClientError
from .tui import Cancelled


def safe(value):
    """Keep Korean readable without allowing terminal or bidi control sequences."""
    return "".join(c if unicodedata.category(c)[0] != "C" else f"\\u{ord(c):04x}" for c in str(value))


def width(value):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in value)


def fit(value, size):
    result = ""
    for char in safe(value):
        if width(result + char) > size:
            break
        result += char
    return result


def lines(value, size):
    result = []
    for line in str(value).splitlines() or [""]:
        remaining = safe(line)
        while width(remaining) > size:
            part = fit(remaining, size)
            if not part:
                result.append("?")
                remaining = remaining[1:]
                continue
            result.append(part)
            remaining = remaining[len(part):]
        result.append(remaining)
    return result


def pretty(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return value
    return json.dumps(value, ensure_ascii=False, indent=2)


class Screen:
    def __init__(self, screen):
        self.screen = screen
        self.nav = 0
        self.focus = "content"
        self.row = 0
        self.query = ""
        self.colors = curses.has_colors()
        if self.colors:
            curses.start_color()
            curses.use_default_colors()
        self.screen.keypad(True)
        self.screen.bkgd(" ", curses.A_NORMAL)

    def color(self, pair):
        # Respect the terminal's light/dark theme; emphasis never dims the text.
        return curses.A_BOLD if pair == 2 else curses.A_NORMAL

    def put(self, y, x, text, attr=0, limit=None):
        height, cols = self.screen.getmaxyx()
        if not 0 <= y < height or not 0 <= x < cols - 1:
            return
        self.screen.addstr(y, x, fit(text, min(cols - x - 1, limit if limit is not None else cols)), attr)

    def frame(self, title, footer):
        self.screen.erase()
        height, cols = self.screen.getmaxyx()
        self.put(0, 2, "›_ Gjallar", curses.A_BOLD)
        self.put(0, 15, "·  " + title)
        self.put(height - 1, 2, footer, self.color(1))
        return height, cols

    def key(self):
        return self.screen.get_wch()

    def busy(self, message):
        self.frame("작업 중", "서버 응답을 기다리는 중 · 실행 요청은 자동 재전송하지 않습니다")
        self.put(3, 3, message, curses.A_BOLD)
        self.screen.refresh()

    def prompt(self, message, secret=False):
        value = ""
        while True:
            height, cols = self.frame("입력", "Enter 계속  ·  Esc 취소  ·  Backspace 지우기  ·  Ctrl+U 전체 지우기")
            question = lines(message, max(1, cols - 6))[:max(1, height - 7)]
            for i, line in enumerate(question):
                self.put(2 + i, 3, line, curses.A_BOLD)
            visible = "*" * len(value) if secret else safe(value)
            while width(visible) > max(1, cols - 9):
                visible = visible[1:]
            input_row = min(height - 4, 3 + len(question))
            self.put(input_row, 3, "❯ " + visible + "▏")
            self.screen.refresh()
            key = self.key()
            if key in ("\n", "\r", curses.KEY_ENTER):
                self.busy("입력을 처리하고 있습니다…")
                return value
            if key == "\x1b":
                raise Cancelled()
            if key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                value = value[:-1]
            elif key == "\x15":
                value = ""
            elif isinstance(key, str) and key.isprintable():
                value += key

    def view(self, title, value):
        offset = 0
        while True:
            height, cols = self.frame(title, "↑↓ 스크롤  ·  PgUp/PgDn 페이지  ·  Enter 돌아가기  ·  Esc 취소")
            content = lines(value, max(1, cols - 6))
            count = max(1, height - 5)
            offset = max(0, min(offset, len(content) - count))
            for i, line in enumerate(content[offset:offset + count]):
                self.put(2 + i, 3, line)
            self.put(height - 3, 3, f"{offset + 1}–{min(offset + count, len(content))} / {len(content)}", self.color(3))
            self.screen.refresh()
            key = self.key()
            if key in ("\n", "\r", curses.KEY_ENTER):
                return
            if key == "\x1b":
                raise Cancelled()
            if key in (curses.KEY_DOWN, "j"):
                offset += 1
            elif key in (curses.KEY_UP, "k"):
                offset -= 1
            elif key == curses.KEY_NPAGE:
                offset += count
            elif key == curses.KEY_PPAGE:
                offset -= count

    def output(self, value):
        self.view("작업 결과 · 내용을 확인하고 계속하세요", pretty(value))
        self.busy("다음 단계를 준비하고 있습니다…")

    def choose(self, title, options):
        selected = 0
        while True:
            height, cols = self.frame(title, "↑↓ 선택  ·  Enter 확인  ·  Esc 취소")
            count = max(1, height - 5)
            start = max(0, selected - count + 1)
            for i, option in enumerate(options[start:start + count], start):
                self.put(2 + i - start, 3, ("❯ " if i == selected else "  ") + option,
                         self.color(2) if i == selected else 0)
            self.screen.refresh()
            key = self.key()
            if key in ("\n", "\r", curses.KEY_ENTER):
                return selected
            if key == "\x1b":
                raise Cancelled()
            if key in (curses.KEY_DOWN, "j"):
                selected = min(len(options) - 1, selected + 1)
            elif key in (curses.KEY_UP, "k"):
                selected = max(0, selected - 1)

    def next_action(self, controller):
        shortcuts = {"l": "login", "a": "add", "s": "switch", "r": "refresh", "p": "setup", "o": "logout"}
        while True:
            height, cols = self.frame("운영 콘솔", "↑↓ 선택   Enter 열기   Tab 패널   / 검색   ? 도움말   q 종료")
            if height < 20 or cols < 76:
                self.put(3, 2, "터미널을 76열 × 20행 이상으로 넓혀주세요.")
                self.screen.refresh()
                if self.key() == "q":
                    return "quit"
                continue
            data = controller.app.connections.read()
            selected = data["selected"]
            identity = controller.identity or {}
            account = identity.get("user", {}).get("username", "로그인 필요")
            mode = "메모리 session" if controller.app.sessions.mode == "memory" else "OS keyring"
            self.put(2, 2, f"{selected or '연결된 서버 없음'}   /   {account}   /   {mode}")
            self.put(3, 2, data["connections"].get(selected, {}).get("origin", "로컬 설치 또는 기존 서버 연결로 시작하세요."))
            for i, (_, title) in enumerate(controller.sections):
                active = self.focus == "nav" and i == self.nav
                self.put(6 + i * 2, 2, ("❯ " if active else "  ") + title, self.color(2) if active else self.color(1), 20)
            self.put(5, 26, dict(controller.sections)[controller.section], curses.A_BOLD)
            entries = self.entries(controller)
            if self.query and controller.section != "home":
                entries = [entry for entry in entries if self.query.casefold() in pretty(entry[1]).casefold()]
            self.row = min(self.row, max(0, len(entries) - 1))
            self.put(6, 26, f"{len(entries)}개 항목   / {self.query}" if controller.section != "home" else "시작할 작업을 선택하세요.", self.color(3))
            stride = 2 if controller.section == "home" else 1
            count = max(1, (height - 11) // stride)
            start = max(0, self.row - count + 1)
            for i, (label, _) in enumerate(entries[start:start + count], start):
                self.put(8 + (i - start) * stride, 26, ("❯ " if self.focus == "content" and i == self.row else "  ") + label,
                         self.color(2) if self.focus == "content" and i == self.row else 0)
            if not entries:
                self.put(8, 26, "표시할 항목이 없습니다. 로그인·조회 상태를 확인하세요.")
            self.put(height - 3, 2, controller.message, self.color(3))
            self.screen.refresh()
            key = self.key()
            if key == "q":
                return "quit"
            if key == "?":
                self.view("키보드 도움말", "Tab / ←→  탐색·목록 패널 전환\n↑↓ / j k  항목 선택\nEnter  선택한 메뉴·상세 열기\n/  현재 목록 검색\nr  현재 화면 새로고침\nm  조회 시점·누락 등 응답 메타데이터\nl  저장된 서버에 로그인\na  서버 연결 추가\ns  저장된 session으로 서버 전환\np  Proxmox 등록·재개\no  로그아웃\nEsc  입력 취소 / 탐색으로 이동\nq  TUI 종료 (서비스는 계속 실행)")
                continue
            if key == "m":
                self.view("조회 메타데이터", pretty((controller.result or {}).get("meta", {})))
                continue
            if key in shortcuts:
                self.query = ""
                return shortcuts[key]
            if key == "/":
                self.query = self.prompt("현재 목록 검색 · 빈 값으로 해제")
                self.row = 0
            elif key in ("\t", curses.KEY_LEFT, curses.KEY_RIGHT):
                self.focus = "content" if self.focus == "nav" else "nav"
            elif key in (curses.KEY_UP, "k", curses.KEY_DOWN, "j"):
                delta = 1 if key in (curses.KEY_DOWN, "j") else -1
                if self.focus == "nav":
                    self.nav = max(0, min(len(controller.sections) - 1, self.nav + delta))
                else:
                    self.row = max(0, min(len(entries) - 1, self.row + delta))
            elif key in ("\n", "\r", curses.KEY_ENTER):
                if self.focus == "nav":
                    self.row, self.query, self.focus = 0, "", "content"
                    return controller.sections[self.nav][0]
                if entries:
                    value = entries[self.row][1]
                    if controller.section == "home":
                        return value
                    if controller.section == "connections":
                        controller.login(value["name"])
                    else:
                        self.view("항목 상세", pretty(value))
            elif key == "\x1b":
                self.focus, self.query = "nav", ""

    @staticmethod
    def entries(controller):
        if controller.section == "home":
            return [("기존 서버에 연결", "add"), ("저장된 서버에 로그인", "login"),
                    ("이 컴퓨터에 Gjallar 설치·실행", "install"),
                    ("Proxmox 연결 등록·재개", "setup"), ("저장된 session으로 서버 전환", "switch"),
                    ("로그아웃", "logout")]
        result = controller.result
        if result is None:
            return []
        if controller.section == "connections":
            return [(f'{name}   {profile["origin"]}', {"name": name, **profile}) for name, profile in result["connections"].items()]
        data = result.get("data", {})
        if not isinstance(data, list):
            return [(str(key) + "  " + pretty(value), {key: value}) for key, value in data.items()]
        entries = []
        for item in data:
            if isinstance(item, dict):
                keys = [key for key in ("vmid", "name", "node_id", "status", "template_id") if key in item]
                label = "  │  ".join(str(item[key]) for key in keys) if keys else pretty(item)
            else:
                label = str(item)
            entries.append((label, item))
        return entries


def run_screen(callback):
    if not sys.stdin.isatty() or not sys.stdout.isatty() or os.getenv("TERM", "dumb") == "dumb":
        raise ClientError("TERMINAL_REQUIRED", "TUI는 대화형 터미널에서 실행하세요. 자동화에는 CLI 명령을 사용하세요.", 2)
    try:
        return curses.wrapper(lambda screen: callback(Screen(screen)))
    except KeyboardInterrupt:
        return 0
    except curses.error:
        raise ClientError("TERMINAL_UNAVAILABLE", "터미널 화면을 사용할 수 없습니다. TERM 설정과 화면 크기를 확인하세요.", 2) from None
