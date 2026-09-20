import asyncio
from contextlib import asynccontextmanager
import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.auth.users import create_user
from app.console import gateway
from app.console.domain import ConsoleError, ProxyTicket, review_vm
from app.main import app

PATH = '/api/v1/nodes/node1/vms/40000/console'
ORIGIN = {'origin': 'http://127.0.0.1:5173'}
SECRET = 'synthetic-vnc-password'


class FakeConsole:
    def __init__(self):
        self.prepared = 0
        self.closed = 0
        self.closed_event = threading.Event()
        self.checked = 0
        self.inputs = []
        self.error = None

    def review(self):
        return review_vm({'name': 'test'}, {'status': 'running'}, {'VM.Audit': 1, 'VM.Console': 1}, node_id='node1', vmid=40000)

    def prepare(self):
        self.prepared += 1
        if self.error:
            raise self.error
        return ProxyTicket(5900, 'synthetic-vnc-ticket', SECRET)

    def check_selection(self):
        self.checked += 1

    @asynccontextmanager
    async def open(self, ticket):
        owner = self
        queue = asyncio.Queue()

        class Upstream:
            async def send(self, data):
                owner.inputs.append(data)
                await queue.put(data)

            def __aiter__(self):
                return self

            async def __anext__(self):
                return await queue.get()

        try:
            yield Upstream()
        finally:
            self.closed += 1
            self.closed_event.set()


@pytest.fixture
def flow(monkeypatch):
    monkeypatch.setenv('GJALLAR_PASSWORD_HASH_ITERATIONS', '1200')
    monkeypatch.setenv('FRONTEND_PORT', '5173')
    fake = FakeConsole()
    monkeypatch.setattr(gateway, 'console_client', lambda **kwargs: fake)
    monkeypatch.setattr('app.api.v1.vm_console.console_client', lambda **kwargs: fake)
    for role in ('operator', 'viewer'):
        create_user(username=role, password='synthetic-password', role=role)
    with TestClient(app) as client:
        yield client, fake
    assert gateway._counts == {}


def login(client, role='operator'):
    assert client.post('/api/v1/auth/login', json={'username': role, 'password': 'synthetic-password'}).status_code == 200


def test_console_read_and_upgrade_require_operator(flow):
    client, fake = flow
    assert client.get(PATH).status_code == 401
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(PATH + '/socket', headers=ORIGIN):
            pass
    login(client, 'viewer')
    assert client.get(PATH).status_code == 403
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(PATH + '/socket', headers=ORIGIN):
            pass
    assert fake.prepared == 0
    login(client)
    response = client.get(PATH)
    assert response.status_code == 200 and SECRET not in response.text


@pytest.mark.parametrize('headers,suffix', [({}, ''), ({'origin': 'https://evil.example'}, ''), ({'origin': 'null'}, ''),
                                           (ORIGIN, '?ticket=guessed'), (ORIGIN, '?vmid=40001')])
def test_cross_origin_missing_origin_and_query_rejected_before_pve(flow, headers, suffix):
    client, fake = flow
    login(client)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(PATH + '/socket' + suffix, headers=headers):
            pass
    assert fake.prepared == 0


def test_binary_relay_explicit_close_and_no_reconnect(flow):
    client, fake = flow
    login(client)
    with client.websocket_connect(PATH + '/socket', headers=ORIGIN) as ws:
        assert ws.receive_json() == {'type': 'ready', 'password': SECRET, 'expires_in': 900}
        ws.send_bytes(b'RFB 003.008\n')
        assert ws.receive_bytes() == b'RFB 003.008\n'
        ws.send_bytes(b'a' * 100000)
        assert len(ws.receive_bytes()) == 65536
        assert len(ws.receive_bytes()) == 34464
    assert fake.closed_event.wait(2)
    assert fake.prepared == 1 and fake.closed == 1


def test_browser_disconnect_does_not_send_a_second_asgi_close(monkeypatch):
    fake = FakeConsole()
    actor = SimpleNamespace(user_id='synthetic-user')
    monkeypatch.setattr(gateway, 'authenticated_actor', lambda token: actor)
    monkeypatch.setattr(gateway, 'console_client', lambda **kwargs: fake)
    monkeypatch.setattr(gateway, 'allowed_origins', lambda: {ORIGIN['origin']})

    class Browser:
        query_params = {}
        headers = ORIGIN
        cookies = {}
        application_state = WebSocketState.CONNECTING
        client_state = WebSocketState.CONNECTING

        async def accept(self):
            self.application_state = self.client_state = WebSocketState.CONNECTED

        async def send_json(self, message):
            assert message['type'] == 'ready'

        async def receive(self):
            self.client_state = WebSocketState.DISCONNECTED
            return {'type': 'websocket.disconnect'}

        async def close(self, **kwargs):
            raise AssertionError('Browser has already closed the WebSocket')

    asyncio.run(gateway.serve_console(Browser(), node_id='node1', vmid=40000))
    assert fake.closed == 1 and gateway._counts == {}


@pytest.mark.parametrize('kind', ['text', 'oversize'])
def test_invalid_browser_frame_closes_both_sides(flow, kind):
    client, fake = flow
    login(client)
    with client.websocket_connect(PATH + '/socket', headers=ORIGIN) as ws:
        ws.receive_json()
        if kind == 'text':
            ws.send_text('not-rfb')
        else:
            ws.send_bytes(b'x' * (128 * 1024 + 1))
        with pytest.raises(WebSocketDisconnect) as failure:
            ws.receive_bytes()
        assert failure.value.code == 4409
    assert not fake.inputs and fake.closed == 1


@pytest.mark.parametrize('reason', ['logout', 'expiry'])
def test_session_revocation_and_time_limit_close_without_retry(flow, monkeypatch, reason):
    client, fake = flow
    login(client)
    original = gateway.relay
    async def quick(*args, **kwargs):
        return await original(*args, **kwargs, auth_interval=.01, max_duration=.2 if reason == 'expiry' else 5)
    monkeypatch.setattr(gateway, 'relay', quick)
    with client.websocket_connect(PATH + '/socket', headers=ORIGIN) as ws:
        ws.receive_json()
        if reason == 'logout':
            client.post('/api/v1/auth/logout')
        with pytest.raises(WebSocketDisconnect) as failure:
            ws.receive_bytes()
        assert failure.value.code == (4403 if reason == 'logout' else 4408)
    assert fake.prepared == fake.closed == 1


def test_failed_proxy_is_never_retried(flow):
    client, fake = flow
    login(client)
    fake.error = ConsoleError('CONSOLE_PROXY_FAILED', 'synthetic failure', 502)
    with client.websocket_connect(PATH + '/socket', headers=ORIGIN) as ws:
        with pytest.raises(WebSocketDisconnect) as failure:
            ws.receive_json()
        assert failure.value.reason == 'CONSOLE_PROXY_FAILED'
    assert fake.prepared == 1 and fake.closed == 0


def test_connection_capacity_is_bounded_and_released():
    with gateway.connection_slot('a'), gateway.connection_slot('a'):
        with pytest.raises(ConsoleError):
            with gateway.connection_slot('a'):
                pass
        with gateway.connection_slot('b'):
            assert gateway._counts == {'a': 2, 'b': 1}
    assert gateway._counts == {}


@pytest.mark.parametrize('config,status,permissions', [
    ({}, {'status': 'stopped'}, {'VM.Audit', 'VM.Console'}),
    ({'template': 1}, {'status': 'running'}, {'VM.Audit', 'VM.Console'}),
    ({'vga': 'serial0'}, {'status': 'running'}, {'VM.Audit', 'VM.Console'}),
    ({'vga': 'type=none'}, {'status': 'running'}, {'VM.Audit', 'VM.Console'}),
    ({}, {'status': 'running'}, {'VM.Audit'}),
])
def test_unsupported_target_is_not_started(config, status, permissions):
    with pytest.raises(ConsoleError):
        review_vm(config, status, permissions, node_id='node1', vmid=40000)


@pytest.mark.parametrize('patch', [{'port': True}, {'port': 6000}, {'port': '5900.0'}, {'port': ' 5900'},
                                  {'port': '05900'}, {'port': '５９００'}, {'port': '6000'}, {'port': 5900.0}, {'ticket': 'bad\nheader'},
                                  {'password': ''}, {'password': 'bad\rheader'}, {'ticket': 'x' * 513}])
def test_proxy_secret_response_is_validated_without_leaking(patch):
    with pytest.raises(ConsoleError) as failure:
        ProxyTicket.parse({'port': 5900, 'ticket': SECRET, 'password': SECRET, **patch})
    assert SECRET not in str(failure.value)


def test_proxy_repr_never_contains_ticket_or_password():
    ticket = ProxyTicket.parse({'port': 5900, 'ticket': SECRET, 'password': SECRET})
    assert SECRET not in repr(ticket)


@pytest.mark.parametrize('port', [5900, '5900', 5999, '5999'])
def test_proxy_accepts_pve_decimal_port_without_changing_credentials(port):
    ticket = ProxyTicket.parse({'port': port, 'ticket': SECRET})
    assert type(ticket.port) is int and ticket.port == int(port)
    assert ticket.ticket == ticket.password == SECRET


def test_permission_downgrade_closes_active_stream(flow, monkeypatch):
    client, fake = flow
    login(client)
    original = gateway.relay
    async def quick(*args, **kwargs):
        return await original(*args, **kwargs, auth_interval=.01, max_duration=5)
    monkeypatch.setattr(gateway, 'relay', quick)
    with client.websocket_connect(PATH + '/socket', headers=ORIGIN) as ws:
        ws.receive_json()
        monkeypatch.setattr(gateway, 'actor_for_session_token', lambda _: None)
        with pytest.raises(WebSocketDisconnect) as failure:
            ws.receive_bytes()
        assert failure.value.code == 4403
    assert fake.prepared == fake.closed == 1


def test_source_change_closes_active_stream(flow, monkeypatch):
    client, fake = flow
    login(client)
    original = gateway.relay
    async def quick(*args, **kwargs):
        return await original(*args, **kwargs, auth_interval=.01, max_duration=5)
    monkeypatch.setattr(gateway, 'relay', quick)
    with client.websocket_connect(PATH + '/socket', headers=ORIGIN) as ws:
        ws.receive_json()
        def changed():
            raise ConsoleError('SETUP_RESTART_REQUIRED', 'changed', 503)
        monkeypatch.setattr(fake, 'check_selection', changed)
        with pytest.raises(WebSocketDisconnect) as failure:
            ws.receive_bytes()
        assert failure.value.reason == 'SETUP_RESTART_REQUIRED'
    assert fake.prepared == fake.closed == 1
