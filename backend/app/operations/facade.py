"""Composition facade for shared Operations queries."""

from __future__ import annotations

from typing import Any

from app.operations.core.application import (
    InvalidOperationQuery,
    OperationListQuery,
    OperationQueryNotFound,
    OperationQueryService,
)
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.recovery.domain import recovery_item_payload
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.target_lock import get_target_operation_lock


def list_operations(
    *,
    status: str | None = None,
    operation_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    return OperationQueryService(operations=SqlAlchemyOperationStore()).list(
        OperationListQuery(status=status, operation_type=operation_type, limit=limit)
    )


def get_operation(operation_id: str) -> dict[str, Any]:
    result = OperationQueryService(operations=SqlAlchemyOperationStore()).get(operation_id)
    operation = result["operation"]
    recovery = SqlAlchemyRecoveryStore().get(operation_id)
    result["recovery"] = recovery_item_payload(recovery) if recovery is not None else None
    result["target_lock"] = get_target_operation_lock(
        str(operation.get("target_type") or ""),
        str(operation.get("target_id") or ""),
    )
    return result


__all__ = ["InvalidOperationQuery", "OperationQueryNotFound", "get_operation", "list_operations"]
