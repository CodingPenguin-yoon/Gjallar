"""Shared CLI/TUI flows. All remote operations go through the selected API."""
from .api import Api
from .errors import ClientError
from .sessions import session_key, unexpired


class Application:
    def __init__(self, connections, sessions, api_factory=Api, connection_name=None):
        self.connections, self.sessions, self.api_factory = connections, sessions, api_factory
        self.connection_name = connection_name

    def _session(self, profile):
        key = session_key(profile)
        value = self.sessions.get(key)
        if value and not unexpired(value):
            self.sessions.delete(key)
            raise ClientError("SESSION_EXPIRED", "session이 만료되었습니다. 다시 로그인하세요.", 3)
        return value

    def _request(self, profile, method, path, **kwargs):
        api = self.api_factory(profile)
        try:
            return api.request(method, path, **kwargs)
        finally:
            api.close()

    @staticmethod
    def _user(data):
        user = data.get("user") if isinstance(data, dict) else None
        if not isinstance(user, dict) or user.get("role") not in {"viewer", "operator", "admin"} or not isinstance(user.get("username"), str):
            raise ClientError("PROTOCOL_ERROR", "계정 응답 계약이 맞지 않습니다.", 5)
        return {key: user.get(key) for key in ("user_id", "username", "role")}

    def login(self, username, password, name=None):
        name, profile = self.connections.get(name or self.connection_name)
        key = session_key(profile)
        previous = self.sessions.get(key)
        api = self.api_factory(profile)
        token = None
        storage_attempted = False
        try:
            payload, cookies = api.request("POST", "auth/login", body={"username": username, "password": password})
            matches = [cookie.value for cookie in cookies.jar if cookie.name == profile["cookie_name"]]
            if len(matches) != 1:
                raise ClientError("PROTOCOL_ERROR", "고유한 session cookie가 없습니다. 서버 session 설정을 확인하세요.", 5)
            token = matches[0]
            data = payload["data"]
            user = self._user(data)
            value = {"token": token, "expires_at": data.get("expires_at"), "username": user["username"]}
            if data.get("authenticated") is not True or not token or not unexpired(value):
                raise ClientError("PROTOCOL_ERROR", "로그인 session 응답이 올바르지 않습니다.", 5)
            storage_attempted = True
            self.sessions.set(key, value)
            self.connections.select(name, profile)
            return {"ok": True, "server": profile["origin"], "connection": name, "user": user,
                    "session_mode": self.sessions.mode, "expires_at": value["expires_at"]}
        except ClientError as original:
            storage_failure = False
            if storage_attempted:
                try:
                    if previous:
                        self.sessions.set(key, previous)
                    else:
                        self.sessions.delete(key)
                except ClientError:
                    storage_failure = True
            if token:
                try:
                    api.request("POST", "auth/logout", token=token)
                except ClientError:
                    raise ClientError("LOGIN_CLEANUP_UNCONFIRMED", "로그인 완료 처리 실패. 새 session의 서버 폐기를 확인하지 못했습니다. 만료 또는 관리자 폐기가 필요합니다.") from None
            if storage_failure:
                raise ClientError("SESSION_STORAGE_UNCONFIRMED", "새 session은 서버에서 폐기했지만 로컬 keyring 복원을 확인하지 못했습니다. keyring 잠금·저장 상태를 확인하세요.") from None
            raise original
        finally:
            api.close()

    def status(self, name=None):
        name, profile = self.connections.get(name or self.connection_name)
        session = self._session(profile)
        try:
            payload, _ = self._request(profile, "GET", "auth/me", token=session["token"] if session else None)
        except ClientError as exc:
            if exc.exit_code == 3:
                self.sessions.delete(session_key(profile))
            raise
        data = payload["data"]
        if not isinstance(data, dict):
            raise ClientError("PROTOCOL_ERROR", "계정 상태 응답 계약이 맞지 않습니다.", 5)
        if data.get("authenticated") is not True or not session:
            if session:
                self.sessions.delete(session_key(profile))
            raise ClientError("SESSION_EXPIRED", "로그인이 필요합니다. session이 없거나 만료·폐기되었습니다.", 3)
        return {"ok": True, "server": profile["origin"], "connection": name,
                "user": self._user(data), "session_mode": self.sessions.mode}

    def use(self, name):
        _, profile = self.connections.get(name)
        status = self.status(name)
        self.connections.select(name, profile)
        return status

    def read(self, resource):
        if resource not in {"nodes", "vms", "templates", "connection"}:
            raise ClientError("INVALID_RESOURCE", "지원하지 않는 조회입니다.", 2)
        name, profile = self.connections.get(self.connection_name)
        identity = self.status(name)
        session = self._session(profile)
        if session is None:
            raise ClientError("SESSION_EXPIRED", "session이 변경되었습니다. 다시 로그인하세요.", 3)
        path = "setup/proxmox/connection" if resource == "connection" else resource
        try:
            payload, _ = self._request(profile, "GET", path, token=session["token"])
        except ClientError as exc:
            if exc.exit_code == 3:
                self.sessions.delete(session_key(profile))
            raise
        data, meta = payload["data"], payload.get("meta", {})
        if (resource == "connection" and not isinstance(data, dict)) or (resource != "connection" and not isinstance(data, list)):
            raise ClientError("PROTOCOL_ERROR", "조회 응답 계약이 맞지 않습니다.", 5)
        observation = data if resource == "connection" else meta.get("connection", {})
        if not isinstance(observation, dict):
            raise ClientError("PROTOCOL_ERROR", "연결 관찰 응답 계약이 맞지 않습니다.", 5)
        warning = "관찰 일부 누락" if meta.get("freshness") == "partial" or observation.get("freshness") == "partial" else None
        state = observation.get("state")
        exit_code = 6 if state == "unconfigured" or (state == "degraded" and observation.get("inventory_available") is False) else 0
        return {**identity, "data": data, "meta": meta, "warning": warning, "exit_code": exit_code}

    def logout(self, name=None):
        name, profile = self.connections.get(name or self.connection_name)
        key = session_key(profile)
        session = self.sessions.get(key)
        failure = None
        try:
            if session:
                payload, _ = self._request(profile, "POST", "auth/logout", token=session["token"])
                if not isinstance(payload["data"], dict) or payload["data"].get("authenticated") is not False:
                    raise ClientError("PROTOCOL_ERROR", "logout 응답이 올바르지 않습니다.", 5)
        except ClientError as exc:
            failure = exc
        finally:
            self.sessions.delete(key)
        if failure:
            raise ClientError("LOGOUT_UNCONFIRMED", "로컬 session은 삭제했습니다. 서버 폐기는 확인되지 않았습니다. 만료 또는 관리자 폐기를 확인하세요.", failure.exit_code)
        return {"ok": True, "connection": name, "authenticated": False, "status": "revoked_or_already_expired" if session else "no_local_session"}

    def proxmox_setup(self, action, *, attempt_id=None, body=None):
        import uuid

        if action not in {"trust", "list", "prepare", "status", "login", "mfa", "plan", "confirm", "verify", "activate", "observe", "cancel", "revoke", "import-plan", "import-env"}:
            raise ClientError("INVALID_ACTION", "지원하지 않는 연결 등록 작업입니다.", 2)
        name, profile = self.connections.get(self.connection_name)
        identity = self.status(name)
        if identity["user"]["role"] != "admin":
            raise ClientError("PERMISSION_DENIED", "Proxmox 연결 등록은 Gjallar 관리자만 할 수 있습니다.", 4)
        path = "setup/proxmox/registrations"
        if action == "trust":
            path += "/trust"
        elif action not in {"prepare", "list"}:
            try:
                path += "/" + str(uuid.UUID(attempt_id))
            except (ValueError, TypeError, AttributeError):
                raise ClientError("INVALID_ATTEMPT", "올바른 등록 ID가 필요합니다.", 2) from None
            if action != "status":
                path += "/" + action
        session = self._session(profile)
        if session is None:
            raise ClientError("SESSION_EXPIRED", "다시 로그인하세요.", 3)
        payload, _ = self._request(profile, "GET" if action in {"status", "list"} else "POST", path,
                                   token=session["token"], body=body)
        return {**identity, "data": payload["data"]}

    def request(self, path, *, method="GET", body=None, operator=False):
        """Authenticated CLI workflow call; paths are built by local commands only."""
        name, profile = self.connections.get(self.connection_name)
        identity = self.status(name)
        if operator and identity["user"]["role"] not in {"operator", "admin"}:
            raise ClientError("PERMISSION_DENIED", "VM 작업은 operator 또는 admin 계정으로 실행하세요.", 4)
        session = self._session(profile)
        if session is None:
            raise ClientError("SESSION_EXPIRED", "다시 로그인하세요.", 3)
        try:
            payload, _ = self._request(profile, method, path, token=session["token"], body=body)
        except ClientError as exc:
            if exc.exit_code == 3:
                self.sessions.delete(session_key(profile))
            raise
        return {**identity, "data": payload["data"], "meta": payload.get("meta", {})}
