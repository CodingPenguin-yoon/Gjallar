"""Secret redaction helpers for logs, artifacts, and API payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from re import compile, sub
from typing import Any

REDACTED = "[REDACTED]"
_SECRET_KEY_MARKERS = (
    "secret",
    "token",
    "password",
    "passwd",
    "private_key",
    "credential",
    "database_url",
    "connection_string",
)
_SECRET_EXACT_KEYS = {
    "sshkeys",
    "sshkey",
    "ssh_public_key",
    "sshpublickey",
    "public_key",
    "publickey",
}
_SAFE_KEYS = {"password_login"}
_SSH_PUBLIC_KEY_VALUE_PATTERN = compile(
    r"(?m)(?:^|\s)((?:sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com|ssh-ed25519|ssh-rsa|rsa-sha2-256|rsa-sha2-512|ecdsa-sha2-[A-Za-z0-9@._+-]+)\s+[A-Za-z0-9+/=]+(?:\s+[^\r\n]+)?)"
)


def _is_secret_key(key: Any) -> bool:
    normalized = str(key).replace("-", "_").lower()
    compact = normalized.replace("_", "")
    if normalized in _SAFE_KEYS:
        return False
    if normalized in _SECRET_EXACT_KEYS or compact in _SECRET_EXACT_KEYS:
        return True
    return any(marker in normalized for marker in _SECRET_KEY_MARKERS)


def _redact_string(value: str) -> str:
    """Mask credential material embedded in URLs or key/value-like strings."""
    value = _SSH_PUBLIC_KEY_VALUE_PATTERN.sub("[REDACTED_SSH_PUBLIC_KEY]", value)
    if "://" in value and "@" in value:
        return sub(
            r"(://[^:/@]+:)[^@]+(@)",
            lambda match: f"{match.group(1)}{REDACTED}{match.group(2)}",
            value,
        )
    lowered = value.lower()
    if any(marker in lowered for marker in _SECRET_KEY_MARKERS):
        return REDACTED
    return value


def redact_secrets(value: Any) -> Any:
    """Recursively replace secret-looking values with a safe marker.

    Keys that identify tokens, passwords, connection strings, or credentialed
    URLs are redacted as whole values. Containers preserve their shape so call
    sites can safely serialize the result for artifacts or API responses.
    """
    if isinstance(value, Mapping):
        return {
            key: REDACTED if _is_secret_key(key) else redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(redact_secrets(item) for item in value)
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, set):
        return {redact_secrets(item) for item in value}
    if isinstance(value, str):
        return _redact_string(value)
    return value
