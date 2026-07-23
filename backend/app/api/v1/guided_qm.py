"""Guided ``qm`` operation HTTP routes for ``/api/v1``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from app.api.v1.responses import success_response
from app.auth.dependencies import require_operator
from app.auth.roles import AuthenticatedUser, actor_evidence
from app.operations.guided_qm.facade import (
    GuidedQmError,
    attest_guided_qm_operation,
    plan_guided_qm_unlock,
    verify_guided_qm_operation,
)
from app.proxmox.client import get_default_proxmox_mutation_client

router = APIRouter()


def _guided_qm_http_error(exc: GuidedQmError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.to_detail())


async def plan_guided_qm_unlock_action(
    payload: dict | None = None,
    actor: AuthenticatedUser | dict | None = None,
) -> dict:
    try:
        result = await run_in_threadpool(
            plan_guided_qm_unlock,
            payload=payload or {},
            actor=actor_evidence(actor) if actor is not None else None,
            client_factory=get_default_proxmox_mutation_client,
        )
    except GuidedQmError as exc:
        raise _guided_qm_http_error(exc) from exc
    return success_response(
        result,
        meta={"mode": "guided_manual", "executor": "external_proxmox_node_shell"},
    )


@router.post("/operations/guided-qm/vm-unlock")
async def plan_guided_qm_unlock_route(
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    return await plan_guided_qm_unlock_action(payload, actor=actor)


async def attest_guided_qm_operation_action(
    operation_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser | dict | None = None,
) -> dict:
    try:
        result = await run_in_threadpool(
            attest_guided_qm_operation,
            operation_id=operation_id,
            payload=payload or {},
            actor=actor_evidence(actor) if actor is not None else None,
        )
    except GuidedQmError as exc:
        raise _guided_qm_http_error(exc) from exc
    return success_response(result, meta={"mode": "guided_manual_operator_attestation"})


@router.post("/operations/{operation_id}/operator-attestation")
async def attest_guided_qm_operation_route(
    operation_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    return await attest_guided_qm_operation_action(operation_id, payload, actor=actor)


async def verify_guided_qm_operation_action(
    operation_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser | dict | None = None,
) -> dict:
    try:
        result = await run_in_threadpool(
            verify_guided_qm_operation,
            operation_id=operation_id,
            payload=payload or {},
            actor=actor_evidence(actor) if actor is not None else None,
            client_factory=get_default_proxmox_mutation_client,
        )
    except GuidedQmError as exc:
        raise _guided_qm_http_error(exc) from exc
    return success_response(result, meta={"mode": "guided_manual_api_verification"})


@router.post("/operations/{operation_id}/verification")
async def verify_guided_qm_operation_route(
    operation_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    return await verify_guided_qm_operation_action(operation_id, payload, actor=actor)
