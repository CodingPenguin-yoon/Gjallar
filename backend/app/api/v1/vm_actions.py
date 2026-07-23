"""Verified VM action HTTP routes for ``/api/v1``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from app.api.v1 import inventory_context
from app.api.v1.responses import success_response
from app.auth.dependencies import require_operator
from app.auth.roles import AuthenticatedUser, actor_evidence
from app.proxmox.client import get_default_proxmox_mutation_client
from app.vm_actions.post_create_readiness import (
    PostCreateReadinessError,
    record_post_create_readiness_evidence,
)
from app.vm_actions.shutdown import VmShutdownError, run_vm_shutdown
from app.vm_actions.start import VmStartError, run_vm_start

router = APIRouter()


async def start_vm_action(
    node_id: str,
    vmid: int,
    payload: dict | None = None,
    actor: AuthenticatedUser | dict | None = None,
) -> dict:
    """Start a stopped VM through the explicit VM action path."""
    try:
        result = await run_in_threadpool(
            run_vm_start,
            node_id=node_id,
            vmid=vmid,
            payload=payload or {},
            actor=actor_evidence(actor) if actor is not None else None,
            inventory_adapter=inventory_context.inventory_adapter(),
            client_factory=get_default_proxmox_mutation_client,
        )
    except VmStartError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
    return success_response(result, meta={"mode": "proxmox_native_vm_start"})


@router.post("/nodes/{node_id}/vms/{vmid}/actions/start")
async def start_vm_action_route(
    node_id: str,
    vmid: int,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    return await start_vm_action(node_id, vmid, payload, actor=actor)


async def shutdown_vm_action(
    node_id: str,
    vmid: int,
    payload: dict | None = None,
    actor: AuthenticatedUser | dict | None = None,
) -> dict:
    """Gracefully shut down a running VM through the verified action path."""
    try:
        result = await run_in_threadpool(
            run_vm_shutdown,
            node_id=node_id,
            vmid=vmid,
            payload=payload or {},
            actor=actor_evidence(actor) if actor is not None else None,
            inventory_adapter=inventory_context.inventory_adapter(),
            client_factory=get_default_proxmox_mutation_client,
        )
    except VmShutdownError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
    return success_response(result, meta={"mode": "proxmox_native_vm_shutdown"})


@router.post("/nodes/{node_id}/vms/{vmid}/actions/shutdown")
async def shutdown_vm_action_route(
    node_id: str,
    vmid: int,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    return await shutdown_vm_action(node_id, vmid, payload, actor=actor)


async def post_create_readiness_evidence_action(
    node_id: str,
    vmid: int,
    payload: dict | None = None,
    actor: AuthenticatedUser | dict | None = None,
) -> dict:
    """Record local-only operator-supplied readiness evidence for an existing VM."""
    try:
        result = await run_in_threadpool(
            record_post_create_readiness_evidence,
            node_id=node_id,
            vmid=vmid,
            payload=payload or {},
            actor=actor_evidence(actor) if actor is not None else None,
        )
    except PostCreateReadinessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
    return success_response(result, meta={"mode": "post_create_readiness_evidence_local_only"})


@router.post("/nodes/{node_id}/vms/{vmid}/post-create-readiness-evidence")
async def post_create_readiness_evidence_route(
    node_id: str,
    vmid: int,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    return await post_create_readiness_evidence_action(node_id, vmid, payload, actor=actor)
