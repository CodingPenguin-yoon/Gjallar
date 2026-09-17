"""Validated, secret-free inputs for durable setup records."""
import hashlib
import ipaddress
import json
import re
from urllib.parse import urlsplit
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SetupError(RuntimeError):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code = code
        self.status = status


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    nodes: list[str] = Field(min_length=1, max_length=128)
    vmids: list[int] = Field(default_factory=list, max_length=4096)
    storages: list[str] = Field(default_factory=list, max_length=128)
    bridges: list[str] = Field(default_factory=list, max_length=128)

    @field_validator("nodes", "storages", "bridges")
    @classmethod
    def identifiers(cls, values):
        if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", v) for v in values):
            raise ValueError("Invalid scope identifier")
        return sorted(set(values))

    @field_validator("vmids")
    @classmethod
    def vm_ids(cls, values):
        if any(not 100 <= value <= 999999999 for value in values):
            raise ValueError("Invalid VMID")
        return sorted(set(values))


class RegistrationIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    endpoint: str = Field(max_length=512)
    ca_pem: str = Field(default="", max_length=65536)
    owner: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}@(pam|pve)$")
    scope: Scope
    features: list[str] = Field(default_factory=lambda: ["read"], min_length=1, max_length=3)
    expires_at: int = Field(gt=0)
    mode: Literal["issue", "import_env"] = "issue"

    @field_validator("endpoint")
    @classmethod
    def endpoint_origin(cls, value):
        try:
            parsed = urlsplit(value)
            port = parsed.port if parsed.port is not None else 8006
            host = parsed.hostname
            if (parsed.scheme != "https" or not host or not 1 <= port <= 65535 or parsed.username is not None
                    or parsed.password is not None or parsed.query or parsed.fragment
                    or parsed.path not in {"", "/", "/api2/json", "/api2/json/"}
                    or any(ord(c) <= 32 or ord(c) >= 127 for c in value)
                    or "\\" in value or "%" in host):
                raise ValueError
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                if not re.fullmatch(r"[A-Za-z0-9.-]+", host) or host.lower().rstrip(".") == "localhost":
                    raise ValueError
            else:
                if not permitted_address(address):
                    raise ValueError
            authority = f"[{host}]" if ":" in host else host.lower().rstrip(".")
            return f"https://{authority}:{port}/api2/json"
        except ValueError:
            raise ValueError("A verified HTTPS Proxmox endpoint is required") from None

    @field_validator("ca_pem")
    @classmethod
    def certificate(cls, value):
        if value:
            from cryptography.x509 import load_pem_x509_certificates
            if "PRIVATE KEY" in value or not value.strip().startswith("-----BEGIN CERTIFICATE-----"):
                raise ValueError("Only public CA certificates are accepted")
            try:
                if not load_pem_x509_certificates(value.encode("ascii")):
                    raise ValueError
            except (ValueError, UnicodeError):
                raise ValueError("Invalid public CA certificate") from None
        return value

    @field_validator("features")
    @classmethod
    def supported_features(cls, value):
        if not set(value) <= {"read", "power"} or "read" not in value:
            raise ValueError("Unsupported feature combination")
        return sorted(set(value))


def permitted_address(address):
    if getattr(address, "ipv4_mapped", None) is not None:
        address = address.ipv4_mapped
    return not (address.is_loopback or address.is_link_local or address.is_multicast
                or address.is_unspecified or address.is_reserved)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
