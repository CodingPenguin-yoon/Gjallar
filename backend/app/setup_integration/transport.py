"""HTTPS-only, DNS-pinned Proxmox setup transport with sanitized failures."""
import http.client
import ipaddress
import json
import re
import time
import uuid
import socket
import ssl
from urllib.parse import urlencode, urlsplit

from app.setup_integration.contracts import SetupError, permitted_address
from app.setup_integration.tls import proxmox_tls_context, pinned_tls_context, certificate_fingerprint, verify_certificate_pin


class ProxmoxSetupTransport:
    def __init__(self, endpoint, ca_pem="", *, resolver=socket.getaddrinfo, certificate_sha256=""):
        if certificate_sha256 and (ca_pem or not re.fullmatch(r"[a-f0-9]{64}", certificate_sha256)):
            raise SetupError("PROXMOX_REQUEST_INVALID", "인증서 fingerprint를 확인하세요.", 422)
        self.certificate_sha256 = certificate_sha256
        self.origin = urlsplit(endpoint)
        self.host = self.origin.hostname
        self.port = self.origin.port or 8006
        try:
            self.context = pinned_tls_context() if certificate_sha256 else proxmox_tls_context(ca_pem)
            addresses = {result[4][0] for result in resolver(self.host, self.port, type=socket.SOCK_STREAM)}
            if not addresses or any(not permitted_address(ipaddress.ip_address(value)) for value in addresses):
                raise SetupError("PROXMOX_ENDPOINT_REJECTED", "이 Proxmox 주소는 사용할 수 없습니다.", 422)
            self.address = sorted(addresses)[0]
        except (OSError, ValueError):
            raise SetupError("PROXMOX_ENDPOINT_UNAVAILABLE", "Proxmox 주소 또는 CA 인증서를 확인하세요.", 502) from None

    def verify_peer(self, ssl_object):
        if self.certificate_sha256:
            verify_certificate_pin(ssl_object.getpeercert(binary_form=True), self.certificate_sha256)

    @classmethod
    def probe_certificate(cls, *, endpoint):
        # No HTTP request and no authentication data during first-use trust discovery.
        transport = cls(endpoint)
        try:
            with socket.create_connection((transport.address, transport.port), timeout=5) as plain:
                with pinned_tls_context().wrap_socket(plain, server_hostname=transport.host) as peer:
                    fingerprint = certificate_fingerprint(peer.getpeercert(binary_form=True))
            return {"endpoint": endpoint, "certificate_sha256": fingerprint}
        except (OSError, ValueError):
            raise SetupError("PROXMOX_TLS_FAILED", "Proxmox 서버 인증서를 확인할 수 없습니다.", 502) from None

    def request(self, method, path, *, data=None, ticket=None, csrf=None, token_id=None, secret=None, timeout=None,
                response_metadata=False):
        if not path.startswith("/") or ".." in path or "?" in path or "#" in path:
            raise SetupError("PROXMOX_REQUEST_INVALID", "지원하지 않는 API 경로입니다.", 422)
        headers = {"Accept": "application/json"}
        if ticket:
            headers["Cookie"] = "PVEAuthCookie=" + ticket
            if csrf:
                headers["CSRFPreventionToken"] = csrf
        elif token_id and secret:
            headers["Authorization"] = f"PVEAPIToken={token_id}={secret}"
        if any(any(ord(c) < 32 or ord(c) > 126 for c in str(value)) for value in headers.values()):
            raise SetupError("PROXMOX_PROTOCOL_ERROR", "Proxmox 인증 응답 형식이 올바르지 않습니다.", 502)
        encoded = urlencode(data or {})
        route = "/api2/json" + path
        body = None
        if method in {"GET", "DELETE"}:
            if encoded:
                route += "?" + encoded
        else:
            body = encoded.encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        return self._send(method, route, headers, body, timeout=timeout, response_metadata=response_metadata)

    def upload_import(self, *, node, storage, filename, file, size, sha256, token_id, secret, heartbeat):
        if (not all(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', value) for value in (node, storage))
                or not re.fullmatch(r'gjallar-image-[1-9][0-9]{2,8}-[a-f0-9]{64}\.qcow2', filename)
                or type(size) is not int or not 104 <= size <= 1024 ** 3
                or not re.fullmatch(r'[a-f0-9]{64}', sha256) or file.tell() != 0):
            raise SetupError('PROXMOX_REQUEST_INVALID', '검증된 이미지의 고정 upload 입력을 확인하세요.', 422)
        boundary = 'gjallar-' + uuid.uuid4().hex
        fields = {'content': 'import', 'checksum-algorithm': 'sha256', 'checksum': sha256}
        prefix = ''.join(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
                         for key, value in fields.items()).encode('ascii')
        prefix += (f'--{boundary}\r\nContent-Disposition: form-data; name="filename"; filename="{filename}"\r\n'
                   'Content-Type: application/octet-stream\r\n\r\n').encode('ascii')
        suffix = f'\r\n--{boundary}--\r\n'.encode('ascii')
        headers = {'Accept': 'application/json', 'Authorization': f'PVEAPIToken={token_id}={secret}',
                   'Content-Type': 'multipart/form-data; boundary=' + boundary,
                   'Content-Length': str(len(prefix) + size + len(suffix))}
        if not token_id or not secret or any(any(ord(c) < 32 or ord(c) > 126 for c in value) for value in headers.values()):
            raise SetupError('PROXMOX_PROTOCOL_ERROR', 'Proxmox 인증정보 형식을 확인하세요.', 502)

        def chunks():
            deadline = time.monotonic() + 600
            next_heartbeat = time.monotonic() + 10
            heartbeat()
            yield prefix
            sent = 0
            while sent < size:
                now = time.monotonic()
                if now > deadline:
                    raise SetupError('PROXMOX_UPLOAD_TIMEOUT', '이미지 업로드 제한 시간을 초과했습니다.', 502)
                if now >= next_heartbeat:
                    heartbeat()
                    next_heartbeat = now + 10
                chunk = file.read(min(64 * 1024, size - sent))
                if not chunk:
                    raise SetupError('PROXMOX_UPLOAD_INCOMPLETE', '검증한 이미지 파일을 끝까지 읽지 못했습니다.', 502)
                sent += len(chunk)
                yield chunk
            if file.read(1):
                raise SetupError('PROXMOX_UPLOAD_INCOMPLETE', '검증한 이미지 파일 크기가 변경됐습니다.', 502)
            heartbeat()
            yield suffix

        return self._send('POST', f'/api2/json/nodes/{node}/storage/{storage}/upload', headers, chunks(), timeout=15)

    def _send(self, method, route, headers, body, *, timeout=None, response_metadata=False):
        read_timeout = timeout[1] if isinstance(timeout, tuple) else (timeout or 15)
        connection = http.client.HTTPSConnection(self.host, self.port, context=self.context, timeout=read_timeout)
        try:
            # Establish TLS against the original hostname while dialing only the
            # address checked above. Credentials are sent after certificate check.
            plain = socket.create_connection((self.address, self.port), timeout=5)
            try:
                connection.sock = self.context.wrap_socket(plain, server_hostname=self.host)
            except BaseException:
                plain.close()
                raise
            self.verify_peer(connection.sock)
            connection.sock.settimeout(read_timeout)
            connection.request(method, route, body=body, headers=headers)
            response = connection.getresponse()
            if response.status in {401, 403}:
                code = "PROXMOX_AUTH_FAILED" if response.status == 401 else "PROXMOX_PERMISSION_DENIED"
                raise SetupError(code, "Proxmox 로그인 또는 해당 작업의 권한을 확인하세요.", 502)
            if response.status == 404:
                raise SetupError("PROXMOX_NOT_FOUND", "Proxmox에서 요청한 대상을 찾을 수 없습니다.", 502)
            if not 200 <= response.status < 300:
                raise SetupError("PROXMOX_API_REJECTED", "Proxmox가 요청을 거부했습니다. 상태를 다시 확인하세요.", 502)
            content = response.read(2 * 1024 * 1024 + 1)
            if len(content) > 2 * 1024 * 1024:
                raise ValueError
            payload = json.loads(content)
            if not isinstance(payload, dict) or "data" not in payload:
                raise ValueError
            return payload if response_metadata else payload["data"]
        except ssl.SSLError:
            raise SetupError("PROXMOX_TLS_FAILED", "Proxmox 인증서 또는 CA를 검증할 수 없습니다.", 502) from None
        except (OSError, http.client.HTTPException):
            raise SetupError("PROXMOX_COMMUNICATION_FAILED", "Proxmox 통신 결과를 확인할 수 없습니다. 변경 요청을 자동 재시도하지 마세요.", 502) from None
        except (ValueError, UnicodeError):
            raise SetupError("PROXMOX_PROTOCOL_ERROR", "Proxmox 응답 형식이 올바르지 않습니다.", 502) from None
        finally:
            connection.close()
