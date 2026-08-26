"""Read-only Proxmox inventory dataclasses.

These models intentionally describe observed inventory only. They do not expose
create/apply/delete/power operations; later Sets may add live read adapters
behind the same read-only shape and separate safety tests.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


_INVENTORY_SOURCE_NAMES = ("storage", "network", "vm_config", "guest_agent", "vm_detail")


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
    address: str = ""
    netmask: str = ""
    prefix: int | None = None
    cidr: str = ""
    gateway: str = ""
    bridge_ports: tuple[str, ...] = ()
    vlan_aware: bool | None = None
    mtu: int | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["bridge_ports"] = list(self.bridge_ports)
        return data


@dataclass(frozen=True)
class GuestAgentInventory:
    available: bool
    ip_addresses: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ip_addresses"] = list(self.ip_addresses)
        return data


@dataclass(frozen=True)
class IpEvidenceInventory:
    ip_address: str
    source: str
    interface_name: str = ""
    interface_type: str = ""
    scope: str = "observed"
    primary_candidate: bool = False
    duplicate_warning_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NicBridgeEvidenceInventory:
    interface_name: str
    bridge_id: str
    source: str = "config"
    interface_type: str = "proxmox_net_config"
    model: str = ""
    mac_address: str = ""
    tag: str = ""
    firewall: bool | None = None
    link_down: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    ip_evidence: tuple[IpEvidenceInventory, ...] = ()
    nic_bridge_evidence: tuple[NicBridgeEvidenceInventory, ...] = ()
    guest_agent: GuestAgentInventory = field(default_factory=lambda: GuestAgentInventory(False))
    tags: tuple[str, ...] = ()
    storage_id: str = "unknown"
    disks: tuple[DiskInventory, ...] = ()
    smbios1: str = ""
    vmgenid: str = ""
    mac_addresses: tuple[str, ...] = ()
    config_lock: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ip_addresses"] = list(self.ip_addresses)
        data["ip_evidence"] = [item.to_dict() for item in self.ip_evidence]
        data["nic_bridge_evidence"] = [item.to_dict() for item in self.nic_bridge_evidence]
        data["guest_agent"] = self.guest_agent.to_dict()
        data["tags"] = list(self.tags)
        data["disks"] = [disk.to_dict() for disk in self.disks]
        data["mac_addresses"] = list(self.mac_addresses)
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
    cpu: int = 0
    memory_mb: int = 0
    disk_gb: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InventorySourceAvailability:
    """Availability and completeness of one optional snapshot sub-source."""

    source: str
    expected_targets: int = 0
    observed_targets: int = 0
    failed_targets: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self.expected_targets == 0 or self.observed_targets > 0

    @property
    def complete(self) -> bool:
        return not self.failed_targets and self.observed_targets >= self.expected_targets

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "complete": self.complete,
            "expected_targets": self.expected_targets,
            "observed_targets": self.observed_targets,
            "failed_targets": list(self.failed_targets),
        }


@dataclass(frozen=True)
class InventoryAvailability:
    """Completeness of an existing base snapshot.

    A missing base snapshot is represented by no ``InventorySnapshot`` and a
    503 response. Therefore ``available`` is true whenever this value exists,
    while ``complete`` and each source describe partial observations.
    """

    sources: tuple[InventorySourceAvailability, ...] = ()

    @property
    def available(self) -> bool:
        return True

    @property
    def complete(self) -> bool:
        return all(source.complete for source in self.sources)

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "complete": self.complete,
            "sources": {source.source: source.to_dict() for source in self.sources},
        }


def complete_inventory_availability() -> InventoryAvailability:
    return InventoryAvailability(
        sources=tuple(InventorySourceAvailability(source=name) for name in _INVENTORY_SOURCE_NAMES)
    )


@dataclass(frozen=True)
class InventorySnapshot:
    source: str
    observed_at: str
    nodes: tuple[NodeInventory, ...]
    vms: tuple[VmInventory, ...]
    templates: tuple[TemplateInventory, ...]
    connection: dict[str, Any] = field(default_factory=dict)
    availability: InventoryAvailability = field(default_factory=complete_inventory_availability)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "observed_at": self.observed_at,
            "nodes": [node.to_dict() for node in self.nodes],
            "vms": [vm.to_dict() for vm in self.vms],
            "templates": [template.to_dict() for template in self.templates],
            "connection": self.connection,
            "availability": self.availability.to_dict(),
        }
