"""Redacted Proxmox connection truth for product and workload boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from app.proxmox.inventory import ProxmoxInventoryUnavailableError
from app.proxmox.models import InventorySnapshot


@dataclass(frozen=True)
class ProxmoxConnectionStatus:
    state: str
    source: str
    cluster_id: str
    observed_at: str = ""
    freshness: str = "unknown"
    reason: str = ""
    configured: bool = False
    inventory_available: bool = False
    missing_configuration: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "source": self.source,
            "cluster_id": self.cluster_id,
            "observed_at": self.observed_at or None,
            "freshness": self.freshness,
            "reason": self.reason or None,
            "configured": self.configured,
            "inventory_available": self.inventory_available,
            "missing_configuration": list(self.missing_configuration),
        }


@dataclass(frozen=True)
class ProxmoxConnectionObservation:
    status: ProxmoxConnectionStatus
    snapshot: InventorySnapshot | None = None


def _cluster_id(adapter: Any) -> str:
    return str(getattr(adapter, "cluster_id", "gjallar-mvp") or "gjallar-mvp")


def _degraded_reason(exc: Exception) -> str:
    if isinstance(exc, requests.exceptions.SSLError):
        return "proxmox_tls_failed"
    if isinstance(exc, requests.exceptions.Timeout):
        return "proxmox_connection_timed_out"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "proxmox_connection_unreachable"
    if isinstance(exc, requests.exceptions.HTTPError):
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code in {401, 403}:
            return "proxmox_authentication_failed"
        return "proxmox_api_rejected"
    return "proxmox_inventory_unavailable"


def observe_proxmox_connection(adapter: Any) -> ProxmoxConnectionObservation:
    source = str(getattr(adapter, "source", "unavailable") or "unavailable")
    cluster_id = _cluster_id(adapter)
    if source == "unavailable":
        context = adapter.redacted_connection_context() if hasattr(adapter, "redacted_connection_context") else {}
        return ProxmoxConnectionObservation(
            status=ProxmoxConnectionStatus(
                state="unconfigured",
                source=source,
                cluster_id=cluster_id,
                reason=str(context.get("reason") or "proxmox_inventory_unconfigured"),
                missing_configuration=tuple(context.get("missing_configuration") or ()),
            )
        )

    try:
        snapshot = adapter.snapshot()
    except ProxmoxInventoryUnavailableError as exc:
        return ProxmoxConnectionObservation(
            status=ProxmoxConnectionStatus(
                state=exc.connection_state,
                source=source,
                cluster_id=cluster_id,
                reason=exc.reason,
                configured=exc.connection_state != "unconfigured",
                missing_configuration=exc.missing_configuration,
            )
        )
    except Exception as exc:
        return ProxmoxConnectionObservation(
            status=ProxmoxConnectionStatus(
                state="degraded",
                source=source,
                cluster_id=cluster_id,
                reason=_degraded_reason(exc),
                configured=True,
            )
        )

    if getattr(adapter, "is_test_fixture", False):
        state = "test_fixture"
        freshness = "fixture"
        configured = False
    else:
        state = "live"
        freshness = "fresh"
        configured = True
    return ProxmoxConnectionObservation(
        status=ProxmoxConnectionStatus(
            state=state,
            source=str(snapshot.source or source),
            cluster_id=cluster_id,
            observed_at=str(snapshot.observed_at or ""),
            freshness=freshness,
            configured=configured,
            inventory_available=True,
        ),
        snapshot=snapshot,
    )
