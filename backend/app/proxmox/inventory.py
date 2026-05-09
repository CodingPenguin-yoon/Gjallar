"""Fake/read-only Proxmox inventory adapter for Set 5.

The adapter is deliberately read-only and fixture-backed. It gives the /api/v1
core a stable contract for nodes, VMs, templates, storage, networks,
guest-agent, and IP observations without touching a live Proxmox cluster.
"""

from __future__ import annotations

from typing import Any

from app.core.redaction import redact_secrets
from app.proxmox.models import (
    GuestAgentInventory,
    InventorySnapshot,
    NetworkInventory,
    NodeInventory,
    StorageInventory,
    TemplateInventory,
    VmInventory,
)


class FakeProxmoxInventoryAdapter:
    """Fixture-backed read-only inventory adapter for tests and dev mode."""

    source = "fake_read_only"

    def __init__(
        self,
        *,
        source_config: dict[str, Any] | None = None,
        observed_at: str = "2026-05-09T02:38:00+09:00",
    ) -> None:
        self._source_config = dict(source_config or {"mode": self.source})
        self._observed_at = observed_at
        self._storages = (
            StorageInventory(
                storage_id="local-lvm",
                node_id="yoonmanserver2",
                type="lvmthin",
                total_gb=512,
                free_gb=240,
                content=("images", "rootdir"),
            ),
            StorageInventory(
                storage_id="local-lvm",
                node_id="yoonmanserver3",
                type="lvmthin",
                total_gb=512,
                free_gb=256,
                content=("images", "rootdir"),
            ),
        )
        self._networks = (
            NetworkInventory(bridge_id="vmbr0", node_id="yoonmanserver2"),
            NetworkInventory(bridge_id="vmbr0", node_id="yoonmanserver3"),
        )
        self._nodes = (
            NodeInventory(
                node_id="yoonmanserver2",
                display_name="yoonmanserver2",
                status="online",
                cpu_total=16,
                memory_total_mb=65536,
                storage=tuple(item for item in self._storages if item.node_id == "yoonmanserver2"),
                networks=tuple(item for item in self._networks if item.node_id == "yoonmanserver2"),
            ),
            NodeInventory(
                node_id="yoonmanserver3",
                display_name="yoonmanserver3",
                status="online",
                cpu_total=16,
                memory_total_mb=65536,
                storage=tuple(item for item in self._storages if item.node_id == "yoonmanserver3"),
                networks=tuple(item for item in self._networks if item.node_id == "yoonmanserver3"),
            ),
        )
        self._templates = (
            TemplateInventory(
                template_id="ubuntu-template",
                vmid=9000,
                name="ubuntu-cloudinit-template",
                node_id="yoonmanserver2",
                storage_id="local-lvm",
                family="ubuntu",
                cloud_init_ready=True,
                guest_agent_ready=True,
            ),
        )
        self._vms = (
            VmInventory(
                vmid=101,
                name="gjallar-fixture-vm",
                node_id="yoonmanserver2",
                status="running",
                template=False,
                cpu=2,
                memory_mb=4096,
                disk_gb=40,
                ip_addresses=("192.168.2.141",),
                guest_agent=GuestAgentInventory(available=True, ip_addresses=("192.168.2.141",)),
                tags=("gjallar", "fixture"),
            ),
        )

    def redacted_connection_context(self) -> dict[str, Any]:
        return redact_secrets({"source": self.source, **self._source_config})

    def snapshot(self) -> InventorySnapshot:
        return InventorySnapshot(
            source=self.source,
            observed_at=self._observed_at,
            nodes=self._nodes,
            vms=self._vms,
            templates=self._templates,
            connection=self.redacted_connection_context(),
        )

    def list_nodes(self) -> list[NodeInventory]:
        return list(self._nodes)

    def list_vms(self) -> list[VmInventory]:
        return list(self._vms)

    def get_vm(self, vmid: int) -> VmInventory | None:
        for vm in self._vms:
            if vm.vmid == vmid:
                return vm
        return None

    def list_templates(self) -> list[TemplateInventory]:
        return list(self._templates)

    def list_storage(self, node_id: str | None = None) -> list[StorageInventory]:
        if node_id is None:
            return list(self._storages)
        return [storage for storage in self._storages if storage.node_id == node_id]

    def list_networks(self, node_id: str | None = None) -> list[NetworkInventory]:
        if node_id is None:
            return list(self._networks)
        return [network for network in self._networks if network.node_id == node_id]


def get_default_inventory_adapter() -> FakeProxmoxInventoryAdapter:
    """Return the current non-mutating inventory adapter for /api/v1."""
    return FakeProxmoxInventoryAdapter()
