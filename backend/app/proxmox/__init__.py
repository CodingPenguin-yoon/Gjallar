"""Read-only Proxmox inventory package for the Gjallar MVP core."""

from app.proxmox.inventory import FakeProxmoxInventoryAdapter, LiveProxmoxInventoryAdapter
from app.proxmox.models import (
    GuestAgentInventory,
    IpEvidenceInventory,
    InventorySnapshot,
    NetworkInventory,
    NicBridgeEvidenceInventory,
    NodeInventory,
    StorageInventory,
    TemplateInventory,
    VmInventory,
)

__all__ = [
    "FakeProxmoxInventoryAdapter",
    "LiveProxmoxInventoryAdapter",
    "GuestAgentInventory",
    "IpEvidenceInventory",
    "InventorySnapshot",
    "NetworkInventory",
    "NicBridgeEvidenceInventory",
    "NodeInventory",
    "StorageInventory",
    "TemplateInventory",
    "VmInventory",
]
