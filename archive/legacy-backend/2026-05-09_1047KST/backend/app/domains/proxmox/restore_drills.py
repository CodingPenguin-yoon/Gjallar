"""Gjallar-owned restore drill record persistence.

Restore drill records are local evidence only: this module never calls PBS,
Proxmox, or guest-level restore APIs. Operators can record outcomes from
manual/external drills so the operational risk dashboard can reason about
missing, stale, or failed restore validation.
"""

from __future__ import annotations

import math
import time
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Dict

from sqlalchemy import inspect

from app.shared.platform_db import (
    create_platform_engine,
    create_session_factory,
    resolve_platform_state_database_url,
)
from app.shared.platform_models import OperationalRestoreDrill

SECONDS_PER_DAY = 86_400
ALLOWED_RESTORE_DRILL_OUTCOMES = {"passed", "failed", "partial", "blocked"}
DEFAULT_RESOURCE_TYPE = "qemu"
DEFAULT_RECORDED_BY = "local"
MAX_DRILL_ID_LENGTH = 64
MAX_NODE_LENGTH = 128
MAX_RESOURCE_TYPE_LENGTH = 32
MAX_OUTCOME_LENGTH = 32
MAX_NOTES_LENGTH = 4_000


def _safe_int(value: Any, default: int | None = None) -> int | None:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None or isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _now_epoch(now: Any | None = None) -> float:
    if now is None:
        return time.time()
    if hasattr(now, "timestamp"):
        return float(now.timestamp())
    value = _safe_float(now)
    return value if value is not None else time.time()


def _normalize_text(value: Any, *, default: str = "", max_length: int | None = None) -> str:
    text = str(value if value is not None else default).strip()
    if not text:
        text = default
    if max_length is not None:
        text = text[:max_length]
    return text


class OperationalRestoreDrillStore:
    """Persist local restore drill records for dashboard evidence."""

    def __init__(self, database_url: str | None = None):
        self._database_url = database_url or resolve_platform_state_database_url()
        self._engine = create_platform_engine(self._database_url)
        self._session_factory = create_session_factory(self._engine)
        self._ensure_required_schema()

    def _ensure_required_schema(self) -> None:
        inspector = inspect(self._engine)
        existing_tables = set(inspector.get_table_names())
        if "operational_restore_drills" not in existing_tables:
            raise RuntimeError(
                "Platform state DB schema is missing required table "
                "(operational_restore_drills). Run `cd backend && alembic upgrade head`."
            )

        existing_columns = {column["name"] for column in inspector.get_columns("operational_restore_drills")}
        required_columns = {
            "drill_id",
            "resource_type",
            "node",
            "vmid",
            "outcome",
            "drilled_at",
            "recorded_at",
            "evidence_json",
        }
        missing_columns = sorted(required_columns - existing_columns)
        if missing_columns:
            raise RuntimeError(
                "Platform state DB schema is missing required operational_restore_drills columns "
                f"({', '.join(missing_columns)}). Run `cd backend && alembic upgrade head`."
            )

    def _normalize_drill_id(self, value: Any | None = None) -> str:
        drill_id = _normalize_text(value or uuid.uuid4().hex, max_length=MAX_DRILL_ID_LENGTH)
        if not drill_id:
            raise ValueError("drill_id is required.")
        return drill_id

    def _normalize_resource_type(self, value: Any | None = None) -> str:
        resource_type = _normalize_text(value, default=DEFAULT_RESOURCE_TYPE, max_length=MAX_RESOURCE_TYPE_LENGTH).lower()
        return resource_type or DEFAULT_RESOURCE_TYPE

    def _normalize_node(self, value: Any) -> str:
        node = _normalize_text(value, max_length=MAX_NODE_LENGTH)
        if not node:
            raise ValueError("node is required.")
        return node

    def _normalize_vmid(self, value: Any) -> int:
        vmid = _safe_int(value)
        if vmid is None or vmid <= 0:
            raise ValueError("vmid must be a positive integer.")
        return vmid

    def _normalize_outcome(self, value: Any) -> str:
        outcome = _normalize_text(value, max_length=MAX_OUTCOME_LENGTH).lower()
        if outcome not in ALLOWED_RESTORE_DRILL_OUTCOMES:
            allowed = ", ".join(sorted(ALLOWED_RESTORE_DRILL_OUTCOMES))
            raise ValueError(f"outcome must be one of: {allowed}.")
        return outcome

    def _normalize_evidence(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        evidence = payload.get("evidence_json", payload.get("evidence", {}))
        if evidence is None:
            return {}
        if not isinstance(evidence, Mapping):
            raise ValueError("evidence must be an object.")
        return dict(evidence)

    def _record_to_dict(self, record: OperationalRestoreDrill) -> Dict[str, Any]:
        return {
            "drill_id": record.drill_id,
            "resource_type": record.resource_type or DEFAULT_RESOURCE_TYPE,
            "node": record.node,
            "vmid": int(record.vmid),
            "vm_name": record.vm_name or "",
            "datastore": record.datastore or "",
            "snapshot": record.snapshot or "",
            "outcome": record.outcome,
            "drilled_at": int(record.drilled_at),
            "recorded_at": int(record.recorded_at),
            "recorded_by": record.recorded_by or DEFAULT_RECORDED_BY,
            "notes": record.notes or "",
            "evidence": dict(record.evidence_json or {}),
        }

    def record_drill(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        """Record a manual/external restore drill outcome in Gjallar local DB."""

        data = dict(payload or {})
        drilled_at = _safe_float(data.get("drilled_at"))
        if drilled_at is None:
            raise ValueError("drilled_at is required and must be a finite epoch timestamp.")
        recorded_at = _now_epoch(data.get("recorded_at"))
        if drilled_at > recorded_at:
            raise ValueError("drilled_at must not be in the future.")

        record = OperationalRestoreDrill(
            drill_id=self._normalize_drill_id(data.get("drill_id")),
            resource_type=self._normalize_resource_type(data.get("resource_type")),
            node=self._normalize_node(data.get("node")),
            vmid=self._normalize_vmid(data.get("vmid")),
            vm_name=_normalize_text(data.get("vm_name") or data.get("name")),
            datastore=_normalize_text(data.get("datastore")),
            snapshot=_normalize_text(data.get("snapshot")),
            outcome=self._normalize_outcome(data.get("outcome")),
            drilled_at=drilled_at,
            recorded_at=recorded_at,
            recorded_by=_normalize_text(data.get("recorded_by"), default=DEFAULT_RECORDED_BY),
            notes=_normalize_text(data.get("notes"), max_length=MAX_NOTES_LENGTH),
            evidence_json=self._normalize_evidence(data),
        )

        with self._session_factory.begin() as session:
            session.add(record)
            session.flush()
            return self._record_to_dict(record)

    def list_drills(self, *, node: Any | None = None, vmid: Any | None = None, limit: Any = 100) -> list[Dict[str, Any]]:
        """List restore drill records, newest first."""

        normalized_node = self._normalize_node(node) if node is not None else None
        normalized_vmid = self._normalize_vmid(vmid) if vmid is not None else None
        normalized_limit = max(1, min(_safe_int(limit, 100) or 100, 500))

        with self._session_factory() as session:
            query = session.query(OperationalRestoreDrill)
            if normalized_node is not None:
                query = query.filter(OperationalRestoreDrill.node == normalized_node)
            if normalized_vmid is not None:
                query = query.filter(OperationalRestoreDrill.vmid == normalized_vmid)
            records = (
                query.order_by(
                    OperationalRestoreDrill.drilled_at.desc(),
                    OperationalRestoreDrill.recorded_at.desc(),
                    OperationalRestoreDrill.drill_id.desc(),
                )
                .limit(normalized_limit)
                .all()
            )
            return [self._record_to_dict(record) for record in records]

    def get_latest_successful_drill_by_vmid(self, vmid: Any) -> Dict[str, Any] | None:
        """Return the newest passed drill for a VMID, if one exists."""

        normalized_vmid = self._normalize_vmid(vmid)
        with self._session_factory() as session:
            record = (
                session.query(OperationalRestoreDrill)
                .filter(OperationalRestoreDrill.vmid == normalized_vmid)
                .filter(OperationalRestoreDrill.outcome == "passed")
                .order_by(
                    OperationalRestoreDrill.drilled_at.desc(),
                    OperationalRestoreDrill.recorded_at.desc(),
                    OperationalRestoreDrill.drill_id.desc(),
                )
                .first()
            )
            return self._record_to_dict(record) if record is not None else None

    def get_latest_restore_drill_evidence_by_vm(
        self,
        vms: Sequence[Mapping[str, Any]],
        *,
        now_epoch: Any | None = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Return dashboard-keyed latest restore drill evidence for VMs."""

        observed_epoch = _now_epoch(now_epoch)
        evidence: Dict[str, Dict[str, Any]] = {}
        with self._session_factory() as session:
            for vm in vms or []:
                if not isinstance(vm, Mapping):
                    continue
                try:
                    node = self._normalize_node(vm.get("node"))
                    vmid = self._normalize_vmid(vm.get("vmid"))
                except ValueError:
                    continue
                record = (
                    session.query(OperationalRestoreDrill)
                    .filter(OperationalRestoreDrill.node == node)
                    .filter(OperationalRestoreDrill.vmid == vmid)
                    .order_by(
                        OperationalRestoreDrill.drilled_at.desc(),
                        OperationalRestoreDrill.recorded_at.desc(),
                        OperationalRestoreDrill.drill_id.desc(),
                    )
                    .first()
                )
                if record is None:
                    continue
                item = self._record_to_dict(record)
                item["latest_drill_age_days"] = round(
                    max(0.0, (observed_epoch - float(record.drilled_at)) / SECONDS_PER_DAY),
                    1,
                )
                evidence[f"{node}/{vmid}"] = item
        return evidence
