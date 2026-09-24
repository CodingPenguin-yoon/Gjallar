"""Strict HTTPS/WSS console transport; PVE secrets never enter URLs shown to users."""
import asyncio
from contextlib import asynccontextmanager
import logging
import os
import socket
from urllib.parse import urlencode

from websockets.asyncio.client import connect, ClientConnection
from websockets.exceptions import WebSocketException

from app.console.domain import ConsoleError, ProxyTicket, review_vm, validate_target
from app.setup_integration.contracts import RegistrationIntent, SetupError
from app.setup_integration.runtime import ManagedRequests, console_selection
from app.setup_integration.transport import ProxmoxSetupTransport

# WebSocket protocol debug logging contains authentication headers and RFB bytes.
# Keep it private; the API exposes fixed, sanitized error codes instead.
_protocol_log = logging.Logger('gjallar.console.transport', level=logging.CRITICAL + 1)
_protocol_log.addHandler(logging.NullHandler())
_protocol_log.propagate = False


class ConsoleClient:
    def __init__(self, *, node_id, vmid):
        validate_target(node_id, vmid)
        self.node_id, self.vmid = node_id, vmid
        selected = console_selection(node_id=node_id, vmid=vmid)
        self.revision = selected['revision_id'] if selected else None
        if selected:
            requests = ManagedRequests(selected)
            self.transport, self.request = requests.transport, requests.request
            self.token_id = selected['configuration']['token_id']
            self.secret = selected['secret']
        else:
            if os.getenv('PROXMOX_TLS_INSECURE', '').lower() in {'1', 'true', 'yes', 'on'}:
                raise ConsoleError('CONSOLE_TLS_REQUIRED', '콘솔은 검증된 HTTPS 연결이 필요합니다. 관리형 연결에 공개 CA를 등록하세요.', 503)
            try:
                endpoint = RegistrationIntent.endpoint_origin(os.getenv('PROXMOX_API_URL', ''))
            except ValueError:
                raise ConsoleError('CONSOLE_CONNECTION_UNAVAILABLE', '검증된 Proxmox 연결을 등록하세요.', 503) from None
            self.transport = ProxmoxSetupTransport(endpoint)
            self.token_id, self.secret = os.getenv('PROXMOX_API_TOKEN_ID', ''), os.getenv('PROXMOX_API_TOKEN_SECRET', '')
            if not self.token_id or not self.secret:
                raise ConsoleError('CONSOLE_CONNECTION_UNAVAILABLE', 'Proxmox 인증정보를 확인하세요.', 503)
            self.request = self._legacy_request
        if any(not 33 <= ord(char) <= 126 for char in self.token_id + self.secret):
            raise ConsoleError('CONSOLE_CONNECTION_UNAVAILABLE', 'Proxmox 인증정보 형식을 확인하세요.', 503)
        self.path = f'/nodes/{node_id}/qemu/{vmid}'

    def _legacy_request(self, method, path, *, data=None):
        return self.transport.request(method, path, data=data, token_id=self.token_id, secret=self.secret)

    def check_selection(self):
        selected = console_selection(node_id=self.node_id, vmid=self.vmid)
        if (selected['revision_id'] if selected else None) != self.revision:
            raise ConsoleError('CONSOLE_CONNECTION_CHANGED', 'Proxmox 연결이 변경됐습니다. 다시 로그인하거나 서버를 재시작하세요.', 503)

    def review(self):
        self.check_selection()
        permission_path = f'/vms/{self.vmid}'
        permissions = self.request('GET', '/access/permissions', data={'path': permission_path})
        config = self.request('GET', self.path + '/config', data={'current': 1})
        status = self.request('GET', self.path + '/status/current')
        if (not all(isinstance(value, dict) for value in (permissions, config, status))
                or not isinstance(permissions.get(permission_path, {}), dict)):
            raise ConsoleError('CONSOLE_OBSERVATION_UNAVAILABLE', 'PVE 권한·VM 상태를 확인할 수 없습니다.', 502)
        return review_vm(config, status, permissions.get(permission_path, {}), node_id=self.node_id, vmid=self.vmid)

    def prepare(self):
        self.review()
        return ProxyTicket.parse(self.request('POST', self.path + '/vncproxy', data={'websocket': 1}))

    @asynccontextmanager
    async def open(self, ticket):
        transport = self.transport
        route = '/api2/json' + self.path + '/vncwebsocket?' + urlencode({'port': ticket.port, 'vncticket': ticket.ticket})
        host = f'[{transport.host}]' if ':' in transport.host else transport.host
        uri = f'wss://{host}:{transport.port}{route}'
        sock = socket.socket(socket.AF_INET6 if ':' in transport.address else socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(False)
        try:
            await asyncio.wait_for(asyncio.get_running_loop().sock_connect(sock, (transport.address, transport.port)), 5)
            class PinnedConnection(ClientConnection):
                async def handshake(self, *args, **kwargs):
                    # TLS is established, but WebSocket headers/ticket have not been sent.
                    transport.verify_peer(self.transport.get_extra_info('ssl_object'))
                    return await super().handshake(*args, **kwargs)

            # Supplying an already connected socket also forbids all redirects in websockets.
            async with connect(uri, sock=sock, ssl=transport.context, server_hostname=transport.host,
                    create_connection=PinnedConnection, proxy=None, compression=None, additional_headers={'Authorization': f'PVEAPIToken={self.token_id}={self.secret}'},
                    logger=_protocol_log, open_timeout=5, close_timeout=2, max_size=4 * 1024 * 1024, max_queue=16) as upstream:
                yield upstream
        except (OSError, TimeoutError, WebSocketException, ValueError):
            raise ConsoleError('CONSOLE_UPSTREAM_FAILED', 'PVE 콘솔 연결을 확인하지 못했습니다. 자동 재접속하지 않습니다.', 502) from None
        finally:
            sock.close()


def console_client(*, node_id, vmid):
    try:
        return ConsoleClient(node_id=node_id, vmid=vmid)
    except SetupError as exc:
        raise ConsoleError(exc.code, str(exc), exc.status) from None
