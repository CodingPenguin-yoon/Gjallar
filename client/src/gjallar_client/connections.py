"""Non-secret, atomic connection configuration with serialized writers."""
from contextlib import contextmanager
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit
import uuid

from .errors import ClientError


def canonical_origin(value: str) -> str:
    try:
        url = urlsplit(value)
        if (url.scheme not in {"http", "https"} or not url.hostname or url.username
                or url.password or url.query or url.fragment or url.path not in {"", "/"}
                or any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value):
            raise ValueError
        host = url.hostname.lower().encode("idna").decode("ascii")
        if url.scheme == "http":
            if not ipaddress.ip_address(host).is_loopback:
                raise ValueError
        port = url.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        authority = f"[{host}]" if ":" in host else host
        if port and port != {"http": 80, "https": 443}[url.scheme]:
            authority += f":{port}"
        return f"{url.scheme}://{authority}"
    except (ValueError, UnicodeError):
        raise ClientError("INVALID_ORIGIN", "HTTPS 서버 주소 또는 literal loopback HTTP 주소를 입력하세요. 경로·인증정보는 허용하지 않습니다.", 2) from None


def private_directory(path: Path):
    if path.is_symlink():
        raise ClientError("UNSAFE_PATH", "심볼릭 링크 경로는 사용할 수 없습니다.")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise ClientError("UNSAFE_PATH", "현재 사용자 소유의 0700 전용 디렉터리가 필요합니다.")


@contextmanager
def file_lock(path: Path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ClientError("STORAGE_BUSY", "다른 작업이 설정을 사용 중입니다. 완료 후 다시 실행하세요.") from None
        yield
    finally:
        os.close(fd)


def atomic_json(path: Path, value):
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Connections:
    def __init__(self, directory: Path):
        self.directory = directory.expanduser().absolute()
        self.path = self.directory / "connections.json"

    def read(self):
        if not self.path.exists():
            return {"version": 1, "selected": None, "connections": {}}
        try:
            if self.path.is_symlink():
                raise ValueError
            data = json.loads(self.path.read_text())
            if set(data) != {"version", "selected", "connections"} or data["version"] != 1:
                raise ValueError
            if not isinstance(data["connections"], dict):
                raise ValueError
            for name, profile in data["connections"].items():
                self.validate_name(name)
                if set(profile) != {"id", "origin", "cookie_name", "ca_file"}:
                    raise ValueError
                uuid.UUID(profile["id"])
                if canonical_origin(profile["origin"]) != profile["origin"]:
                    raise ValueError
                self.validate_cookie(profile["cookie_name"])
                if profile["ca_file"] is not None and not isinstance(profile["ca_file"], str):
                    raise ValueError
            if data["selected"] is not None and data["selected"] not in data["connections"]:
                raise ValueError
            return data
        except (OSError, ValueError, TypeError, KeyError, AttributeError, ClientError):
            raise ClientError("CONFIG_INVALID", "연결 설정을 읽을 수 없습니다. 원본을 보존하고 복구하세요.") from None

    @staticmethod
    def validate_name(name):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name):
            raise ClientError("INVALID_NAME", "연결 별칭은 영문·숫자·점·밑줄·대시 1~64자입니다.", 2)

    @staticmethod
    def validate_cookie(name):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", name):
            raise ClientError("INVALID_COOKIE", "cookie 이름이 올바르지 않습니다.", 2)

    def update(self, operation):
        try:
            private_directory(self.directory)
            with file_lock(self.directory / ".config.lock"):
                data = self.read()
                result = operation(data)
                atomic_json(self.path, data)
                return result
        except OSError:
            raise ClientError("CONFIG_WRITE_FAILED", "연결 설정 저장 실패. 기존 파일을 보존합니다.") from None

    def add(self, name, origin, cookie_name="gjallar_session", ca_file=None):
        self.validate_name(name)
        self.validate_cookie(cookie_name)
        origin = canonical_origin(origin)
        ca_file = str(Path(ca_file).expanduser().absolute()) if ca_file else None
        def operation(data):
            if name in data["connections"]:
                raise ClientError("CONNECTION_EXISTS", "기존 별칭은 덮어쓰지 않습니다. 새 별칭을 사용하세요.", 2)
            data["connections"][name] = {"id": str(uuid.uuid4()), "origin": origin,
                                          "cookie_name": cookie_name, "ca_file": ca_file}
            return data["connections"][name]
        return self.update(operation)

    def get(self, name=None):
        data = self.read()
        name = name or data["selected"]
        if name not in data["connections"]:
            raise ClientError("NO_CONNECTION", "연결을 추가하고 login 또는 connection use로 선택하세요.", 2)
        return name, data["connections"][name]

    def select(self, name, expected):
        def operation(data):
            if data["connections"].get(name) != expected:
                raise ClientError("CONFIG_CONFLICT", "연결이 변경되었습니다. 다시 선택하세요.")
            data["selected"] = name
        self.update(operation)
