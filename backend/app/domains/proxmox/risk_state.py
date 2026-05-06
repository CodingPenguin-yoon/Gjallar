"""Gjallar-owned operational risk state persistence.

Proxmox remains a read-only evidence source. This module stores Gjallar's own
observations, such as when a VM was first observed in a stopped state, in the
platform-state database so risk checks survive backend restarts.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any, Dict

from sqlalchemy import inspect

from app.shared.platform_db import (
    create_platform_engine,
    create_session_factory,
    resolve_platform_state_database_url,
)
from app.shared.platform_models import OperationalVMState

SECONDS_PER_DAY = 86_400
INACTIVE_VM_STATE_RETENTION_DAYS = 30
INACTIVE_VM_STATE_RETENTION_SECONDS = INACTIVE_VM_STATE_RETENTION_DAYS * SECONDS_PER_DAY


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number else default


def _now_epoch(now: Any | None = None) -> float:
    if now is None:
        return time.time()
    if hasattr(now, "timestamp"):
        return float(now.timestamp())
    return _safe_float(now, time.time())


class OperationalRiskStateStore:
    """Persist VM observation state for operational risk calculations."""

    def __init__(self, database_url: str | None = None, *, inactive_retention_days: int = INACTIVE_VM_STATE_RETENTION_DAYS):
        self._database_url = database_url or resolve_platform_state_database_url()
        self._inactive_retention_seconds = max(0, int(inactive_retention_days)) * SECONDS_PER_DAY
        self._engine = create_platform_engine(self._database_url)
        self._session_factory = create_session_factory(self._engine)
        self._ensure_required_schema()

    def _ensure_required_schema(self) -> None:
        inspector = inspect(self._engine)
        existing_tables = set(inspector.get_table_names())
        if "operational_vm_state" not in existing_tables:
            raise RuntimeError(
                "Platform state DB schema is missing required table "
                "(operational_vm_state). Run `cd backend && alembic upgrade head`."
            )

        existing_columns = {column["name"] for column in inspector.get_columns("operational_vm_state")}
        required_columns = {
            "active",
            "missing_since_at",
            "lifecycle_generation",
        }
        missing_columns = sorted(required_columns - existing_columns)
        if missing_columns:
            raise RuntimeError(
                "Platform state DB schema is missing required operational_vm_state columns "
                f"({', '.join(missing_columns)}). Run `cd backend && alembic upgrade head`."
            )

    def _resource_type(self, vm: Mapping[str, Any]) -> str:
        raw = str(vm.get("type") or vm.get("vm_type") or vm.get("resource_type") or "qemu").strip().lower()
        return raw or "qemu"

    def _resource_key(self, vm: Mapping[str, Any]) -> str | None:
        vmid = _safe_int(vm.get("vmid"), 0)
        if vmid <= 0:
            return None
        return f"{self._resource_type(vm)}:{vmid}"

    def _dashboard_key(self, record: OperationalVMState) -> str:
        return f"{record.node}/{record.vmid}"

    def _safe_payload(self, vm: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "node": vm.get("node"),
            "vmid": vm.get("vmid"),
            "name": vm.get("name") or vm.get("server_name"),
            "status": vm.get("status"),
            "tags": vm.get("tags", []),
            "description_present": bool(vm.get("description") or vm.get("notes")),
        }

    def _history_for_record(self, record: OperationalVMState, *, observed_at: float) -> Dict[str, Any]:
        status = str(record.status or "unknown").strip().lower()
        status_since = _safe_float(record.status_since_at, observed_at)
        stopped_since = status_since if status == "stopped" else None
        stopped_days = None
        if stopped_since is not None:
            stopped_days = round(max(0.0, (observed_at - stopped_since) / SECONDS_PER_DAY), 1)

        missing_since = getattr(record, "missing_since_at", None)
        return {
            "resource_key": record.resource_key,
            "resource_type": record.resource_type,
            "node": record.node,
            "vmid": record.vmid,
            "name": record.name,
            "status": status,
            "active": bool(getattr(record, "active", True)),
            "first_seen_at": int(record.first_seen_at),
            "last_seen_at": int(record.last_seen_at),
            "missing_since": int(missing_since) if missing_since is not None else None,
            "status_since": int(status_since),
            "last_running_at": int(record.last_running_at) if record.last_running_at is not None else None,
            "stopped_since": int(stopped_since) if stopped_since is not None else None,
            "stopped_days": stopped_days,
            "lifecycle_generation": _safe_int(getattr(record, "lifecycle_generation", 1), 1),
            "source": "gjallar_db",
        }

    def _purge_inactive_records(self, session: Any, *, observed_epoch: float) -> None:
        if self._inactive_retention_seconds <= 0:
            return
        cutoff = observed_epoch - self._inactive_retention_seconds
        inactive_records = (
            session.query(OperationalVMState)
            .filter(OperationalVMState.active.is_(False))
            .all()
        )
        for record in inactive_records:
            missing_since = _safe_float(record.missing_since_at, observed_epoch)
            if missing_since <= cutoff:
                session.delete(record)


    def observe_vms(
        self,
        vms: Sequence[Mapping[str, Any]],
        *,
        observed_at: Any | None = None,
        reconcile_missing: bool = False,
    ) -> Dict[str, Dict[str, Any]]:
        """Persist latest VM observations and return dashboard-keyed history evidence.

        By default this method only records the VMs it was given. Missing-VM
        reconciliation is fail-closed and must be explicitly enabled by a caller
        that has already proven the input is a complete cluster-wide snapshot.
        An empty snapshot is treated conservatively as possibly uncollected
        evidence and does not mark every known VM missing.
        """

        observed_epoch = _now_epoch(observed_at)
        history: Dict[str, Dict[str, Any]] = {}
        observations: list[tuple[Mapping[str, Any], str, int, str, str, str, str]] = []
        seen_resource_keys: set[str] = set()

        for vm in vms or []:
            if not isinstance(vm, Mapping):
                continue
            node = str(vm.get("node") or "").strip()
            vmid = _safe_int(vm.get("vmid"), 0)
            if not node or vmid <= 0:
                continue

            resource_key = self._resource_key(vm)
            if not resource_key:
                continue

            status = str(vm.get("status") or "unknown").strip().lower() or "unknown"
            name = str(vm.get("name") or vm.get("server_name") or f"vm-{vmid}")
            resource_type = self._resource_type(vm)
            observations.append((vm, node, vmid, resource_key, status, name, resource_type))
            seen_resource_keys.add(resource_key)

        if not observations:
            with self._session_factory.begin() as session:
                self._purge_inactive_records(session, observed_epoch=observed_epoch)
            return history

        with self._session_factory.begin() as session:
            for vm, node, vmid, resource_key, status, name, resource_type in observations:
                record = session.get(OperationalVMState, resource_key)
                if record is None:
                    record = OperationalVMState(
                        resource_key=resource_key,
                        resource_type=resource_type,
                        node=node,
                        vmid=vmid,
                        name=name,
                        status=status,
                        active=True,
                        first_seen_at=observed_epoch,
                        last_seen_at=observed_epoch,
                        missing_since_at=None,
                        status_since_at=observed_epoch,
                        last_running_at=observed_epoch if status == "running" else None,
                        lifecycle_generation=1,
                        last_observed_payload_json=self._safe_payload(vm),
                    )
                    session.add(record)
                else:
                    was_inactive = not bool(getattr(record, "active", True))
                    previous_status = str(record.status or "unknown").strip().lower()
                    if was_inactive:
                        record.first_seen_at = observed_epoch
                        record.status_since_at = observed_epoch
                        record.last_running_at = observed_epoch if status == "running" else None
                        record.lifecycle_generation = _safe_int(getattr(record, "lifecycle_generation", 1), 1) + 1
                    elif previous_status != status:
                        record.status_since_at = observed_epoch

                    record.resource_type = resource_type
                    record.node = node
                    record.vmid = vmid
                    record.name = name
                    record.status = status
                    record.active = True
                    record.missing_since_at = None
                    record.last_seen_at = observed_epoch
                    if status == "running":
                        record.last_running_at = observed_epoch
                    record.last_observed_payload_json = self._safe_payload(vm)

                session.flush()
                history[self._dashboard_key(record)] = self._history_for_record(record, observed_at=observed_epoch)

            if reconcile_missing is True:
                active_records = (
                    session.query(OperationalVMState)
                    .filter(OperationalVMState.active.is_(True))
                    .all()
                )
                for record in active_records:
                    if record.resource_key in seen_resource_keys:
                        continue
                    record.active = False
                    if record.missing_since_at is None:
                        record.missing_since_at = observed_epoch

            self._purge_inactive_records(session, observed_epoch=observed_epoch)

        return history
