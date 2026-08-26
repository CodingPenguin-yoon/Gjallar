"""Application query boundary for authoritative Proxmox workload inventory."""

from __future__ import annotations

from typing import Any

from app.proxmox import inventory as proxmox_inventory
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


def get_default_workload_inventory_query() -> WorkloadInventoryQuery:
    return WorkloadInventoryQuery(proxmox_inventory.get_default_inventory_adapter())
