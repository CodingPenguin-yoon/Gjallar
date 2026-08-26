"""Read-only inventory HTTP routes for ``/api/v1``."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.v1 import inventory_context
from app.api.v1.responses import success_response
from app.vm_create.drafts import list_create_profile_options

router = APIRouter()


@router.get("/setup/proxmox/connection")
def get_proxmox_connection_status() -> dict:
    """Return redacted connection truth without exposing fixture inventory."""
    observation = inventory_context.inventory_query().observe()
    return success_response(observation.status.to_dict(), meta={"mode": "connection_status"})


@router.get("/cluster/summary")
def cluster_summary() -> dict:
    """Return a read-only MVP cluster summary."""
    observation = inventory_context.inventory_observation()
    snapshot = observation.snapshot
    return success_response(
        {
            "cluster_id": observation.status.cluster_id,
            "mode": "read_only_inventory",
            "node_count": len(snapshot.nodes),
            "vm_count": len(snapshot.vms),
            "template_count": len(snapshot.templates),
            "risk_level": "unknown",
        },
        meta=inventory_context.inventory_meta(observation),
    )


@router.get("/nodes")
def list_nodes() -> dict:
    """Return read-only node inventory."""
    observation = inventory_context.inventory_observation()
    nodes = observation.snapshot.nodes
    return success_response(
        [node.to_dict() for node in nodes],
        meta=inventory_context.inventory_meta(observation),
    )


@router.get("/vms")
def list_vms() -> dict:
    """Return read-only VM inventory."""
    observation = inventory_context.inventory_observation()
    vms = observation.snapshot.vms
    return success_response(
        [vm.to_dict() for vm in vms],
        meta=inventory_context.inventory_meta(observation),
    )


@router.get("/vms/{vmid}")
def get_vm(vmid: int) -> dict:
    """Return a read-only VM detail for the requested VMID."""
    observation = inventory_context.inventory_observation()
    vm = next((item for item in observation.snapshot.vms if item.vmid == vmid), None)
    if vm is None:
        raise HTTPException(status_code=404, detail="VM inventory item not found")
    return success_response(vm.to_dict(), meta=inventory_context.inventory_meta(observation))


@router.get("/profiles")
async def list_profiles() -> dict:
    """Return active DB-backed VM creation profile defaults."""
    return success_response([profile.to_dict() for profile in list_create_profile_options()])


@router.get("/templates")
def list_templates() -> dict:
    """Return read-only template inventory."""
    observation = inventory_context.inventory_observation()
    templates = observation.snapshot.templates
    return success_response(
        [template.to_dict() for template in templates],
        meta=inventory_context.inventory_meta(observation),
    )


@router.get("/storage")
def list_storage() -> dict:
    """Return read-only storage candidates from inventory."""
    observation = inventory_context.inventory_observation()
    storages = [storage for node in observation.snapshot.nodes for storage in node.storage]
    return success_response(
        [storage.to_dict() for storage in storages],
        meta=inventory_context.inventory_meta(observation),
    )


@router.get("/networks")
def list_networks() -> dict:
    """Return read-only network bridge inventory."""
    observation = inventory_context.inventory_observation()
    networks = [network for node in observation.snapshot.nodes for network in node.networks]
    return success_response(
        [network.to_dict() for network in networks],
        meta=inventory_context.inventory_meta(observation),
    )
