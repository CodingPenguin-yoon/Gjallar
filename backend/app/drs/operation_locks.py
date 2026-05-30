"""DRS operation lock lookup and acquisition helpers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
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
    "approval_packet_id",
    "job_id",
    "source",
    "reason",
    "recommendation_id",
    "operation",
    "scope",
    "owner",
    "upid",
    "task_result",
    "reconciliation_reason",
    "source_node_id",
    "target_node_id",
    "vmid",
    "post_check_status",
    "post_check_reason",
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


def compact_lock_rows(rows: list[OperationLockRecord]) -> list[dict[str, Any]]:
    return [_lock_to_evidence(row) for row in rows]


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


def _blocked_acquisition_result(scopes: list[dict[str, str]], locks: list[OperationLockRecord]) -> dict[str, Any]:
    lock_evidence = compact_lock_rows(locks)
    return {
        "acquired": False,
        "checked_scopes": scopes,
        "locks": [],
        "lock_ids": [],
        "matching_locks": lock_evidence,
        "matching_statuses": sorted({lock["status"] for lock in lock_evidence}),
        "blockers": lock_blockers({"matching_locks": lock_evidence}) or ["operation_lock_active"],
    }


def acquire_drs_operation_locks(
    session: Session,
    *,
    cluster_id: str,
    vm_identity_id: str | None,
    vmid: int | str | None,
    source_node_id: str | None,
    target_node_id: str | None,
    owner_id: str,
    reason: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create active VM identity, locator, and route locks if all scopes are open."""
    normalized_cluster_id = _as_text(cluster_id, DEFAULT_CLUSTER_ID)
    scopes = operation_lock_scopes(
        cluster_id=normalized_cluster_id,
        vm_identity_id=vm_identity_id,
        vmid=vmid,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
    )
    existing = query_open_locks_for_scopes(session, scopes)
    if existing:
        return _blocked_acquisition_result(scopes, existing)

    now = _now()
    compact_evidence = dict(evidence or {})
    rows: list[OperationLockRecord] = []
    for scope in scopes:
        lock = OperationLockRecord(
            operation_lock_id=f"drslock-{uuid.uuid4().hex}",
            operation_type=DRS_MIGRATION_OPERATION_TYPE,
            scope_type=scope["scope_type"],
            scope_key=scope["scope_key"],
            status="active",
            cluster_id=normalized_cluster_id,
            vm_identity_id=_as_text(vm_identity_id) or None,
            vmid=_as_int(vmid) or None,
            source_node_id=_as_text(source_node_id) or None,
            target_node_id=_as_text(target_node_id) or None,
            owner_id=_as_text(owner_id) or None,
            reason=_as_text(reason, "drs_migration_execution"),
            evidence=compact_evidence,
            created_at=now,
            updated_at=now,
        )
        session.add(lock)
        rows.append(lock)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        return _blocked_acquisition_result(scopes, query_open_locks_for_scopes(session, scopes))
    locks = compact_lock_rows(rows)
    return {
        "acquired": True,
        "checked_scopes": scopes,
        "locks": locks,
        "lock_ids": [lock["operation_lock_id"] for lock in locks],
        "matching_locks": [],
        "matching_statuses": [],
        "blockers": [],
    }


def mark_locks_reconciliation_required(
    session: Session,
    *,
    lock_ids: list[str],
    reason: str,
    evidence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Conservatively mark active DRS locks as requiring reconciliation."""
    if not lock_ids:
        return []
    now = _now()
    rows = list(
        session.execute(
            select(OperationLockRecord)
            .where(
                OperationLockRecord.operation_lock_id.in_(lock_ids),
                OperationLockRecord.operation_type == DRS_MIGRATION_OPERATION_TYPE,
            )
            .order_by(OperationLockRecord.scope_type, OperationLockRecord.operation_lock_id)
        ).scalars()
    )
    for row in rows:
        if row.status == "released":
            continue
        row.status = "reconciliation_required"
        row.reason = _as_text(reason, "drs_migration_reconciliation_required")
        row.evidence = {**_compact_row_evidence(row.evidence), **_compact_row_evidence(evidence or {})}
        row.updated_at = now
    session.flush()
    return compact_lock_rows(rows)


def release_drs_operation_locks(
    session: Session,
    *,
    lock_ids: list[str],
    reason: str,
    evidence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Release DRS locks after verified safe completion."""
    if not lock_ids:
        return []
    now = _now()
    rows = list(
        session.execute(
            select(OperationLockRecord)
            .where(
                OperationLockRecord.operation_lock_id.in_(lock_ids),
                OperationLockRecord.operation_type == DRS_MIGRATION_OPERATION_TYPE,
            )
            .order_by(OperationLockRecord.scope_type, OperationLockRecord.operation_lock_id)
        ).scalars()
    )
    for row in rows:
        if row.status == "released":
            continue
        row.status = "released"
        row.reason = _as_text(reason, "drs_migration_completed")
        row.evidence = {**_compact_row_evidence(row.evidence), **_compact_row_evidence(evidence or {})}
        row.released_at = now
        row.updated_at = now
    session.flush()
    return compact_lock_rows(rows)


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
