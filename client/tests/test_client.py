import json
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from gjallar_client.api import Api
from gjallar_client.application import Application
from gjallar_client.connections import Connections, canonical_origin, file_lock
from gjallar_client.errors import ClientError
from gjallar_client.sessions import KeyringStore, MemoryStore, session_key
from gjallar_client.tui import TerminalController

TOKEN = "synthetic-cookie-secret"
PASSWORD = "synthetic-password-secret"


class Server:
    def __init__(self):
        self.calls = []
        self.authenticated = True
        self.fail = None
        self.partial = False

    def __call__(self, request):
        self.calls.append(request)
        if self.fail:
            return httpx.Response(self.fail, json={"detail": {"message": TOKEN}})
        path = request.url.path
        if path.endswith("/login"):
            data = {"authenticated": True, "user": {"user_id": "1", "username": "admin", "role": "admin"},
                    "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
            return httpx.Response(200, json={"ok": True, "data": data}, headers={"set-cookie": f"gjallar_session={TOKEN}; HttpOnly; Path=/"})
        if path.endswith("/me"):
            data = {"authenticated": self.authenticated, "user": {"user_id": "1", "username": "admin", "role": "admin"}}
        elif path.endswith("/logout"):
            data = {"authenticated": False, "revoked": True}
        elif path.endswith("/connection"):
            data = {"state": "unconfigured", "inventory_available": False}
        else:
            data = []
        return httpx.Response(200, json={"ok": True, "data": data, "meta": {"freshness": "partial" if self.partial else "fresh"}})


@pytest.fixture
def setup(tmp_path):
    config = Connections(tmp_path / "config")
    profile = config.add("one", "https://one.test")
    server = Server()
    app = Application(config, MemoryStore(), lambda p: Api(p, httpx.MockTransport(server)))
    return app, config, profile, server


def test_login_read_logout_and_no_secret_files(setup):
    app, config, profile, server = setup
    result = app.login("admin", PASSWORD, "one")
    assert result["user"]["role"] == "admin"
    assert TOKEN not in json.dumps(result)
    assert PASSWORD not in config.path.read_text() and TOKEN not in config.path.read_text()
    assert config.path.stat().st_mode & 0o777 == 0o600
    for resource in ("nodes", "vms", "templates"):
        assert app.read(resource)["data"] == []
    assert app.read("connection")["exit_code"] == 6
    server.partial = True
    assert app.read("vms")["warning"] == "관찰 일부 누락"
    assert app.logout()["authenticated"] is False
    assert app.sessions.get(session_key(profile)) is None
    assert all(str(r.url).startswith("https://one.test/") for r in server.calls)


@pytest.mark.parametrize("origin", ["http://remote.test", "http://localhost:8000", "https://user:secret@one.test", "https://one.test/prefix", "https://one.test/?secret=1", "https://one.test/#secret", "https://one.test:0", "https://one.test\n"])
def test_unsafe_origins(origin):
    with pytest.raises(ClientError):
        canonical_origin(origin)


def test_canonical_origin():
    assert canonical_origin("https://EXAMPLE.test:443/") == "https://example.test"
    assert canonical_origin("http://[::1]:8000") == "http://[::1]:8000"


def test_switch_separates_same_host_ports_and_failure_preserves_selection(setup):
    app, config, profile, server = setup
    app.login("admin", PASSWORD, "one")
    other = config.add("two", "https://one.test:8443")
    server.authenticated = False
    with pytest.raises(ClientError):
        app.use("two")
    assert config.read()["selected"] == "one"
    assert "cookie" not in server.calls[-1].headers
    server.authenticated = True
    app.login("admin", PASSWORD, "two")
    assert config.read()["selected"] == "two"
    assert session_key(profile) != session_key(other)


def test_me_200_false_and_local_expiry_clear_cookie(setup):
    app, _, profile, server = setup
    app.login("admin", PASSWORD, "one")
    server.authenticated = False
    with pytest.raises(ClientError, match="만료"):
        app.status()
    assert app.sessions.get(session_key(profile)) is None
    app.sessions.set(session_key(profile), {"token": TOKEN, "expires_at": "2000-01-01T00:00:00+00:00", "username": "admin"})
    count = len(server.calls)
    with pytest.raises(ClientError):
        app.status()
    assert len(server.calls) == count


@pytest.mark.parametrize(("status", "code", "exit_code"), [(401,"LOGIN_FAILED",3), (403,"PERMISSION_DENIED",4), (302,"REDIRECT_REJECTED",5), (500,"SERVER_ERROR",5)])
def test_errors_do_not_expose_server_body(setup, status, code, exit_code):
    app, _, _, server = setup
    server.fail = status
    with pytest.raises(ClientError) as error:
        app.login("admin", PASSWORD, "one")
    assert error.value.code == code and error.value.exit_code == exit_code
    assert TOKEN not in str(error.value)
    assert len(server.calls) == 1


def test_tls_and_transport_failures(setup):
    _, _, profile, _ = setup
    for tls, expected in [(True, "TLS_ERROR"), (False, "COMMUNICATION_FAILED")]:
        def handler(request):
            if tls:
                try:
                    raise ssl.SSLCertVerificationError(TOKEN)
                except ssl.SSLError as cause:
                    raise httpx.ConnectError(PASSWORD) from cause
            raise httpx.ReadTimeout(PASSWORD)
        api = Api(profile, httpx.MockTransport(handler))
        with pytest.raises(ClientError) as error:
            api.request("GET", "auth/me")
        assert error.value.code == expected and PASSWORD not in str(error.value)
        api.close()


def test_logout_failure_still_removes_local_session(setup):
    app, _, profile, server = setup
    app.login("admin", PASSWORD, "one")
    server.fail = 500
    with pytest.raises(ClientError) as error:
        app.logout()
    assert error.value.code == "LOGOUT_UNCONFIRMED"
    assert app.sessions.get(session_key(profile)) is None


def test_atomic_replace_failure_and_config_corruption_preserve_original(setup, monkeypatch):
    _, config, _, _ = setup
    original = config.path.read_bytes()
    monkeypatch.setattr("os.replace", lambda *args: (_ for _ in ()).throw(OSError(TOKEN)))
    with pytest.raises(ClientError):
        config.add("two", "https://two.test")
    assert config.path.read_bytes() == original
    config.path.write_text('{"version": 99}')
    with pytest.raises(ClientError):
        config.read()
    assert config.path.read_text() == '{"version": 99}'


def test_config_lock_conflict(setup):
    _, config, _, _ = setup
    with file_lock(config.directory / ".config.lock"):
        with pytest.raises(ClientError) as error:
            config.add("two", "https://two.test")
    assert error.value.code == "STORAGE_BUSY"


def test_keyring_allowlist_and_fake_backend_roundtrip():
    values = {}
    backend_type = type("Keyring", (), {
        "__module__": "keyring.backends.macOS",
        "get_password": lambda self, s, k: values.get(k),
        "set_password": lambda self, s, k, v: values.__setitem__(k, v),
        "delete_password": lambda self, s, k: values.pop(k),
    })
    store = KeyringStore(backend_type())
    store.set("key", {"token": TOKEN})
    assert store.get("key")["token"] == TOKEN
    store.delete("key")
    assert not values
    with pytest.raises(ClientError):
        KeyringStore(MemoryStore())


def test_session_save_failure_revokes_new_session(setup, monkeypatch):
    app, config, _, server = setup
    monkeypatch.setattr(app.sessions, "set", lambda *args: (_ for _ in ()).throw(ClientError("STORE", "저장 실패")))
    with pytest.raises(ClientError):
        app.login("admin", PASSWORD, "one")
    assert server.calls[-1].url.path.endswith("/logout")
    assert config.read()["selected"] is None


def test_tui_login_queries_switch_quit_without_logout(setup):
    app, config, _, server = setup
    config.add("two", "https://two.test")
    class UI:
        actions = iter(["login", "nodes", "vms", "templates", "connection", "login", "switch", "quit"])
        connections = iter([0, 1, 0])
        output = []

        def next_action(self, controller):
            return next(self.actions)

        def choose(self, title, options):
            return next(self.connections)

        def prompt(self, message, secret=False):
            return PASSWORD if secret else "admin"

        def busy(self, message):
            self.output.append(message)

    ui = UI()
    assert TerminalController(app, ui).run() == 0
    assert config.read()["selected"] == "one"
    assert not any(r.url.path.endswith("/logout") for r in server.calls)
    assert PASSWORD not in "".join(ui.output) and TOKEN not in "".join(ui.output)


def test_cli_json_and_errors(tmp_path, capsys):
    from gjallar_client.cli import main
    prefix = ["--config-dir", str(tmp_path / "config")]
    assert main(prefix + ["connect", "one", "https://one.test"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"]
    assert main(prefix + ["connection", "list"]) == 0
    assert "one" in json.loads(capsys.readouterr().out)["connections"]
    assert main(prefix + ["connect", "one", "https://two.test"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "CONNECTION_EXISTS"


def test_config_failure_after_login_restores_previous_session(setup, monkeypatch):
    app, config, profile, server = setup
    app.login("admin", PASSWORD, "one")
    old = app.sessions.get(session_key(profile)).copy()
    monkeypatch.setattr(config, "select", lambda *args: (_ for _ in ()).throw(ClientError("WRITE", "실패")))
    with pytest.raises(ClientError):
        app.login("admin", "new-password", "one")
    assert app.sessions.get(session_key(profile)) == old
    assert server.calls[-1].url.path.endswith("/logout")


def test_non_json_response_and_inventory_unavailable_are_not_empty_success(setup):
    _, _, profile, _ = setup
    responses = [(httpx.Response(200, text=PASSWORD), "PROTOCOL_ERROR"),
                 (httpx.Response(503, json={"detail": {"code": "PROXMOX_INVENTORY_UNCONFIGURED"}}), "PROXMOX_INVENTORY_UNCONFIGURED")]
    for response, expected in responses:
        api = Api(profile, httpx.MockTransport(lambda _: response))
        with pytest.raises(ClientError) as error:
            api.request("GET", "nodes")
        assert error.value.code == expected
        assert PASSWORD not in str(error.value)
        api.close()


def test_locked_keyring_does_not_fallback_or_leak():
    def denied(*args):
        raise RuntimeError(TOKEN)
    backend_type = type("Keyring", (), {"__module__": "keyring.backends.SecretService", "get_password": denied})
    store = KeyringStore(backend_type())
    with pytest.raises(ClientError) as error:
        store.get("profile")
    assert error.value.code == "KEYRING_UNAVAILABLE"
    assert TOKEN not in str(error.value)
    assert "memory" in str(error.value)


@pytest.mark.parametrize('code', ['PROXMOX_TLS_FAILED', 'PROXMOX_ENDPOINT_UNAVAILABLE', 'PROXMOX_COMMUNICATION_FAILED'])
def test_setup_upstream_failure_keeps_safe_code_without_server_message(setup, code):
    _, _, profile, _ = setup
    response = httpx.Response(502, json={'detail': {'code': code, 'message': PASSWORD, 'debug': TOKEN}})
    api = Api(profile, httpx.MockTransport(lambda _: response))
    try:
        with pytest.raises(ClientError) as error:
            api.request('POST', 'setup/proxmox/registrations/trust', body={'endpoint': 'https://pve.example.test'})
        assert error.value.code == code
        assert PASSWORD not in str(error.value) and TOKEN not in str(error.value)
    finally:
        api.close()
