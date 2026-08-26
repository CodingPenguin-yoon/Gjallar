"""Operation query HTTP routes for ``/api/v1``."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.v1.responses import success_response
from app.operations.facade import (
    InvalidOperationQuery,
    OperationQueryNotFound,
    get_operation,
    list_operations,
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
