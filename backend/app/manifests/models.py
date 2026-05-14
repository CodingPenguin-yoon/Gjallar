"""Dataclass models for the builtin Gjallar MVP manifests."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class HardwareLimit:
    default: int
    min: int
    max: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class ProfileHardware:
    cpu: HardwareLimit
    memory_mb: HardwareLimit
    disk_gb: HardwareLimit

    def to_dict(self) -> dict[str, dict[str, int]]:
        return {
            "cpu": self.cpu.to_dict(),
            "memory_mb": self.memory_mb.to_dict(),
            "disk_gb": self.disk_gb.to_dict(),
        }


@dataclass(frozen=True)
class AccessDefaults:
    default_user: str
    require_ssh_key: bool = True
    allow_password_login: bool = False
    allow_user_override: bool = True
    ssh_key_source: str = "operator_default_public_key"

    @property
    def cloud_init_user(self) -> str:
        return self.default_user

    @property
    def password_login(self) -> bool:
        return self.allow_password_login

    def to_recommendations_dict(self) -> dict[str, Any]:
        return {
            "default_user": self.default_user,
            "require_ssh_key": self.require_ssh_key,
            "allow_password_login": self.allow_password_login,
            "allow_user_override": self.allow_user_override,
        }


@dataclass(frozen=True)
class TemplateRequirements:
    require_cloud_init: bool = True
    require_qemu_guest_agent: bool = True

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)


@dataclass(frozen=True)
class VmProfile:
    profile_id: str
    display_name: str
    display_name_ko: str
    enabled: bool
    hardware: ProfileHardware
    access: AccessDefaults
    template_requirements: TemplateRequirements = field(default_factory=TemplateRequirements)
    source: str = "static_seed"
    management: str = "read_only"
    target_node_candidates: tuple[str, ...] = ()
    template_family: str = "ubuntu"
    default_ip_mode: str = "static"

    @property
    def create_enabled(self) -> bool:
        return self.enabled

    def to_dict(self) -> dict:
        return {
            "id": self.profile_id,
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "display_name_ko": self.display_name_ko,
            "enabled": self.enabled,
            "create_enabled": self.create_enabled,
            "hardware": self.hardware.to_dict(),
            "template_requirements": self.template_requirements.to_dict(),
            "access_recommendations": self.access.to_recommendations_dict(),
            "source": self.source,
            "management": self.management,
        }


@dataclass(frozen=True)
class NetworkProfile:
    network_id: str
    display_name: str
    node_bridges: dict[str, str]
    allowed_ip_modes: tuple[str, ...] = ("dhcp", "static")
    default_ip_mode: str = "static"
    create_ip_range: str = "192.168.2.140-150"

    def resolve_bridge(self, node_id: str) -> str:
        try:
            return self.node_bridges[node_id]
        except KeyError as exc:
            raise ValueError(
                f"red risk: no bridge mapping for node {node_id!r} in network {self.network_id!r}"
            ) from exc

    def to_dict(self) -> dict:
        data = asdict(self)
        data["allowed_ip_modes"] = list(self.allowed_ip_modes)
        return data


@dataclass(frozen=True)
class TemplateProfile:
    template_id: str
    family: str
    display_name: str
    cloud_init_required: bool = True
    qemu_guest_agent_required: bool = True
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
