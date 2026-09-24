"""Workload inventory providers shared by API transport modules."""

from fastapi import HTTPException

from app.setup_integration.proxmox_connection import ProxmoxConnectionObservation
from app.workloads.inventory import (
    WorkloadInventoryQuery,
    WorkloadInventoryUnavailableError,
    get_default_workload_inventory_query,
)


def inventory_query() -> WorkloadInventoryQuery:
    return get_default_workload_inventory_query()


def inventory_unavailable_http(exc: WorkloadInventoryUnavailableError) -> HTTPException:
    return HTTPException(status_code=503, detail=exc.to_detail())


def inventory_adapter():
    try:
        return inventory_query().require_adapter()
    except WorkloadInventoryUnavailableError as exc:
        raise inventory_unavailable_http(exc) from exc


def mutation_inventory_adapter(*, node_id: str, vmid: int):
    try:
        return inventory_query().require_mutation_adapter(node_id=node_id, vmid=vmid)
    except WorkloadInventoryUnavailableError as exc:
        raise inventory_unavailable_http(exc) from exc


def inventory_observation() -> ProxmoxConnectionObservation:
    try:
        return inventory_query().require_observation()
    except WorkloadInventoryUnavailableError as exc:
        raise inventory_unavailable_http(exc) from exc


def inventory_meta(observation: ProxmoxConnectionObservation) -> dict:
    return {
        "source": observation.status.source,
        "mode": "read_only",
        "observed_at": observation.status.observed_at or None,
        "freshness": observation.status.freshness,
        "connection": observation.status.to_dict(),
        "availability": observation.snapshot.availability.to_dict(),
    }


def create_inventory_adapter():
    try:
        return inventory_query().require_create_adapter()
    except WorkloadInventoryUnavailableError as exc:
        raise inventory_unavailable_http(exc) from exc
