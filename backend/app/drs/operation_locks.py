"""Read-only DRS operation lock lookup helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.models import OperationLockRecord
from app.db.session import session_scope
from app.drs.identity import DEFAULT_CLUSTER_ID

DRS_MIGRATION_OPERATION_TYPE = "drs_migration"
OPEN_LOCK_STATUSES = ("active", "stale", "reconciliation_required")
LOCK_STATUS_BLOCKERS = {
    "active": "operation_lock_active",
    "stale": "operation_lock_stale",
    "reconciliation_required": "operation_lock_reconciliation_required",
}
_COMPACT_EVIDENCE_KEYS = {
    "source",
    "reason",
    "recommendation_id",
    "operation",
    "scope",
    "owner",
}


def _as_text(value: Any, fallback: str = "") -> str:
    text = str(value if value is not None else "").strip()
    return text or fallback


def _as_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _segment(value: Any, fallback: str = "unknown") -> str:
    return _as_text(value, fallback).replace("|", "-")


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def identity_scope_key(cluster_id: str, vm_identity_id: str | None) -> str:
    return f"{_segment(cluster_id, DEFAULT_CLUSTER_ID)}|vm_identity|{_segment(vm_identity_id)}"


def locator_scope_key(cluster_id: str, vmid: int | str | None) -> str:
    return f"{_segment(cluster_id, DEFAULT_CLUSTER_ID)}|proxmox_locator|{_as_int(vmid)}"


def route_scope_key(cluster_id: str, source_node_id: str | None, target_node_id: str | None) -> str:
    return f"{_segment(cluster_id, DEFAULT_CLUSTER_ID)}|route|{_segment(source_node_id)}|{_segment(target_node_id)}"


def operation_lock_scopes(
    *,
    cluster_id: str,
    vm_identity_id: str | None,
    vmid: int | str | None,
    source_node_id: str | None,
    target_node_id: str | None,
) -> list[dict[str, str]]:
    normalized_cluster_id = _as_text(cluster_id, DEFAULT_CLUSTER_ID)
    return [
        {
            "scope_type": "vm_identity",
            "scope_key": identity_scope_key(normalized_cluster_id, vm_identity_id),
        },
        {
            "scope_type": "proxmox_locator",
            "scope_key": locator_scope_key(normalized_cluster_id, vmid),
        },
        {
            "scope_type": "route",
            "scope_key": route_scope_key(normalized_cluster_id, source_node_id, target_node_id),
        },
    ]


def _compact_row_evidence(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in sorted(value) if key in _COMPACT_EVIDENCE_KEYS}


def _lock_to_evidence(row: OperationLockRecord) -> dict[str, Any]:
    return {
        "operation_lock_id": row.operation_lock_id,
        "operation_type": row.operation_type,
        "scope_type": row.scope_type,
        "scope_key": row.scope_key,
        "status": row.status,
        "cluster_id": row.cluster_id,
        "vm_identity_id": row.vm_identity_id,
        "vmid": row.vmid,
        "source_node_id": row.source_node_id,
        "target_node_id": row.target_node_id,
        "owner_id": row.owner_id,
        "reason": row.reason,
        "evidence": _compact_row_evidence(row.evidence),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "expires_at": _iso(row.expires_at),
        "released_at": _iso(row.released_at),
    }


def query_open_locks_for_scopes(
    session: Session,
    scopes: list[dict[str, str]],
    *,
    operation_type: str = DRS_MIGRATION_OPERATION_TYPE,
) -> list[OperationLockRecord]:
    """Return open DRS locks matching any checked scope without mutating state."""
    filters = [
        and_(
            OperationLockRecord.scope_type == scope["scope_type"],
            OperationLockRecord.scope_key == scope["scope_key"],
        )
        for scope in scopes
    ]
    if not filters:
        return []
    return list(
        session.execute(
            select(OperationLockRecord)
            .where(
                OperationLockRecord.operation_type == operation_type,
                OperationLockRecord.status.in_(OPEN_LOCK_STATUSES),
                or_(*filters),
            )
            .order_by(
                OperationLockRecord.scope_type,
                OperationLockRecord.status,
                OperationLockRecord.created_at,
                OperationLockRecord.operation_lock_id,
            )
        ).scalars()
    )


def lock_blockers(lock_evidence: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    seen: set[str] = set()
    for lock in lock_evidence.get("matching_locks", []):
        blocker = LOCK_STATUS_BLOCKERS.get(_as_text(lock.get("status")))
        if blocker and blocker not in seen:
            seen.add(blocker)
            blockers.append(blocker)
    return blockers


def recommendation_lock_evidence(
    *,
    cluster_id: str,
    vm_identity_id: str | None,
    vmid: int | str | None,
    source_node_id: str | None,
    target_node_id: str | None,
) -> dict[str, Any]:
    """Build compact read-only lock evidence for a DRS recommendation route."""
    normalized_cluster_id = _as_text(cluster_id, DEFAULT_CLUSTER_ID)
    scopes = operation_lock_scopes(
        cluster_id=normalized_cluster_id,
        vm_identity_id=vm_identity_id,
        vmid=vmid,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
    )
    with session_scope() as session:
        locks = query_open_locks_for_scopes(session, scopes)
    matching = [_lock_to_evidence(lock) for lock in locks]
    statuses = sorted({lock["status"] for lock in matching})
    return {
        "operation_type": DRS_MIGRATION_OPERATION_TYPE,
        "cluster_id": normalized_cluster_id,
        "open_statuses": list(OPEN_LOCK_STATUSES),
        "checked_scopes": scopes,
        "matching_locks": matching,
        "matching_statuses": statuses,
        "blocking": bool(matching),
    }
