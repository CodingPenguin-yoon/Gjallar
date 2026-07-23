"""Composition facade for current Insights read sources."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from app.insights.application import InsightsQueryService
from app.insights.placement import build_placement_model
from app.insights.ports import InventoryInsightSource
from app.jobs.runs import list_job_runs_strict
from app.workloads.inventory import get_default_workload_inventory_query


class _InventoryPort:
    def observe(self) -> InventoryInsightSource:
        observation = get_default_workload_inventory_query().observe()
        snapshot = observation.snapshot.to_dict() if observation.snapshot is not None else None
        return InventoryInsightSource(
            connection=observation.status.to_dict(),
            snapshot=snapshot,
        )


class _RiskPort:
    def list_jobs(self) -> Sequence[Mapping[str, Any]]:
        return list_job_runs_strict()


class _MappingInventoryAdapter:
    def __init__(self, snapshot: Mapping[str, Any]) -> None:
        self._snapshot = dict(snapshot)
        self.source = str(self._snapshot.get("source") or "proxmox_inventory")
        connection = self._snapshot.get("connection") if isinstance(self._snapshot.get("connection"), Mapping) else {}
        self.cluster_id = str(connection.get("cluster_id") or "gjallar-mvp")

    def snapshot(self) -> Mapping[str, Any]:
        return self._snapshot

    def list_nodes(self) -> list[Mapping[str, Any]]:
        return [dict(item) for item in self._snapshot.get("nodes") or [] if isinstance(item, Mapping)]

    def list_vms(self) -> list[Mapping[str, Any]]:
        return [dict(item) for item in self._snapshot.get("vms") or [] if isinstance(item, Mapping)]

    def list_storage(self, node_id: str | None = None) -> list[Mapping[str, Any]]:
        items: list[Mapping[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for node in self.list_nodes():
            current_node = str(node.get("node_id") or node.get("id") or "unknown")
            if node_id is not None and current_node != node_id:
                continue
            for value in node.get("storage") or []:
                if not isinstance(value, Mapping):
                    continue
                item = {**dict(value), "node_id": value.get("node_id") or current_node}
                key = (str(item.get("node_id") or ""), str(item.get("storage_id") or item.get("id") or ""))
                if key in seen:
                    continue
                seen.add(key)
                items.append(item)
        return items

    def list_networks(self, node_id: str | None = None) -> list[Mapping[str, Any]]:
        items: list[Mapping[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for node in self.list_nodes():
            current_node = str(node.get("node_id") or node.get("id") or "unknown")
            if node_id is not None and current_node != node_id:
                continue
            for value in node.get("networks") or []:
                if not isinstance(value, Mapping):
                    continue
                item = {**dict(value), "node_id": value.get("node_id") or current_node}
                key = (str(item.get("node_id") or ""), str(item.get("bridge_id") or item.get("id") or ""))
                if key in seen:
                    continue
                seen.add(key)
                items.append(item)
        return items


class _PlacementPort:
    def build(
        self,
        snapshot: Mapping[str, Any],
        risks: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        return build_placement_model(
            _MappingInventoryAdapter(snapshot),
            risks=list(risks),
        )


def get_insights() -> dict[str, Any]:
    service = InsightsQueryService(
        inventory=_InventoryPort(),
        risks=_RiskPort(),
        placement=_PlacementPort(),
    )
    return service.query().to_dict()
