"""Only an OS vault or explicitly selected process memory may hold cookies."""
import json
from datetime import datetime, timezone

from .errors import ClientError


class MemoryStore:
    mode = "memory"

    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


class KeyringStore:
    mode = "keyring"
    allowed = {("keyring.backends.macOS", "Keyring"), ("keyring.backends.SecretService", "Keyring")}

    def __init__(self, backend=None):
        try:
            if backend is None:
                import keyring
                backend = keyring.get_keyring()
            if (type(backend).__module__, type(backend).__name__) not in self.allowed:
                raise ValueError
            self.backend = backend
        except Exception:
            # Discovery also invokes OS/plugin code; fail closed at that boundary.
            raise self.unavailable() from None

    @staticmethod
    def unavailable():
        return ClientError("KEYRING_UNAVAILABLE", "OS keyring을 사용할 수 없습니다. 잠금을 해제하거나 --session-mode memory tui를 명시적으로 사용하세요. 평문 저장은 하지 않습니다.")

    def _call(self, action, key, value=None):
        # OS backend errors have platform-specific types and can include secrets.
        # Normalize only at this external boundary, without fallback or raw output.
        try:
            service = "org.gjallar.client"
            if action == "get":
                raw = self.backend.get_password(service, key)
                return json.loads(raw) if raw else None
            if action == "set":
                self.backend.set_password(service, key, json.dumps(value))
            elif self.backend.get_password(service, key) is not None:
                self.backend.delete_password(service, key)
        except Exception:
            raise self.unavailable() from None

    def get(self, key):
        return self._call("get", key)

    def set(self, key, value):
        self._call("set", key, value)

    def delete(self, key):
        self._call("delete", key)


def session_key(profile):
    return f'{profile["id"]}|{profile["origin"]}|{profile["cookie_name"]}'


def unexpired(value):
    try:
        if not isinstance(value, dict) or set(value) != {"token", "expires_at", "username"} or not isinstance(value["token"], str) or not value["token"]:
            raise ValueError
        expiry = datetime.fromisoformat(value["expires_at"])
        return expiry > datetime.now(timezone.utc)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ClientError("SESSION_INVALID", "보관된 session이 손상되었습니다. logout 후 다시 로그인하세요.") from None
