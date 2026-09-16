"""Operation query HTTP routes for ``/api/v1``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from app.api.v1.responses import success_response
from app.auth.dependencies import require_operator
from app.auth.roles import AuthenticatedUser, actor_evidence
from app.operations.facade import (
    InvalidOperationQuery,
    OperationQueryNotFound,
    OperationRecoveryObserveError,
    get_operation,
    list_operations,
    observe_operation_recovery,
)

router = APIRouter()


@router.get("/operations")
def list_operations_route(
    status: str | None = None,
    operation_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    target_type: str | None = None,
    target_id: str | None = None,
) -> dict:
    try:
        result = list_operations(
            status=status,
            operation_type=operation_type,
            target_type=target_type,
            target_id=target_id,
            limit=limit,
        )
    except InvalidOperationQuery as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_OPERATION_QUERY", "message": str(exc)},
        ) from exc
    return success_response(
        result,
        meta={
            "mode": "operation_read",
            "filters": {
                "status": status,
                "operation_type": operation_type,
                "target_type": target_type,
                "target_id": target_id,
                "limit": limit,
            },
        },
    )


@router.get("/operations/{operation_id}")
def get_operation_route(operation_id: str) -> dict:
    try:
        result = get_operation(operation_id)
    except OperationQueryNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "GUIDED_QM_OPERATION_NOT_FOUND",
                "canonical_code": "OPERATION_NOT_FOUND",
                "message": str(exc),
                "operation_id": exc.operation_id,
            },
        ) from exc
    return success_response(result, meta={"mode": "operation_read"})


@router.post("/operations/{operation_id}/recovery/observe")
async def observe_operation_recovery_route(
    operation_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    request = dict(payload or {})
    allowed_fields = {"expected_version", "expected_checksum", "idempotency_key"}
    raw_version = request.get("expected_version")
    expected_checksum = request.get("expected_checksum")
    idempotency_key = request.get("idempotency_key")
    if (
        set(request) - allowed_fields
        or isinstance(raw_version, bool)
        or not isinstance(raw_version, int)
        or raw_version < 1
        or not isinstance(expected_checksum, str)
        or not expected_checksum.strip()
        or not isinstance(idempotency_key, str)
        or not idempotency_key.strip()
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_OPERATION_RECOVERY_OBSERVE_REQUEST",
                "message": "Only a positive integer expected_version and non-empty expected_checksum/idempotency_key are accepted",
            },
        )
    try:
        result = await run_in_threadpool(
            observe_operation_recovery,
            operation_id,
            actor=actor_evidence(actor),
            expected_version=raw_version,
            expected_checksum=expected_checksum.strip(),
            idempotency_key=idempotency_key.strip(),
        )
    except OperationRecoveryObserveError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
    return success_response(result, meta={"mode": "operation_recovery_observation", "mutation_enabled": False})
