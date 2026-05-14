"""Access and SSH public key helpers for Create VM."""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SSH_PUBLIC_KEY_ENV = "GJALLAR_DEFAULT_SSH_PUBLIC_KEY"
DEFAULT_SSH_PUBLIC_KEY_FILE_ENV = "GJALLAR_DEFAULT_SSH_PUBLIC_KEY_FILE"

_PRIVATE_KEY_MARKERS = (
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "-----BEGIN RSA PRIVATE KEY-----",
    "-----BEGIN DSA PRIVATE KEY-----",
    "-----BEGIN EC PRIVATE KEY-----",
    "-----BEGIN PRIVATE KEY-----",
    "PRIVATE KEY",
)
_KEY_TYPE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@+-]*$")


@dataclass(frozen=True)
class SshPublicKeyValidation:
    valid: bool
    supplied: bool
    fingerprint: str | None = None
    key_type: str | None = None
    error_code: str | None = None
    message: str = ""
    _normalized_public_key: str = field(default="", repr=False, compare=False)

    @property
    def normalized_public_key(self) -> str:
        return self._normalized_public_key if self.valid else ""

    def safe_detail(self) -> dict[str, object]:
        return {
            "ssh_key_present": self.supplied,
            "ssh_key_valid": self.valid,
            "fingerprint": self.fingerprint,
            "key_type": self.key_type,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class ResolvedSshPublicKey:
    source: str
    validation: SshPublicKeyValidation

    @property
    def transient_public_key(self) -> str:
        return self.validation.normalized_public_key


def _missing_validation(message: str = "SSH public key is not configured") -> SshPublicKeyValidation:
    return SshPublicKeyValidation(
        valid=False,
        supplied=False,
        error_code="ssh_public_key_missing",
        message=message,
    )


def _invalid_validation(*, supplied: bool = True, code: str, message: str) -> SshPublicKeyValidation:
    return SshPublicKeyValidation(
        valid=False,
        supplied=supplied,
        error_code=code,
        message=message,
    )


def _decode_blob(encoded: str) -> bytes | None:
    try:
        return base64.b64decode(encoded.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError, ValueError):
        return None


def _read_ssh_string(blob: bytes, offset: int = 0) -> tuple[bytes, int] | None:
    if offset + 4 > len(blob):
        return None
    length = struct.unpack(">I", blob[offset : offset + 4])[0]
    start = offset + 4
    end = start + length
    if length <= 0 or end > len(blob):
        return None
    return blob[start:end], end


def validate_ssh_public_key(value: object) -> SshPublicKeyValidation:
    """Validate an OpenSSH public key and compute its SHA256 fingerprint."""
    text = str(value or "").strip()
    if not text:
        return _missing_validation()

    upper_text = text.upper()
    if any(marker in upper_text for marker in _PRIVATE_KEY_MARKERS):
        return _invalid_validation(
            code="ssh_private_key_not_allowed",
            message="SSH private key material is not allowed",
        )

    parts = text.split()
    if len(parts) < 2:
        return _invalid_validation(
            code="ssh_public_key_malformed",
            message="SSH public key must use OpenSSH '<type> <base64>' format",
        )

    key_type = parts[0].strip()
    encoded = parts[1].strip()
    if not _KEY_TYPE_PATTERN.fullmatch(key_type):
        return _invalid_validation(
            code="ssh_public_key_malformed",
            message="SSH public key type is malformed",
        )

    blob = _decode_blob(encoded)
    if not blob:
        return _invalid_validation(
            code="ssh_public_key_malformed",
            message="SSH public key blob is malformed",
        )

    parsed = _read_ssh_string(blob)
    if parsed is None:
        return _invalid_validation(
            code="ssh_public_key_malformed",
            message="SSH public key blob is incomplete",
        )
    parsed_type_bytes, offset = parsed
    try:
        parsed_type = parsed_type_bytes.decode("ascii")
    except UnicodeDecodeError:
        return _invalid_validation(
            code="ssh_public_key_malformed",
            message="SSH public key blob type is malformed",
        )
    if parsed_type != key_type:
        return _invalid_validation(
            code="ssh_public_key_malformed",
            message="SSH public key type does not match the encoded blob",
        )

    if key_type == "ssh-ed25519":
        parsed_public_key = _read_ssh_string(blob, offset)
        if parsed_public_key is None or len(parsed_public_key[0]) != 32:
            return _invalid_validation(
                code="ssh_public_key_malformed",
                message="SSH ed25519 public key blob is malformed",
            )

    fingerprint = base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii").rstrip("=")
    return SshPublicKeyValidation(
        valid=True,
        supplied=True,
        fingerprint=f"SHA256:{fingerprint}",
        key_type=key_type,
        _normalized_public_key=f"{key_type} {encoded}",
    )


def resolve_ssh_public_key(request_value: object = None) -> ResolvedSshPublicKey:
    """Resolve a request key or backend default without exposing raw key material."""
    request_text = str(request_value or "").strip()
    if request_text:
        return ResolvedSshPublicKey(
            source="request",
            validation=validate_ssh_public_key(request_text),
        )

    env_text = os.getenv(DEFAULT_SSH_PUBLIC_KEY_ENV, "").strip()
    if env_text:
        return ResolvedSshPublicKey(
            source="backend_default_env",
            validation=validate_ssh_public_key(env_text),
        )

    key_path = os.getenv(DEFAULT_SSH_PUBLIC_KEY_FILE_ENV, "").strip()
    if key_path:
        path = Path(key_path).expanduser()
        if path.is_file():
            return ResolvedSshPublicKey(
                source="backend_default_file",
                validation=validate_ssh_public_key(path.read_text(encoding="utf-8").strip()),
            )
        return ResolvedSshPublicKey(
            source="backend_default_file",
            validation=_invalid_validation(
                supplied=False,
                code="ssh_public_key_file_missing",
                message="Configured SSH public key file does not exist",
            ),
        )

    return ResolvedSshPublicKey(source="missing", validation=_missing_validation())
