"""Read-only Proxmox inventory package for the Gjallar MVP core."""

from app.proxmox.inventory import FakeProxmoxInventoryAdapter, LiveProxmoxInventoryAdapter
from app.proxmox.models import (
    GuestAgentInventory,
    InventorySnapshot,
    NetworkInventory,
    NodeInventory,
    StorageInventory,
    TemplateInventory,
    VmInventory,
)

__all__ = [
    "FakeProxmoxInventoryAdapter",
    "LiveProxmoxInventoryAdapter",
    "GuestAgentInventory",
    "InventorySnapshot",
    "NetworkInventory",
    "NodeInventory",
    "StorageInventory",
    "TemplateInventory",
    "VmInventory",
]
