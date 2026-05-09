"""Dataclass models for the builtin Gjallar MVP manifests."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class HardwareDefaults:
    cpu: int
    memory_mb: int
    disk_gb: int


@dataclass(frozen=True)
class AccessDefaults:
    cloud_init_user: str
    password_login: bool
    ssh_key_source: str = "operator_default_public_key"


@dataclass(frozen=True)
class ProfileNetworkDefaults:
    network_profile: str
    default_ip_mode: str
    allowed_ip_modes: tuple[str, ...] = ("dhcp", "static")


@dataclass(frozen=True)
class VmProfile:
    profile_id: str
    display_name: str
    create_enabled: bool
    hardware: HardwareDefaults
    access: AccessDefaults
    network: ProfileNetworkDefaults
    target_node_candidates: tuple[str, ...]
    template_family: str

    def to_dict(self) -> dict:
        data = asdict(self)
        data["target_node_candidates"] = list(self.target_node_candidates)
        data["network"]["allowed_ip_modes"] = list(self.network.allowed_ip_modes)
        return data


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
