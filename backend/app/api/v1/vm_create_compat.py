"""Compatibility HTTP routes for the Create VM workflow."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.inventory_context import inventory_adapter as _inventory_adapter
from app.api.v1.inventory_context import mutation_inventory_adapter as _mutation_inventory_adapter
from app.api.v1.responses import success_response
from app.auth.dependencies import require_operator
from app.auth.roles import AuthenticatedUser
from app.proxmox.client import get_default_proxmox_mutation_client
from app.vm_create import application as vm_create_application

router = APIRouter()


async def _application_response(
    call: Awaitable[vm_create_application.VmCreateApplicationResult],
) -> dict[str, Any]:
    try:
        result = await call
    except vm_create_application.VmCreateApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return success_response(result.data, meta={"mode": result.mode})


def _mutation_client_factory():
    return get_default_proxmox_mutation_client()


async def create_vm_draft(
    payload: dict | None = None,
    actor: AuthenticatedUser | dict | None = None,
) -> dict:
    return await _application_response(
        vm_create_application.create_draft(
            payload,
            actor=actor,
            inventory_adapter=_inventory_adapter(),
        )
    )


@router.post("/vm-create/drafts")
async def create_vm_draft_route(
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    return await create_vm_draft(payload, actor=actor)


async def preflight_vm_draft(
    draft_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser | dict | None = None,
) -> dict:
    return await _application_response(
        vm_create_application.preflight_draft(
            draft_id,
            payload,
            actor=actor,
            inventory_adapter=_inventory_adapter(),
        )
    )


@router.post("/vm-create/{draft_id}/preflight")
async def preflight_vm_draft_route(
    draft_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    return await preflight_vm_draft(draft_id, payload, actor=actor)


async def plan_vm_draft(
    draft_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser | dict | None = None,
) -> dict:
    return await _application_response(
        vm_create_application.plan_draft(
            draft_id,
            payload,
            actor=actor,
            inventory_adapter=_inventory_adapter(),
        )
    )


@router.post("/vm-create/{draft_id}/plan")
async def plan_vm_draft_route(
    draft_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    return await plan_vm_draft(draft_id, payload, actor=actor)


async def approve_vm_draft(
    draft_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser | dict | None = None,
) -> dict:
    return await _application_response(
        vm_create_application.approve_draft(
            draft_id,
            payload,
            actor=actor,
            inventory_adapter=_inventory_adapter(),
        )
    )


@router.post("/vm-create/{draft_id}/approve")
async def approve_vm_draft_route(
    draft_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    return await approve_vm_draft(draft_id, payload, actor=actor)


async def preview_vm_draft_proxmox_create(
    draft_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser | dict | None = None,
) -> dict:
    return await _application_response(
        vm_create_application.preview_proxmox_create(
            draft_id,
            payload,
            actor=actor,
            inventory_adapter=_inventory_adapter(),
        )
    )


@router.post("/vm-create/{draft_id}/proxmox-preview")
async def preview_vm_draft_proxmox_create_route(
    draft_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    return await preview_vm_draft_proxmox_create(draft_id, payload, actor=actor)


async def create_vm_draft_proxmox_native(
    draft_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser | dict | None = None,
) -> dict:
    return await _application_response(
        vm_create_application.execute_proxmox_create(
            draft_id,
            payload,
            actor=actor,
            inventory_adapter=_mutation_inventory_adapter(),
            mutation_client_factory=_mutation_client_factory,
        )
    )


@router.post("/vm-create/{draft_id}/proxmox-create")
async def create_vm_draft_proxmox_native_route(
    draft_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    return await create_vm_draft_proxmox_native(draft_id, payload, actor=actor)
