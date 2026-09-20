import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.console import infrastructure
from app.console.domain import ConsoleError, ProxyTicket


def test_wss_uses_pinned_socket_verified_tls_and_no_proxy(monkeypatch):
    calls = []
    socket = SimpleNamespace(setblocking=lambda value: calls.append(('blocking', value)), close=lambda: calls.append(('close',)))
    monkeypatch.setattr(infrastructure, 'socket', SimpleNamespace(socket=lambda *args: socket, AF_INET=2, AF_INET6=30, SOCK_STREAM=1))
    @asynccontextmanager
    async def connect(uri, **kwargs):
        calls.append(('connect', uri, kwargs))
        yield 'upstream'
    monkeypatch.setattr(infrastructure, 'connect', connect)
    client = infrastructure.ConsoleClient.__new__(infrastructure.ConsoleClient)
    client.path = '/nodes/node1/qemu/40000'
    client.token_id, client.secret = 'synthetic@pve!token', 'synthetic-secret'
    client.transport = SimpleNamespace(host='pve.example.test', address='192.168.2.10', port=8006, context=object())
    async def run():
        async def dial(sock, address):
            assert sock is socket
            calls.append(('dial', address))
        monkeypatch.setattr(asyncio.get_running_loop(), 'sock_connect', dial)
        async with client.open(ProxyTicket(5901, 'synthetic-ticket', 'synthetic-password')) as upstream:
            assert upstream == 'upstream'
    asyncio.run(run())
    assert calls[1] == ('dial', ('192.168.2.10', 8006))
    _, uri, options = calls[2]
    assert uri == 'wss://pve.example.test:8006/api2/json/nodes/node1/qemu/40000/vncwebsocket?port=5901&vncticket=synthetic-ticket'
    assert options['sock'] is socket and options['ssl'] is client.transport.context
    assert options['server_hostname'] == 'pve.example.test' and options['proxy'] is None and options['compression'] is None
    assert options['logger'].isEnabledFor(50) is False
    assert options['additional_headers'] == {'Authorization': 'PVEAPIToken=synthetic@pve!token=synthetic-secret'}
    assert calls[-1] == ('close',)


def test_strict_console_does_not_inherit_legacy_tls_bypass(monkeypatch):
    monkeypatch.setattr(infrastructure, 'console_selection', lambda **_: None)
    monkeypatch.setenv('PROXMOX_TLS_INSECURE', 'true')
    with pytest.raises(ConsoleError) as failure:
        infrastructure.console_client(node_id='node1', vmid=40000)
    assert failure.value.code == 'CONSOLE_TLS_REQUIRED'


def test_browser_websocket_debug_cannot_log_cookie_or_rfb_credentials():
    import logging
    from app.console.log_safety import ConsoleProtocolFilter
    record = logging.LogRecord('uvicorn.error', logging.DEBUG, '', 0, '> TEXT %s', ('synthetic-secret',), None)
    record.websocket = object()
    assert ConsoleProtocolFilter().filter(record)
    assert 'synthetic-secret' not in record.getMessage()
    error = logging.LogRecord('uvicorn.error', logging.ERROR, '', 0, 'connection failed', (), None)
    error.websocket = object()
    assert ConsoleProtocolFilter().filter(error) and error.getMessage() == 'connection failed'
