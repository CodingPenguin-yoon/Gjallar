"""Read ports used by the Insights application service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class InventoryInsightSource:
    connection: Mapping[str, Any]
    snapshot: Mapping[str, Any] | None


class InventoryInsightPort(Protocol):
    def observe(self) -> InventoryInsightSource:
        ...


class RiskInsightPort(Protocol):
    def list_jobs(self) -> Sequence[Mapping[str, Any]]:
        ...


class PlacementInsightPort(Protocol):
    def build(
        self,
        snapshot: Mapping[str, Any],
        risks: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        ...
