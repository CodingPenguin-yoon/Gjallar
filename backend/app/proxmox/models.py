"""Read-only Proxmox inventory dataclasses.

These models intentionally describe observed inventory only. They do not expose
create/apply/delete/power operations; later Sets may add live read adapters
behind the same read-only shape and separate safety tests.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class StorageInventory:
    storage_id: str
    node_id: str
    type: str
    total_gb: int
    free_gb: int
    content: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["content"] = list(self.content)
        return data


@dataclass(frozen=True)
class NetworkInventory:
    bridge_id: str
    node_id: str
    type: str = "bridge"
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GuestAgentInventory:
    available: bool
    ip_addresses: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ip_addresses"] = list(self.ip_addresses)
        return data


@dataclass(frozen=True)
class DiskInventory:
    device: str
    bus: str
    index: int
    size_gb: float
    storage_id: str
    volume_id: str
    volume: str
    boot: bool = False
    format: str = ""
    cache: str = ""
    discard: str = ""
    iothread: str = ""
    ssd: str = ""
    backup: str = ""
    readonly: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NodeInventory:
    node_id: str
    display_name: str
    status: str
    cpu_total: int
    memory_total_mb: int
    cpu_usage_percent: float = 0.0
    memory_used_mb: int = 0
    memory_usage_percent: float = 0.0
    storage: tuple[StorageInventory, ...] = ()
    networks: tuple[NetworkInventory, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["storage"] = [item.to_dict() for item in self.storage]
        data["networks"] = [item.to_dict() for item in self.networks]
        return data


@dataclass(frozen=True)
class VmInventory:
    vmid: int
    name: str
    node_id: str
    status: str
    template: bool
    cpu: int
    memory_mb: int
    disk_gb: int
    ip_addresses: tuple[str, ...] = ()
    guest_agent: GuestAgentInventory = field(default_factory=lambda: GuestAgentInventory(False))
    tags: tuple[str, ...] = ()
    storage_id: str = "unknown"
    disks: tuple[DiskInventory, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ip_addresses"] = list(self.ip_addresses)
        data["guest_agent"] = self.guest_agent.to_dict()
        data["tags"] = list(self.tags)
        data["disks"] = [disk.to_dict() for disk in self.disks]
        return data


@dataclass(frozen=True)
class TemplateInventory:
    template_id: str
    vmid: int
    name: str
    node_id: str
    storage_id: str
    family: str
    cloud_init_ready: bool
    guest_agent_ready: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InventorySnapshot:
    source: str
    observed_at: str
    nodes: tuple[NodeInventory, ...]
    vms: tuple[VmInventory, ...]
    templates: tuple[TemplateInventory, ...]
    connection: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "observed_at": self.observed_at,
            "nodes": [node.to_dict() for node in self.nodes],
            "vms": [vm.to_dict() for vm in self.vms],
            "templates": [template.to_dict() for template in self.templates],
            "connection": self.connection,
        }
