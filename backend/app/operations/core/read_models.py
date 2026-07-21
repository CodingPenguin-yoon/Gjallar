"""Stable read models shared by Operations application services."""

from __future__ import annotations

from typing import Any

from app.operations.core.domain import OperationEvent, OperationSnapshot


def operation_payload(operation: OperationSnapshot, *, include_details: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "operation_id": operation.operation_id,
        "operation_type": operation.operation_type,
        "execution_mode": operation.execution_mode,
        "status": operation.status,
        "target_type": operation.target_type,
        "target_id": operation.target_id,
        "idempotency_key": operation.idempotency_key,
        "intent_digest": operation.intent_digest,
        "plan_digest": operation.plan_digest,
        "current_stage": operation.current_stage,
        "actor": operation.actor.to_dict(),
        "expires_at": operation.expires_at.isoformat() if operation.expires_at else None,
        "version": operation.version,
        "last_event_checksum": operation.last_event_checksum,
        "created_at": operation.created_at.isoformat(),
        "updated_at": operation.updated_at.isoformat(),
    }
    if include_details:
        payload["details"] = dict(operation.details)
    return payload


def operation_event_payload(event: OperationEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "operation_id": event.operation_id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "from_status": event.from_status,
        "to_status": event.to_status,
        "stage": event.stage,
        "actor": event.actor.to_dict(),
        "payload": dict(event.payload),
        "previous_checksum": event.previous_checksum,
        "checksum": event.checksum,
        "created_at": event.created_at.isoformat(),
    }
