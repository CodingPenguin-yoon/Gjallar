"""Gjallar-owned acknowledge/suppress state for operational risk items.

Proxmox remains a read-only evidence source. This module only persists local
dashboard workflow metadata in the platform-state database.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, Mapping

from sqlalchemy import inspect

from app.shared.platform_db import (
    create_platform_engine,
    create_session_factory,
    resolve_platform_state_database_url,
)
from app.shared.platform_models import OperationalRiskOverride

ALLOWED_RISK_OVERRIDE_STATUSES = {"acknowledged", "suppressed"}
MAX_RISK_ID_LENGTH = 512
MAX_REASON_LENGTH = 2_000
DEFAULT_UPDATED_BY = "local"


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


class OperationalRiskOverrideStore:
    """Persist local acknowledge/suppress state for deterministic risk IDs."""

    def __init__(self, database_url: str | None = None):
        self._database_url = database_url or resolve_platform_state_database_url()
        self._engine = create_platform_engine(self._database_url)
        self._session_factory = create_session_factory(self._engine)
        self._ensure_required_schema()

    def _ensure_required_schema(self) -> None:
        inspector = inspect(self._engine)
        if "operational_risk_overrides" not in set(inspector.get_table_names()):
            raise RuntimeError(
                "Platform state DB schema is missing required table "
                "(operational_risk_overrides). Run `cd backend && alembic upgrade head`."
            )

    def _normalize_risk_id(self, risk_id: Any) -> str:
        normalized = str(risk_id or "").strip()
        if not normalized:
            raise ValueError("risk_id is required.")
        if len(normalized) > MAX_RISK_ID_LENGTH:
            raise ValueError(f"risk_id must be {MAX_RISK_ID_LENGTH} characters or shorter.")
        return normalized

    def _normalize_status(self, status: Any) -> str:
        normalized = str(status or "").strip().lower()
        if normalized not in ALLOWED_RISK_OVERRIDE_STATUSES:
            allowed = ", ".join(sorted(ALLOWED_RISK_OVERRIDE_STATUSES))
            raise ValueError(f"status must be one of: {allowed}.")
        return normalized

    def _normalize_reason(self, reason: Any | None) -> str:
        normalized = str(reason or "").strip()
        if len(normalized) > MAX_REASON_LENGTH:
            raise ValueError(f"reason must be {MAX_REASON_LENGTH} characters or shorter.")
        return normalized

    def _normalize_updated_by(self, updated_by: Any | None) -> str:
        normalized = str(updated_by or DEFAULT_UPDATED_BY).strip() or DEFAULT_UPDATED_BY
        return normalized[:128]

    def _record_to_dict(self, record: OperationalRiskOverride) -> Dict[str, Any]:
        updated_at = _safe_float(record.updated_at, 0.0) or 0.0
        expires_at = _safe_float(record.expires_at)
        return {
            "risk_id": record.risk_id,
            "status": record.status,
            "reason": record.reason or "",
            "updated_at": int(updated_at),
            "expires_at": int(expires_at) if expires_at is not None else None,
            "updated_by": record.updated_by or DEFAULT_UPDATED_BY,
        }

    def list_active_overrides(self, *, now: Any | None = None) -> Dict[str, Dict[str, Any]]:
        now_epoch = _now_epoch(now)
        active: Dict[str, Dict[str, Any]] = {}
        with self._session_factory() as session:
            records = session.query(OperationalRiskOverride).all()
            for record in records:
                expires_at = _safe_float(record.expires_at)
                if expires_at is not None and expires_at <= now_epoch:
                    continue
                try:
                    self._normalize_status(record.status)
                except ValueError:
                    continue
                active[record.risk_id] = self._record_to_dict(record)
        return dict(sorted(active.items()))

    def upsert_override(
        self,
        risk_id: Any,
        status: Any,
        *,
        reason: Any | None = None,
        expires_at: Any | None = None,
        updated_by: Any | None = DEFAULT_UPDATED_BY,
        updated_at: Any | None = None,
    ) -> Dict[str, Any]:
        normalized_risk_id = self._normalize_risk_id(risk_id)
        normalized_status = self._normalize_status(status)
        normalized_reason = self._normalize_reason(reason)
        normalized_updated_by = self._normalize_updated_by(updated_by)
        normalized_updated_at = _now_epoch(updated_at)
        normalized_expires_at = _safe_float(expires_at)
        if expires_at is not None and normalized_expires_at is None:
            raise ValueError("expires_at must be a finite numeric epoch timestamp or null.")
        if normalized_expires_at is not None and normalized_expires_at <= normalized_updated_at:
            raise ValueError("expires_at must be greater than updated_at.")

        with self._session_factory.begin() as session:
            record = session.get(OperationalRiskOverride, normalized_risk_id)
            if record is None:
                record = OperationalRiskOverride(
                    risk_id=normalized_risk_id,
                    status=normalized_status,
                    reason=normalized_reason,
                    updated_at=normalized_updated_at,
                    expires_at=normalized_expires_at,
                    updated_by=normalized_updated_by,
                )
                session.add(record)
            else:
                record.status = normalized_status
                record.reason = normalized_reason
                record.updated_at = normalized_updated_at
                record.expires_at = normalized_expires_at
                record.updated_by = normalized_updated_by
            session.flush()
            return self._record_to_dict(record)

    def update_override(self, updates: Mapping[str, Any]) -> Dict[str, Any]:
        return self.upsert_override(
            updates.get("risk_id"),
            updates.get("status"),
            reason=updates.get("reason"),
            expires_at=updates.get("expires_at"),
            updated_by=updates.get("updated_by") or DEFAULT_UPDATED_BY,
        )

    def clear_override(self, risk_id: Any) -> Dict[str, Any]:
        normalized_risk_id = self._normalize_risk_id(risk_id)
        cleared = False
        with self._session_factory.begin() as session:
            record = session.get(OperationalRiskOverride, normalized_risk_id)
            if record is not None:
                session.delete(record)
                cleared = True
        return {"risk_id": normalized_risk_id, "cleared": cleared}
