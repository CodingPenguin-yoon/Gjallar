"""Workload inventory providers shared by API transport modules."""

from fastapi import HTTPException

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


def inventory_meta(adapter) -> dict:
    try:
        observation = WorkloadInventoryQuery(adapter).require_observation()
    except WorkloadInventoryUnavailableError as exc:
        raise inventory_unavailable_http(exc) from exc
    return {
        "source": observation.status.source,
        "mode": "read_only",
        "observed_at": observation.status.observed_at or None,
        "freshness": observation.status.freshness,
        "connection": observation.status.to_dict(),
    }
