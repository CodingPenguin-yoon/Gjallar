"""Infrastructure-free durable recovery state and lease rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping


RECOVERY_STATUSES = frozenset({"pending", "leased", "retry_wait", "paused", "completed"})
RECOVERY_KINDS = frozenset({"vm_start_observation", "vm_shutdown_observation"})


class RecoveryDomainError(RuntimeError):
    """Base error for durable recovery invariants."""


class RecoveryNotFound(RecoveryDomainError):
    def __init__(self, operation_id: str) -> None:
        self.operation_id = str(operation_id)
        super().__init__(f"Recovery item was not found: {self.operation_id}")


class RecoveryLeaseLost(RecoveryDomainError):
    def __init__(self, operation_id: str) -> None:
        self.operation_id = str(operation_id)
        super().__init__(f"Recovery lease is no longer owned: {self.operation_id}")


class RecoveryLeaseBusy(RecoveryDomainError):
    def __init__(self, operation_id: str) -> None:
        self.operation_id = str(operation_id)
        super().__init__(f"Recovery item already has a live lease: {self.operation_id}")


@dataclass(frozen=True)
class RecoverySpec:
    operation_id: str
    recovery_kind: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.operation_id).strip():
            raise ValueError("Recovery operation_id is required")
        if self.recovery_kind not in RECOVERY_KINDS:
            raise ValueError(f"Unsupported recovery kind: {self.recovery_kind}")


@dataclass(frozen=True)
class RecoveryItem:
    operation_id: str
    recovery_kind: str
    status: str
    available_at: datetime
    lease_owner: str | None
    lease_generation: int
    lease_expires_at: datetime | None
    attempt_count: int
    last_error_code: str | None
    details: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    def __post_init__(self) -> None:
        if self.status not in RECOVERY_STATUSES:
            raise ValueError(f"Unsupported recovery status: {self.status}")


@dataclass(frozen=True)
class RecoveryLease:
    item: RecoveryItem
    token: str

    @property
    def operation_id(self) -> str:
        return self.item.operation_id

    @property
    def generation(self) -> int:
        return self.item.lease_generation


def recovery_item_payload(item: RecoveryItem) -> dict[str, Any]:
    """Return query-safe recovery state without the private lease token."""

    return {
        "operation_id": item.operation_id,
        "recovery_kind": item.recovery_kind,
        "status": item.status,
        "available_at": item.available_at.isoformat(),
        "lease_owner": item.lease_owner,
        "lease_generation": item.lease_generation,
        "lease_expires_at": item.lease_expires_at.isoformat() if item.lease_expires_at else None,
        "attempt_count": item.attempt_count,
        "last_error_code": item.last_error_code,
        "details": dict(item.details),
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
    }
