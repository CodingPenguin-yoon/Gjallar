"""Authenticated encryption for server-owned Proxmox credentials.

Keys are provisioned separately from the database. This module never creates a
replacement key and never includes secrets or file contents in error messages.
"""

import hashlib
import json
import os
from pathlib import Path
import stat

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CredentialKeyError(RuntimeError):
    pass


class CredentialCipher:
    def __init__(self, key: bytes):
        if len(key) != 32:
            raise CredentialKeyError("인증정보 키는 32바이트여야 합니다.")
        self.key_id = hashlib.sha256(key).hexdigest()
        self._cipher = AESGCM(key)

    @classmethod
    def from_file(cls, path: Path):
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                    raise CredentialKeyError("인증정보 키는 소유자만 읽을 수 있는 일반 파일이어야 합니다.")
                key = stream.read(65)
        except OSError:
            raise CredentialKeyError("인증정보 키를 읽을 수 없습니다. 기존 키 backup을 복원하세요.") from None
        if len(key) == 64:
            try:
                key = bytes.fromhex(key.decode("ascii"))
            except (ValueError, UnicodeError):
                raise CredentialKeyError("인증정보 키 파일 형식이 올바르지 않습니다.") from None
        return cls(key)

    @classmethod
    def configured(cls):
        value = os.environ.get("GJALLAR_CREDENTIAL_KEY_FILE")
        if not value:
            raise CredentialKeyError("GJALLAR_CREDENTIAL_KEY_FILE 설정이 필요합니다.")
        return cls.from_file(Path(value))

    @staticmethod
    def associated_data(*, installation_id, connection_id, revision_id, metadata):
        return json.dumps({
            "format": 1, "installation_id": installation_id,
            "connection_id": connection_id, "revision_id": revision_id,
            "metadata": metadata,
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")

    def encrypt(self, secret: str, **binding):
        if not isinstance(secret, str) or not secret or len(secret) > 4096:
            raise CredentialKeyError("인증정보 형식이 올바르지 않습니다.")
        nonce = os.urandom(12)
        return nonce, self._cipher.encrypt(nonce, secret.encode("utf-8"), self.associated_data(**binding))

    def decrypt(self, *, nonce, ciphertext, key_id, **binding):
        if key_id != self.key_id or len(nonce) != 12:
            raise CredentialKeyError("인증정보 키 또는 저장 형식이 일치하지 않습니다.")
        try:
            return self._cipher.decrypt(nonce, ciphertext, self.associated_data(**binding)).decode("utf-8")
        except (InvalidTag, UnicodeError, ValueError):
            raise CredentialKeyError("인증정보 무결성 검증 실패. DB와 기존 키 backup을 확인하세요.") from None
