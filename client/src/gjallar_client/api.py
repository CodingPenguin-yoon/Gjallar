"""Origin-bound transport for the existing cookie session API."""
import ssl

import httpx

from .errors import ClientError


SETUP_UPSTREAM_ERRORS = {
    "PROXMOX_TLS_FAILED": "Proxmox 인증서를 확인할 수 없습니다. Gjallar 서버 시각과 인증서 유효기간·저장한 지문 또는 CA를 확인하세요.",
    "PROXMOX_ENDPOINT_UNAVAILABLE": "Gjallar 서버에서 Proxmox 주소를 해석할 수 없거나 CA를 읽지 못했습니다. 주소·DNS·CA 설정을 확인하세요.",
    "PROXMOX_COMMUNICATION_FAILED": "Gjallar 서버에서 Proxmox에 연결하거나 응답을 확인하지 못했습니다. 서버 컨테이너의 네트워크·8006 포트를 확인하세요. 변경 요청은 자동 재시도하지 마세요.",
    "PROXMOX_PROTOCOL_ERROR": "Proxmox 응답 형식을 확인할 수 없습니다. 주소가 Proxmox API를 가리키는지 확인하세요.",
    "PROXMOX_AUTH_FAILED": "Proxmox 계정·realm·비밀번호를 확인하세요.",
    "PROXMOX_PERMISSION_DENIED": "Proxmox 계정 또는 토큰에 요청한 작업의 권한이 없습니다.",
}


def is_tls_error(exc):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, ssl.SSLError):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


class Api:
    def __init__(self, profile, transport=None):
        self.profile = profile
        try:
            context = ssl.create_default_context(cafile=profile["ca_file"])
        except (OSError, ssl.SSLError):
            raise ClientError("TLS_ERROR", "CA 파일을 읽거나 검증할 수 없습니다.", 5) from None
        self.client = httpx.Client(base_url=profile["origin"], verify=context, transport=transport,
                                   follow_redirects=False, trust_env=False, timeout=15.0)

    def close(self):
        self.client.close()

    def request(self, method, path, *, token=None, body=None):
        headers = {}
        if token:
            if not isinstance(token, str) or any(ord(c) < 33 or ord(c) > 126 or c in ';,"\\' for c in token):
                raise ClientError("SESSION_INVALID", "보관된 cookie가 올바르지 않습니다.")
            headers["Cookie"] = f'{self.profile["cookie_name"]}={token}'
        self.client.cookies.clear()
        try:
            response = self.client.request(method, "/api/v1/" + path, headers=headers, json=body)
        except httpx.TransportError as exc:
            if is_tls_error(exc):
                raise ClientError("TLS_ERROR", "서버 인증서를 검증할 수 없습니다. 인증서와 CA를 확인하세요.", 5) from None
            raise ClientError("COMMUNICATION_FAILED", "서버 통신 실패. 주소·네트워크를 확인하세요. 로그인 응답 유실 시 session은 만료 또는 관리자 폐기가 필요할 수 있습니다.", 5) from None
        if 300 <= response.status_code < 400:
            raise ClientError("REDIRECT_REJECTED", "서버 redirect를 따르지 않았습니다. 정확한 서버 origin을 설정하세요.", 5)
        if response.status_code == 401:
            raise ClientError("LOGIN_FAILED" if path == "auth/login" else "SESSION_EXPIRED", "로그인 정보가 틀리거나 session이 만료·폐기되었습니다.", 3)
        if response.status_code == 403:
            raise ClientError("PERMISSION_DENIED", "이 요청을 수행할 Gjallar 권한이 없습니다.", 4)
        try:
            payload = response.json()
        except ValueError:
            raise ClientError("PROTOCOL_ERROR", "Gjallar JSON 응답이 아닙니다.", 5) from None
        if response.is_error:
            detail = payload.get("detail", {}) if isinstance(payload, dict) else {}
            code = detail.get("code") if isinstance(detail, dict) else None
            if (path.startswith("setup/proxmox/registrations/") and response.status_code == 502
                    and isinstance(code, str) and code in SETUP_UPSTREAM_ERRORS):
                # Never echo upstream messages: they may contain credentials.
                raise ClientError(code, SETUP_UPSTREAM_ERRORS[code], 5)
            if code in {"PROXMOX_INVENTORY_UNCONFIGURED", "PROXMOX_INVENTORY_DEGRADED"}:
                raise ClientError(code, "Proxmox 미설정 또는 관찰 불가입니다. Gjallar 서버의 연결 상태를 확인하세요.", 6)
            if response.status_code == 404:
                raise ClientError("NOT_FOUND", "대상 또는 작업을 찾을 수 없습니다. 서버·ID를 확인하세요.", 5)
            if response.status_code == 409:
                raise ClientError("STATE_CONFLICT", "현재 상태가 요청 또는 검토한 계획과 충돌합니다. 기존 작업과 대상 상태를 먼저 확인하세요.", 8)
            if response.status_code == 422:
                raise ClientError("INVALID_REQUEST", "서버가 입력을 거부했습니다. 명령 도움말과 생성 입력을 확인하세요.", 2)
            raise ClientError("SERVER_ERROR", "Gjallar 서버가 요청을 처리하지 못했습니다.", 5)
        if not isinstance(payload, dict) or payload.get("ok") is not True or "data" not in payload or not isinstance(payload.get("meta", {}), dict):
            raise ClientError("PROTOCOL_ERROR", "Gjallar 응답 계약이 맞지 않습니다.", 5)
        return payload, response.cookies
