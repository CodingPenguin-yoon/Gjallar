"""Password hashing with stdlib PBKDF2-HMAC-SHA256."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

HASH_NAME = "pbkdf2_sha256"
HASH_VERSION = "v1"
DEFAULT_ITERATIONS = 600_000
MIN_ITERATIONS = 1_000
SALT_BYTES = 16
MAX_PASSWORD_BYTES = 1024


def _iterations() -> int:
    raw = str(os.getenv("GJALLAR_PASSWORD_HASH_ITERATIONS", "")).strip()
    if not raw:
        return DEFAULT_ITERATIONS
    try:
        return max(MIN_ITERATIONS, int(raw))
    except ValueError:
        return DEFAULT_ITERATIONS


def _password_bytes(password: str) -> bytes:
    encoded = str(password).encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError("Password exceeds the maximum supported length")
    return encoded


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def hash_password(password: str) -> str:
    password_bytes = _password_bytes(password)
    salt = secrets.token_bytes(SALT_BYTES)
    iterations = _iterations()
    digest = hashlib.pbkdf2_hmac("sha256", password_bytes, salt, iterations)
    return "$".join([HASH_NAME, HASH_VERSION, str(iterations), _b64encode(salt), _b64encode(digest)])


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        password_bytes = _password_bytes(password)
        name, version, iterations_text, salt_text, digest_text = str(stored_hash or "").split("$", 4)
        if name != HASH_NAME or version != HASH_VERSION:
            return False
        iterations = int(iterations_text)
        if iterations < MIN_ITERATIONS:
            return False
        salt = _b64decode(salt_text)
        expected = _b64decode(digest_text)
    except (ValueError, TypeError):
        return False

    actual = hashlib.pbkdf2_hmac("sha256", password_bytes, salt, iterations)
    return hmac.compare_digest(actual, expected)
