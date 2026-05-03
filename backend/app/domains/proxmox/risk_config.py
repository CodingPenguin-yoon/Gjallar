"""Operational risk threshold configuration persistence.

Thresholds are Gjallar-owned policy values. Proxmox remains a read-only
evidence source; this module only stores local dashboard policy in the
platform-state database.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any, Dict

from sqlalchemy import inspect

from app.domains.proxmox.risk import DEFAULT_THRESHOLDS
from app.shared.platform_db import (
    create_platform_engine,
    create_session_factory,
    resolve_platform_state_database_url,
)
from app.shared.platform_models import OperationalRiskThresholds

THRESHOLD_POLICY_KEY = "default"

ORDERED_THRESHOLD_PAIRS = [
    ("storage_warning_percent", "storage_critical_percent", "Storage warning threshold must be lower than or equal to critical threshold."),
    ("snapshot_warning_days", "snapshot_critical_days", "Snapshot warning threshold must be lower than or equal to critical threshold."),
    ("stopped_warning_days", "stopped_critical_days", "Stopped VM warning threshold must be lower than or equal to critical threshold."),
]


def _safe_float(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("Threshold values must be numbers, not booleans.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Threshold values must be numeric.") from exc
    if number != number:
        raise ValueError("Threshold values must be finite numbers.")
    return number


def validate_risk_thresholds(overrides: Mapping[str, Any] | None = None) -> Dict[str, float]:
    """Merge and validate risk threshold overrides against defaults."""

    thresholds = dict(DEFAULT_THRESHOLDS)
    for key, value in dict(overrides or {}).items():
        if key not in DEFAULT_THRESHOLDS:
            raise ValueError(f"Unknown risk threshold: {key}")
        thresholds[key] = _safe_float(value)

    for key in ["storage_warning_percent", "storage_critical_percent"]:
        value = thresholds[key]
        if value <= 0 or value > 100:
            raise ValueError("Storage thresholds must be between 0 and 100 percent.")

    for key in ["snapshot_warning_days", "snapshot_critical_days", "backup_warning_days", "stopped_warning_days", "stopped_critical_days"]:
        value = thresholds[key]
        if value < 1:
            raise ValueError("Day-based thresholds must be at least 1 day.")
        if value > 3650:
            raise ValueError("Day-based thresholds must be 3650 days or lower.")

    for warning_key, critical_key, message in ORDERED_THRESHOLD_PAIRS:
        if thresholds[warning_key] > thresholds[critical_key]:
            raise ValueError(message)

    return thresholds


class OperationalRiskThresholdStore:
    """Persist local operational risk threshold policy."""

    def __init__(self, database_url: str | None = None):
        self._database_url = database_url or resolve_platform_state_database_url()
        self._engine = create_platform_engine(self._database_url)
        self._session_factory = create_session_factory(self._engine)
        self._ensure_required_schema()

    def _ensure_required_schema(self) -> None:
        inspector = inspect(self._engine)
        if "operational_risk_thresholds" not in set(inspector.get_table_names()):
            raise RuntimeError(
                "Platform state DB schema is missing required table "
                "(operational_risk_thresholds). Run `cd backend && alembic upgrade head`."
            )

    def _response(self, thresholds: Dict[str, float], *, source: str, updated_at: float | None) -> Dict[str, Any]:
        return {
            "thresholds": dict(thresholds),
            "defaults": dict(DEFAULT_THRESHOLDS),
            "source": source,
            "updated_at": int(updated_at) if updated_at is not None else None,
            "database_available": True,
        }

    def get_thresholds(self) -> Dict[str, Any]:
        with self._session_factory() as session:
            record = session.get(OperationalRiskThresholds, THRESHOLD_POLICY_KEY)
            if record is None:
                return self._response(dict(DEFAULT_THRESHOLDS), source="default", updated_at=None)
            thresholds = validate_risk_thresholds(record.thresholds_json or {})
            return self._response(thresholds, source="database", updated_at=record.updated_at)

    def update_thresholds(self, updates: Mapping[str, Any]) -> Dict[str, Any]:
        with self._session_factory.begin() as session:
            record = session.get(OperationalRiskThresholds, THRESHOLD_POLICY_KEY)
            existing = record.thresholds_json if record is not None else {}
            thresholds = validate_risk_thresholds({**dict(existing or {}), **dict(updates or {})})
            now_epoch = time.time()
            if record is None:
                record = OperationalRiskThresholds(
                    key=THRESHOLD_POLICY_KEY,
                    thresholds_json=thresholds,
                    updated_at=now_epoch,
                )
                session.add(record)
            else:
                record.thresholds_json = thresholds
                record.updated_at = now_epoch
            session.flush()
            return self._response(thresholds, source="database", updated_at=now_epoch)

    def reset_thresholds(self) -> Dict[str, Any]:
        with self._session_factory.begin() as session:
            record = session.get(OperationalRiskThresholds, THRESHOLD_POLICY_KEY)
            if record is not None:
                session.delete(record)
        return self._response(dict(DEFAULT_THRESHOLDS), source="default", updated_at=None)
