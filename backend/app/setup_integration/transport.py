"""HTTPS-only, DNS-pinned Proxmox setup transport with sanitized failures."""
import http.client
import ipaddress
import json
import socket
import ssl
from urllib.parse import urlencode, urlsplit

from app.setup_integration.contracts import SetupError, permitted_address


class ProxmoxSetupTransport:
    def __init__(self, endpoint, ca_pem="", *, resolver=socket.getaddrinfo):
        self.origin = urlsplit(endpoint)
        self.host = self.origin.hostname
        self.port = self.origin.port or 8006
        try:
            self.context = ssl.create_default_context(cadata=ca_pem or None)
            addresses = {result[4][0] for result in resolver(self.host, self.port, type=socket.SOCK_STREAM)}
            if not addresses or any(not permitted_address(ipaddress.ip_address(value)) for value in addresses):
                raise SetupError("PROXMOX_ENDPOINT_REJECTED", "이 Proxmox 주소는 사용할 수 없습니다.", 422)
            self.address = sorted(addresses)[0]
        except (OSError, ValueError):
            raise SetupError("PROXMOX_ENDPOINT_UNAVAILABLE", "Proxmox 주소 또는 CA 인증서를 확인하세요.", 502) from None

    def request(self, method, path, *, data=None, ticket=None, csrf=None, token_id=None, secret=None, timeout=None):
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
        if method == "GET":
            if encoded:
                route += "?" + encoded
        else:
            body = encoded.encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
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
            return payload["data"]
        except ssl.SSLError:
            raise SetupError("PROXMOX_TLS_FAILED", "Proxmox 인증서 또는 CA를 검증할 수 없습니다.", 502) from None
        except (OSError, http.client.HTTPException):
            raise SetupError("PROXMOX_COMMUNICATION_FAILED", "Proxmox 통신 결과를 확인할 수 없습니다. 변경 요청을 자동 재시도하지 마세요.", 502) from None
        except (ValueError, UnicodeError):
            raise SetupError("PROXMOX_PROTOCOL_ERROR", "Proxmox 응답 형식이 올바르지 않습니다.", 502) from None
        finally:
            connection.close()
