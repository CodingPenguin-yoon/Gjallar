"""Infrastructure-free Operation state, identity, and evidence-chain rules."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence


EXECUTION_MODES = frozenset({"managed_api", "guided_manual", "observe_only"})
OPERATION_STATUSES = frozenset(
    {
        "draft",
        "planned",
        "awaiting_approval",
        "approved",
        "dispatching",
        "running",
        "awaiting_operator",
        "awaiting_verification",
        "verifying",
        "succeeded",
        "blocked",
        "rejected",
        "expired",
        "failed",
        "needs_reconciliation",
        "cancelled",
    }
)
TERMINAL_OPERATION_STATUSES = frozenset({"succeeded", "blocked", "rejected", "expired", "failed", "cancelled"})

_ALLOWED_TRANSITIONS = {
    "draft": {"planned", "cancelled"},
    "planned": {
        "awaiting_approval",
        "approved",
        "dispatching",
        "awaiting_operator",
        "blocked",
        "expired",
        "failed",
        "cancelled",
    },
    "awaiting_approval": {"approved", "rejected", "expired", "cancelled"},
    "approved": {"dispatching", "awaiting_operator", "blocked", "expired", "cancelled"},
    "dispatching": {"running", "failed", "needs_reconciliation"},
    "running": {"verifying", "failed", "needs_reconciliation"},
    "awaiting_operator": {"awaiting_verification", "expired", "cancelled", "needs_reconciliation"},
    "awaiting_verification": {"verifying", "expired", "needs_reconciliation"},
    "verifying": {"succeeded", "failed", "needs_reconciliation"},
    "needs_reconciliation": {"verifying", "succeeded", "failed", "cancelled"},
    # A guided command can still be executed outside Gjallar after its bundle
    # expires. A trusted late attestation must reopen the record for
    # reconciliation instead of losing evidence about a possible side effect.
    "expired": {"needs_reconciliation"},
}


class OperationDomainError(RuntimeError):
    """Base error for Operation domain invariants."""


class InvalidOperationTransition(OperationDomainError):
    """Raised when an Operation state transition is not allowed."""

    def __init__(self, current_status: str, next_status: str) -> None:
        self.current_status = current_status
        self.next_status = next_status
        super().__init__(f"Operation transition is not allowed: {current_status} -> {next_status}")


class OperationIntentConflict(OperationDomainError):
    """Raised when an idempotency identity already belongs to another intent."""

    def __init__(self, operation_id: str) -> None:
        self.operation_id = operation_id
        super().__init__(f"Operation idempotency identity conflicts with operation {operation_id}")


class OperationNotFound(OperationDomainError):
    """Raised when an operation identity does not exist."""

    def __init__(self, operation_id: str) -> None:
        self.operation_id = operation_id
        super().__init__(f"Operation was not found: {operation_id}")


class OperationStateConflict(OperationDomainError):
    """Raised when a caller's expected current state no longer matches."""

    def __init__(self, operation_id: str, current_status: str) -> None:
        self.operation_id = operation_id
        self.current_status = current_status
        super().__init__(f"Operation state changed concurrently: {operation_id} is {current_status}")


@dataclass(frozen=True)
class OperationActor:
    user_id: str = ""
    username: str = ""
    role: str = ""

    @classmethod
    def from_mapping(cls, actor: Mapping[str, Any] | None) -> "OperationActor":
        payload = actor or {}
        return cls(
            user_id=str(payload.get("actor_user_id") or payload.get("user_id") or "").strip(),
            username=str(payload.get("actor_username") or payload.get("username") or "").strip(),
            role=str(payload.get("actor_role") or payload.get("role") or "").strip(),
        )

    def to_dict(self) -> dict[str, str]:
        return {"user_id": self.user_id, "username": self.username, "role": self.role}


@dataclass(frozen=True)
class OperationSpec:
    operation_id: str
    operation_type: str
    execution_mode: str
    target_type: str
    target_id: str
    idempotency_key: str
    intent_digest: str
    plan_digest: str
    actor: OperationActor
    initial_status: str = "planned"
    initial_stage: str = "plan"
    expires_at: datetime | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        required = {
            "operation_id": self.operation_id,
            "operation_type": self.operation_type,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "idempotency_key": self.idempotency_key,
            "intent_digest": self.intent_digest,
            "plan_digest": self.plan_digest,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise ValueError(f"Operation fields are required: {', '.join(missing)}")
        if self.execution_mode not in EXECUTION_MODES:
            raise ValueError(f"Unsupported execution mode: {self.execution_mode}")
        if self.initial_status not in OPERATION_STATUSES:
            raise ValueError(f"Unsupported operation status: {self.initial_status}")
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("Operation expires_at must include a timezone")


@dataclass(frozen=True)
class OperationSnapshot:
    operation_id: str
    operation_type: str
    execution_mode: str
    status: str
    target_type: str
    target_id: str
    idempotency_key: str
    intent_digest: str
    plan_digest: str
    current_stage: str
    actor: OperationActor
    details: dict[str, Any]
    expires_at: datetime | None
    version: int
    last_event_checksum: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class OperationCreateResult:
    operation: OperationSnapshot
    created: bool


@dataclass(frozen=True)
class OperationEvent:
    event_id: str
    operation_id: str
    sequence: int
    event_type: str
    from_status: str | None
    to_status: str
    stage: str
    actor: OperationActor
    payload: dict[str, Any]
    previous_checksum: str
    checksum: str
    created_at: datetime


def ensure_operation_transition(current_status: str, next_status: str) -> None:
    if current_status not in OPERATION_STATUSES or next_status not in OPERATION_STATUSES:
        raise InvalidOperationTransition(current_status, next_status)
    if next_status not in _ALLOWED_TRANSITIONS.get(current_status, set()):
        raise InvalidOperationTransition(current_status, next_status)


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def operation_digest(payload: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(dict(payload)).encode("utf-8")).hexdigest()


def event_checksum_payload(
    *,
    operation_id: str,
    sequence: int,
    event_type: str,
    from_status: str | None,
    to_status: str,
    stage: str,
    actor: OperationActor,
    payload: Mapping[str, Any],
    previous_checksum: str,
    created_at: datetime,
) -> dict[str, Any]:
    return {
        "operation_id": operation_id,
        "sequence": sequence,
        "event_type": event_type,
        "from_status": from_status,
        "to_status": to_status,
        "stage": stage,
        "actor": actor.to_dict(),
        "payload": dict(payload),
        "previous_checksum": previous_checksum,
        "created_at": created_at.isoformat(),
    }


def verify_event_chain(events: Sequence[OperationEvent]) -> bool:
    previous_checksum = ""
    expected_sequence = 1
    for event in events:
        if event.sequence != expected_sequence or event.previous_checksum != previous_checksum:
            return False
        expected_checksum = operation_digest(
            event_checksum_payload(
                operation_id=event.operation_id,
                sequence=event.sequence,
                event_type=event.event_type,
                from_status=event.from_status,
                to_status=event.to_status,
                stage=event.stage,
                actor=event.actor,
                payload=event.payload,
                previous_checksum=event.previous_checksum,
                created_at=event.created_at,
            )
        )
        if event.checksum != expected_checksum:
            return False
        previous_checksum = event.checksum
        expected_sequence += 1
    return True
