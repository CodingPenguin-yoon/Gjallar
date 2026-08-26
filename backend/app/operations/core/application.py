"""Read-only Operations application services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.operations.core.domain import OPERATION_STATUSES
from app.operations.core.ports import OperationStorePort
from app.operations.core.read_models import operation_event_payload, operation_payload


class InvalidOperationQuery(ValueError):
    """Raised when a list filter is outside the public query contract."""


class OperationQueryNotFound(LookupError):
    def __init__(self, operation_id: str) -> None:
        self.operation_id = str(operation_id)
        super().__init__(f"Operation was not found: {self.operation_id}")


@dataclass(frozen=True)
class OperationListQuery:
    status: str | None = None
    operation_type: str | None = None
    limit: int = 50
    target_type: str | None = None
    target_id: str | None = None

    def normalized(self) -> "OperationListQuery":
        status = str(self.status or "").strip() or None
        operation_type = str(self.operation_type or "").strip() or None
        target_type = str(self.target_type or "").strip() or None
        target_id = str(self.target_id or "").strip() or None
        limit = int(self.limit)
        if status is not None and status not in OPERATION_STATUSES:
            raise InvalidOperationQuery(f"Unsupported operation status: {status}")
        if limit < 1 or limit > 200:
            raise InvalidOperationQuery("Operation list limit must be between 1 and 200")
        return OperationListQuery(
            status=status,
            operation_type=operation_type,
            target_type=target_type,
            target_id=target_id,
            limit=limit,
        )


class OperationQueryService:
    def __init__(self, *, operations: OperationStorePort) -> None:
        self._operations = operations

    def list(self, query: OperationListQuery) -> list[dict[str, Any]]:
        normalized = query.normalized()
        operations = self._operations.list(
            status=normalized.status,
            operation_type=normalized.operation_type,
            target_type=normalized.target_type,
            target_id=normalized.target_id,
            limit=normalized.limit,
        )
        return [operation_payload(operation, include_details=False) for operation in operations]

    def get(self, operation_id: str) -> dict[str, Any]:
        operation = self._operations.get(str(operation_id))
        if operation is None:
            raise OperationQueryNotFound(str(operation_id))
        result = {
            "operation": operation_payload(operation),
            "events": [operation_event_payload(event) for event in self._operations.list_events(operation.operation_id)],
        }
        instruction_bundle = operation.details.get("instruction_bundle")
        if isinstance(instruction_bundle, dict):
            result.update(
                {
                    "instruction_bundle": dict(instruction_bundle),
                    "idempotent_replay": False,
                    "backend_command_execution": False,
                    "proxmox_mutation_enabled": False,
                }
            )
        return result
