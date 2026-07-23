"""HTTP compatibility boundary for DRS advisor and migration workflows."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.inventory_context import inventory_adapter as _inventory_adapter
from app.api.v1.responses import success_response
from app.auth.dependencies import require_operator
from app.auth.roles import AuthenticatedUser, actor_evidence
from app.drs import application as drs_application
from app.jobs.runs import list_job_runs
from app.proxmox.drs_migration import get_default_drs_proxmox_migration_client

router = APIRouter()


def _drs_risks() -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for job in list_job_runs():
        for risk in job.get("risks") or []:
            if isinstance(risk, dict):
                risks.append(risk)
    return risks


def _drs_migration_client_factory() -> Any:
    return get_default_drs_proxmox_migration_client()


def _providers() -> drs_application.DrsApplicationProviders:
    return drs_application.DrsApplicationProviders(
        inventory_adapter=_inventory_adapter,
        risks=_drs_risks,
        migration_client_factory=_drs_migration_client_factory,
    )


def _http_error(exc: drs_application.DrsApplicationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _response(
    operation: Callable[[], drs_application.DrsApplicationResult],
) -> dict[str, Any]:
    try:
        result = operation()
    except drs_application.DrsApplicationError as exc:
        raise _http_error(exc) from exc
    return success_response(result.data, meta=result.meta)


async def _async_response(
    operation: Awaitable[drs_application.DrsApplicationResult],
) -> dict[str, Any]:
    try:
        result = await operation
    except drs_application.DrsApplicationError as exc:
        raise _http_error(exc) from exc
    return success_response(result.data, meta=result.meta)


@router.get("/drs/summary")
def get_drs_summary() -> dict:
    """Return the read-only DRS Advisor summary and current candidates."""
    return _response(lambda: drs_application.get_summary(_providers()))


@router.get("/drs/recommendations")
def list_drs_recommendations() -> dict:
    """Return read-only DRS Advisor recommendations."""
    return _response(lambda: drs_application.list_recommendations(_providers()))


@router.get("/drs/recommendations/{recommendation_id}")
def get_drs_recommendation(recommendation_id: str) -> dict:
    """Return one read-only DRS Advisor recommendation."""
    return _response(
        lambda: drs_application.get_recommendation(
            recommendation_id,
            _providers(),
        )
    )


@router.post("/drs/recommendations/{recommendation_id}/check")
def check_drs_recommendation(
    recommendation_id: str,
    payload: dict | None = None,
) -> dict:
    """Run a read-only final pre-check for one recommendation."""
    return _response(
        lambda: drs_application.check_recommendation(
            recommendation_id,
            payload,
            _providers(),
        )
    )


@router.post("/drs/explicit-test-candidates/check")
def check_drs_explicit_test_candidate(
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    """Run a read-only final pre-check for one explicitly selected smoke candidate."""
    _ = actor
    return _response(
        lambda: drs_application.check_explicit_test_candidate(
            payload,
            _providers(),
        )
    )


@router.get("/drs/policies")
def list_drs_policies() -> dict:
    """Return current DRS VM migration policy management state."""
    return _response(lambda: drs_application.list_policies(_providers()))


@router.get("/drs/policies/{vm_identity_id}")
def get_drs_policy(vm_identity_id: str) -> dict:
    """Return one current DRS VM migration policy item."""
    return _response(
        lambda: drs_application.get_policy(
            vm_identity_id,
            _providers(),
        )
    )


@router.put("/drs/policies/{vm_identity_id}")
def put_drs_policy(
    vm_identity_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    """Manually update one Gjallar-local DRS VM migration policy."""
    return _response(
        lambda: drs_application.put_policy(
            vm_identity_id,
            payload,
            actor=actor_evidence(actor),
            providers=_providers(),
        )
    )


@router.post("/drs/recommendations/{recommendation_id}/approval-packets")
def create_drs_approval_packet(
    recommendation_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    """Create local-only DRS approval and non-runnable migration job intent."""
    return _response(
        lambda: drs_application.create_approval_packet(
            recommendation_id,
            payload,
            actor=actor_evidence(actor),
            providers=_providers(),
        )
    )


@router.post("/drs/explicit-test-candidates/approval-packets")
def create_drs_explicit_test_approval_packet(
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    """Create local approval/job intent for an explicitly selected smoke candidate."""
    return _response(
        lambda: drs_application.create_explicit_test_approval_packet(
            payload,
            actor=actor_evidence(actor),
            providers=_providers(),
        )
    )


async def execute_drs_migration_job_action(
    job_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser | dict | None = None,
) -> dict:
    """Execute one approved DRS migration job through the operator-only path."""
    return await _async_response(
        drs_application.execute_migration_job(
            job_id,
            payload,
            actor=actor_evidence(actor) if actor is not None else None,
            providers=_providers(),
        )
    )


@router.post("/drs/migration-jobs/{job_id}/execute")
async def execute_drs_migration_job_route(
    job_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    return await execute_drs_migration_job_action(job_id, payload, actor=actor)


async def reconcile_drs_migration_job_action(
    job_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser | dict | None = None,
) -> dict:
    """Poll a stored DRS migration UPID and update local reconciliation state."""
    return await _async_response(
        drs_application.reconcile_migration_job(
            job_id,
            payload,
            actor=actor_evidence(actor) if actor is not None else None,
            providers=_providers(),
        )
    )


@router.post("/drs/migration-jobs/{job_id}/reconcile")
async def reconcile_drs_migration_job_route(
    job_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    return await reconcile_drs_migration_job_action(job_id, payload, actor=actor)


async def preview_drs_migration_reconciliation_action(
    job_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser | dict | None = None,
) -> dict:
    """Preview DRS reconciliation evidence without corrective mutation."""
    return await _async_response(
        drs_application.preview_migration_reconciliation(
            job_id,
            payload,
            actor=actor_evidence(actor) if actor is not None else None,
            providers=_providers(),
        )
    )


@router.post("/drs/migration-jobs/{job_id}/reconcile-preview")
async def preview_drs_migration_reconciliation_route(
    job_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    return await preview_drs_migration_reconciliation_action(
        job_id,
        payload,
        actor=actor,
    )
