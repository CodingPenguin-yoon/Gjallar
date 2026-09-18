import curses

import pytest

from gjallar_client.terminal import Screen, fit, lines, pretty, safe, width
from gjallar_client.tui import Cancelled, TerminalController
from gjallar_client.errors import ClientError
from test_client import PASSWORD, setup


class Window:
    def __init__(self, keys, height=24, cols=100):
        self.keys = iter(keys)
        self.height, self.cols = height, cols
        self.writes = []

    def getmaxyx(self):
        return self.height, self.cols

    def addstr(self, y, x, text, attr):
        assert 0 <= y < self.height
        assert x + width(text) < self.cols
        self.writes.append(text)

    def get_wch(self):
        return next(self.keys)

    def erase(self):
        pass

    def refresh(self):
        pass

    def keypad(self, enabled):
        pass

    def bkgd(self, char, attr):
        pass


@pytest.fixture
def screen(monkeypatch):
    monkeypatch.setattr(curses, 'has_colors', lambda: False)
    return lambda keys, **kwargs: Screen(Window(keys, **kwargs))


def test_readable_korean_and_terminal_controls():
    assert safe('로그인 실패') == '로그인 실패'
    assert safe('\x1b[2J\u202e') == '\\u001b[2J\\u202e'
    assert fit('한글abc', 5) == '한글a'
    assert lines('한글', 1) == ['?', '?', '']
    assert pretty('{"message":"\\uc624\\ub958"}') == '{\n  "message": "오류"\n}'


def test_password_is_masked_and_cancellation_submits_nothing(screen):
    ui = screen([*PASSWORD, '\n'])
    assert ui.prompt('비밀번호', secret=True) == PASSWORD
    output = '\n'.join(ui.screen.writes)
    assert PASSWORD not in output and '***' in output
    ui = screen(['x', '\x1b'])
    with pytest.raises(Cancelled):
        ui.prompt('비밀번호', secret=True)


def test_korean_input_edit_and_connection_picker(screen):
    ui = screen(['한', '글', '\x7f', '국', '\n'])
    assert ui.prompt('계정') == '한국'
    ui = screen([curses.KEY_DOWN, '\n'])
    assert ui.choose('서버 선택', ['one', 'two']) == 1


def test_narrow_terminal_can_quit_without_render_error(screen, setup):
    app, *_ = setup
    ui = screen(['q'], height=8, cols=25)
    assert TerminalController(app, ui).run() == 0


def test_escape_dismisses_error_without_ending_tui(screen, setup):
    app, config, *_ = setup
    ui = screen(['l', '\x1b', 'q'])
    config.path.unlink(missing_ok=True)
    assert TerminalController(app, ui).run() == 0


def test_search_open_details_then_quit(screen, setup):
    app, *_ = setup
    ui = screen(['/', *'beta', '\n', '\n', '\n', 'q'])
    controller = TerminalController(app, ui)
    controller.section = 'vms'
    controller.result = {'data': [{'vmid': 1, 'name': 'alpha'}, {'vmid': 2, 'name': 'beta'}]}
    assert controller.run() == 0
    assert any('"name": "beta"' in text for text in ui.screen.writes)
    assert not any('"name": "alpha"' in text for text in ui.screen.writes)


def test_login_failure_can_retry_saved_connection(screen, setup, monkeypatch):
    app, config, _, server = setup
    # The connection remains selectable even without an active selected profile.
    original = app.login
    attempts = []

    def login(username, password, name):
        attempts.append(username)
        if len(attempts) == 1:
            raise ClientError('LOGIN_FAILED', '로그인 정보가 틀립니다.', 3)
        return original(username, password, name)

    monkeypatch.setattr(app, 'login', login)
    ui = screen(['l', '\n', *'wrong', '\n', *PASSWORD, '\n', '\n',
                 'l', '\n', *'admin', '\n', *PASSWORD, '\n', 'q'])
    controller = TerminalController(app, ui)
    assert controller.run() == 0
    assert config.read()['selected'] == 'one'
    assert controller.identity['user']['username'] == 'admin'
    assert attempts == ['wrong', 'admin']
    assert not any(r.url.path.endswith('/logout') for r in server.calls)
