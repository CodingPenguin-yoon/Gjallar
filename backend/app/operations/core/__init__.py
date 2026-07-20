"""Shared Operations domain contracts and persistence boundaries."""

from app.operations.core.domain import (
    EXECUTION_MODES,
    OPERATION_STATUSES,
    InvalidOperationTransition,
    OperationActor,
    OperationCreateResult,
    OperationEvent,
    OperationIntentConflict,
    OperationNotFound,
    OperationSnapshot,
    OperationSpec,
    OperationStateConflict,
    ensure_operation_transition,
    operation_digest,
    verify_event_chain,
)
from app.operations.core.ports import OperationStorePort

__all__ = [
    "EXECUTION_MODES",
    "OPERATION_STATUSES",
    "InvalidOperationTransition",
    "OperationActor",
    "OperationCreateResult",
    "OperationEvent",
    "OperationIntentConflict",
    "OperationNotFound",
    "OperationSnapshot",
    "OperationSpec",
    "OperationStateConflict",
    "OperationStorePort",
    "ensure_operation_transition",
    "operation_digest",
    "verify_event_chain",
]
