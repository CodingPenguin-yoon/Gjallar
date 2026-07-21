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
    return OperationQueryService(operations=SqlAlchemyOperationStore()).get(operation_id)


__all__ = ["InvalidOperationQuery", "OperationQueryNotFound", "get_operation", "list_operations"]
