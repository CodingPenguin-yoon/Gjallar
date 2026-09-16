"""Application query boundary for authoritative Proxmox workload inventory."""

from __future__ import annotations

from typing import Any

from app.proxmox import inventory as proxmox_inventory
from app.proxmox.models import InventorySnapshot
from app.setup_integration.proxmox_connection import ProxmoxConnectionObservation, observe_proxmox_connection


class WorkloadInventoryUnavailableError(RuntimeError):
    def __init__(self, observation: ProxmoxConnectionObservation) -> None:
        self.observation = observation
        self.status = observation.status
        self.code = (
            "PROXMOX_INVENTORY_UNCONFIGURED"
            if observation.status.state == "unconfigured"
            else "PROXMOX_INVENTORY_DEGRADED"
        )
        self.message = (
            "Proxmox inventory is not configured"
            if observation.status.state == "unconfigured"
            else "Proxmox inventory is temporarily unavailable"
        )
        super().__init__(self.message)

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "connection": self.status.to_dict(),
            "proxmox_mutation_enabled": False,
            "side_effects": [],
        }


class ObservedInventoryAdapter:
    """Read-only view pinned to one validated request-scoped observation."""

    def __init__(self, snapshot: InventorySnapshot, *, is_test_fixture: bool = False) -> None:
        self._snapshot = snapshot
        self.source = snapshot.source
        self.is_test_fixture = is_test_fixture

    def snapshot(self) -> InventorySnapshot:
        return self._snapshot

    def list_nodes(self):
        return list(self._snapshot.nodes)

    def list_vms(self):
        return list(self._snapshot.vms)

    def list_templates(self):
        return list(self._snapshot.templates)

    def list_storage(self, node_id=None):
        return [item for node in self._snapshot.nodes if node_id is None or node.node_id == node_id for item in node.storage]

    def list_networks(self, node_id=None):
        return [item for node in self._snapshot.nodes if node_id is None or node.node_id == node_id for item in node.networks]


class WorkloadInventoryQuery:
    def __init__(self, adapter: Any) -> None:
        self.adapter = adapter

    def observe(self) -> ProxmoxConnectionObservation:
        return observe_proxmox_connection(self.adapter)

    def require_observation(self) -> ProxmoxConnectionObservation:
        observation = self.observe()
        if observation.snapshot is None:
            raise WorkloadInventoryUnavailableError(observation)
        return observation

    def require_adapter(self) -> Any:
        self.require_observation()
        return self.adapter

    def require_mutation_adapter(self) -> Any:
        observation = self.require_observation()
        if (
            observation.status.state not in {"live", "test_fixture"}
            or not observation.snapshot.availability.complete
        ):
            raise WorkloadInventoryUnavailableError(observation)
        return self.adapter

    def require_create_adapter(self, *, fresh: bool = False) -> Any:
        observation = observe_proxmox_connection(self.adapter, fresh=fresh)
        if (
            observation.snapshot is None
            or any(not source.complete for source in observation.snapshot.availability.sources
                   if source.source != "guest_agent")
        ):
            raise WorkloadInventoryUnavailableError(observation)
        if not fresh:
            return self.adapter
        return ObservedInventoryAdapter(
            observation.snapshot,
            is_test_fixture=bool(getattr(self.adapter, "is_test_fixture", False)),
        )

    def require_fresh_mutation_adapter(self) -> ObservedInventoryAdapter:
        observation = observe_proxmox_connection(self.adapter, fresh=True)
        if (
            observation.snapshot is None
            or observation.status.state not in {"live", "test_fixture"}
            or not observation.snapshot.availability.complete
        ):
            raise WorkloadInventoryUnavailableError(observation)
        return ObservedInventoryAdapter(
            observation.snapshot,
            is_test_fixture=bool(getattr(self.adapter, "is_test_fixture", False)),
        )


def get_default_workload_inventory_query() -> WorkloadInventoryQuery:
    return WorkloadInventoryQuery(proxmox_inventory.get_default_inventory_adapter())
