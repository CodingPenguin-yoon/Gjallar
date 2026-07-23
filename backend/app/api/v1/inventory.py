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
    adapter = inventory_context.inventory_adapter()
    snapshot = adapter.snapshot()
    return success_response(
        {
            "cluster_id": "gjallar-mvp",
            "mode": "read_only_inventory",
            "node_count": len(snapshot.nodes),
            "vm_count": len(snapshot.vms),
            "template_count": len(snapshot.templates),
            "risk_level": "unknown",
        },
        meta=inventory_context.inventory_meta(adapter),
    )


@router.get("/nodes")
def list_nodes() -> dict:
    """Return read-only node inventory."""
    adapter = inventory_context.inventory_adapter()
    nodes = adapter.list_nodes()
    return success_response(
        [node.to_dict() for node in nodes],
        meta=inventory_context.inventory_meta(adapter),
    )


@router.get("/vms")
def list_vms() -> dict:
    """Return read-only VM inventory."""
    adapter = inventory_context.inventory_adapter()
    vms = adapter.list_vms()
    return success_response(
        [vm.to_dict() for vm in vms],
        meta=inventory_context.inventory_meta(adapter),
    )


@router.get("/vms/{vmid}")
def get_vm(vmid: int) -> dict:
    """Return a read-only VM detail for the requested VMID."""
    adapter = inventory_context.inventory_adapter()
    vm = adapter.get_vm(vmid)
    if vm is None:
        raise HTTPException(status_code=404, detail="VM inventory item not found")
    return success_response(vm.to_dict(), meta=inventory_context.inventory_meta(adapter))


@router.get("/profiles")
async def list_profiles() -> dict:
    """Return active DB-backed VM creation profile defaults."""
    return success_response([profile.to_dict() for profile in list_create_profile_options()])


@router.get("/templates")
def list_templates() -> dict:
    """Return read-only template inventory."""
    adapter = inventory_context.inventory_adapter()
    templates = adapter.list_templates()
    return success_response(
        [template.to_dict() for template in templates],
        meta=inventory_context.inventory_meta(adapter),
    )


@router.get("/storage")
def list_storage() -> dict:
    """Return read-only storage candidates from inventory."""
    adapter = inventory_context.inventory_adapter()
    storages = adapter.list_storage()
    return success_response(
        [storage.to_dict() for storage in storages],
        meta=inventory_context.inventory_meta(adapter),
    )


@router.get("/networks")
def list_networks() -> dict:
    """Return read-only network bridge inventory."""
    adapter = inventory_context.inventory_adapter()
    networks = adapter.list_networks()
    return success_response(
        [network.to_dict() for network in networks],
        meta=inventory_context.inventory_meta(adapter),
    )
