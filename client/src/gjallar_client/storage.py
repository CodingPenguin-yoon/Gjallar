"""Private, atomic installation files with serialized writers."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile

from .errors import ClientError


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
