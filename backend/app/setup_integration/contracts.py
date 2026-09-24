"""Validated, secret-free inputs for durable setup records."""
import hashlib
import ipaddress
import json
import re
from urllib.parse import urlsplit
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SetupError(RuntimeError):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code = code
        self.status = status


FEATURES = {"read", "power", "compute", "create", "disk", "network", "clone", "delete", "console", "template", "image_build", "image_cleanup", "backup", "restore", "migrate", "host_storage", "host_network"}


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    nodes: list[str] = Field(default_factory=list, max_length=128)
    vmids: list[int] = Field(default_factory=list, max_length=4096)
    template_vmids: list[int] = Field(default_factory=list, max_length=4096)
    restore_vmids: list[int] = Field(default_factory=list, max_length=4096)
    image_vmids: list[int] = Field(default_factory=list, max_length=4096)
    clone_vmids: list[int] = Field(default_factory=list, max_length=4096)
    create_vmids: list[int] = Field(default_factory=list, max_length=4096)
    storages: list[str] = Field(default_factory=list, max_length=128)
    host_storages: list[str] = Field(default_factory=list, max_length=128)
    host_bridges: list[str] = Field(default_factory=list, max_length=128)
    restore_storages: list[str] = Field(default_factory=list, max_length=128)
    backup_storages: list[str] = Field(default_factory=list, max_length=128)
    image_cleanup_storages: list[str] = Field(default_factory=list, max_length=128)
    bridges: list[str] = Field(default_factory=list, max_length=128)

    @field_validator("nodes", "storages", "host_storages", "bridges", "image_cleanup_storages", "backup_storages", "restore_storages")
    @classmethod
    def identifiers(cls, values):
        if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", v) for v in values):
            raise ValueError("Invalid scope identifier")
        return sorted(set(values))

    @field_validator('host_bridges')
    @classmethod
    def host_bridge_identifiers(cls, values):
        if any(not re.fullmatch(r'vmbr[0-9]{1,4}', value) for value in values):
            raise ValueError('Host bridge scope requires vmbrN names')
        return sorted(set(values))

    @field_validator("vmids", "template_vmids", "create_vmids", "clone_vmids", "image_vmids", "restore_vmids")
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
    access_mode: Literal["scoped", "cluster"] = "scoped"
    certificate_sha256: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")
    features: list[str] = Field(default_factory=lambda: ["read"], min_length=1, max_length=17)
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
        if not set(value) <= FEATURES or "read" not in value:
            raise ValueError("Unsupported feature combination")
        return sorted(set(value))

    @model_validator(mode="after")
    def creation_scope(self):
        if self.ca_pem and self.certificate_sha256:
            raise ValueError("Choose CA verification or certificate pinning")
        if self.access_mode == "cluster":
            if self.mode != "issue" or any(self.scope.model_dump().values()):
                raise ValueError("Cluster registration issues a new token without resource lists")
            self.features = sorted(FEATURES)
            return self
        if not self.scope.nodes:
            raise ValueError("Scoped registration requires nodes")
        if ('host_network' in self.features) != bool(self.scope.host_bridges):
            raise ValueError('Host network configuration requires its own explicit bridge scope')
        if ('host_storage' in self.features) != bool(self.scope.host_storages):
            raise ValueError('Host storage configuration requires its own explicit storage ID scope')
        if "migrate" in self.features and (len(self.scope.nodes) < 2 or not all((self.scope.vmids, self.scope.storages, self.scope.bridges))):
            raise ValueError("Migration requires existing VMIDs, two selected nodes, storage and bridge scopes")
        if {"backup", "restore"} & set(self.features):
            if not self.scope.vmids or not self.scope.backup_storages or not set(self.scope.backup_storages) <= set(self.scope.storages):
                raise ValueError("Backup requires existing VMIDs and an explicit subset of selected storages")
        elif self.scope.backup_storages:
            raise ValueError("Backup storage scope requires backup or restore")
        if "restore" in self.features:
            if not all((self.scope.restore_vmids, self.scope.restore_storages, self.scope.bridges)) or not set(self.scope.restore_storages) <= set(self.scope.storages):
                raise ValueError("Restore requires future VMIDs and explicit target storage/bridge scopes")
            existing = set(self.scope.vmids) | set(self.scope.template_vmids) | set(self.scope.create_vmids) | set(self.scope.clone_vmids) | set(self.scope.image_vmids)
            if set(self.scope.restore_vmids) & existing:
                raise ValueError("Restore VMIDs must be separate from every other scope")
        elif self.scope.restore_vmids or self.scope.restore_storages:
            raise ValueError("Restore target scopes require their feature")
        if "image_cleanup" in self.features:
            if not self.scope.vmids or not self.scope.image_cleanup_storages or not set(self.scope.image_cleanup_storages) <= set(self.scope.storages):
                raise ValueError("Image cleanup requires existing VMIDs and an explicit subset of selected storages")
        elif self.scope.image_cleanup_storages:
            raise ValueError("Image cleanup storage scope requires its feature")
        if "image_build" in self.features:
            if not all((self.scope.image_vmids, self.scope.storages, self.scope.bridges)):
                raise ValueError("Image build requires future VMID, storage and bridge scopes")
            other = set(self.scope.vmids) | set(self.scope.template_vmids) | set(self.scope.create_vmids) | set(self.scope.clone_vmids)
            if set(self.scope.image_vmids) & other:
                raise ValueError("Image build VMIDs must be separate from every other scope")
        elif self.scope.image_vmids:
            raise ValueError("Image build target scope requires its feature")
        if "clone" in self.features:
            if not all((self.scope.vmids, self.scope.clone_vmids, self.scope.storages, self.scope.bridges)):
                raise ValueError("Clone requires explicit source VM, new VMID, storage and bridge scopes")
            if set(self.scope.clone_vmids) & (set(self.scope.vmids) | set(self.scope.template_vmids) | set(self.scope.create_vmids)):
                raise ValueError("Clone target IDs must be distinct from source, template and creation scopes")
        elif self.scope.clone_vmids:
            raise ValueError("Clone target scope requires the clone feature")
        if "network" in self.features and not self.scope.bridges:
            raise ValueError("Network changes require explicit bridge scope")
        if "template" in self.features and not all((self.scope.vmids, self.scope.storages)):
            raise ValueError("Template conversion requires existing VM and storage scopes")
        if "delete" in self.features and not self.scope.storages:
            raise ValueError("Deletion requires explicit storage scope for volume verification")
        if "disk" in self.features and not self.scope.storages:
            raise ValueError("Disk expansion requires explicit storage scope")
        if "create" in self.features:
            if not all((self.scope.template_vmids, self.scope.create_vmids, self.scope.storages, self.scope.bridges)):
                raise ValueError("Creation requires explicit template, target VMID, storage and bridge scopes")
            if set(self.scope.create_vmids) & (set(self.scope.vmids) | set(self.scope.template_vmids)):
                raise ValueError("Creation targets must be separate from existing VM and template scopes")
        elif self.scope.create_vmids or self.scope.template_vmids:
            raise ValueError("Creation scopes require the create feature")
        return self


def permitted_address(address):
    if getattr(address, "ipv4_mapped", None) is not None:
        address = address.ipv4_mapped
    return not (address.is_loopback or address.is_link_local or address.is_multicast
                or address.is_unspecified or address.is_reserved)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
