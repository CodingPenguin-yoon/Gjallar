"""Bounded, secret-safe external operation evidence helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_PROXMOX_UPID = re.compile(r"^UPID:[A-Za-z0-9_.:@!+-]{1,500}$")
_PROXMOX_VM_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")


def compact_proxmox_error_details(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Keep only allowlisted error metadata; never retain raw bodies or paths."""

    details = dict(value or {})
    evidence: dict[str, Any] = {}
    try:
        status_code = int(details.get("status_code") or 0)
    except (TypeError, ValueError, OverflowError):
        status_code = 0
    if 100 <= status_code <= 599:
        evidence["status_code"] = status_code
    method = str(details.get("method") or "").strip().upper()
    if method in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        evidence["method"] = method
    error_code = str(details.get("error_code") or details.get("code") or "").strip()
    if error_code and re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", error_code):
        evidence["error_code"] = error_code
    response_json = details.get("response_json")
    response_errors = (
        response_json.get("errors")
        if isinstance(response_json, Mapping)
        and isinstance(response_json.get("errors"), Mapping)
        else {}
    )
    direct_invalid_fields = details.get("invalid_fields")
    if not isinstance(direct_invalid_fields, (list, tuple, set, frozenset)):
        direct_invalid_fields = []
    invalid_fields = sorted(
        {
            str(field)
            for field in [*response_errors, *direct_invalid_fields]
            if re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", str(field))
        }
    )[:20]
    if invalid_fields:
        evidence["invalid_fields"] = invalid_fields
    return evidence


def compact_proxmox_connection_evidence(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Describe connection mode without URL or credential identity."""

    context = dict(value or {})
    result: dict[str, Any] = {}
    mode = str(context.get("mode") or "").strip()
    if mode:
        result["mode"] = mode[:80]
    if isinstance(context.get("tls_insecure"), bool):
        result["tls_insecure"] = context["tls_insecure"]
    for key in ("task_timeout_seconds", "connect_timeout_seconds", "read_timeout_seconds"):
        value = context.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result[key] = float(value)
    return result


def compact_proxmox_task(
    value: Mapping[str, Any] | None,
    *,
    node: str = "",
    upid: str = "",
) -> dict[str, Any]:
    task = dict(value or {})
    status = str(task.get("status") or "").strip().lower()
    if status not in {"running", "stopped", "queued", "failed", "unknown"}:
        status = "unknown" if status else ""
    raw_exitstatus = str(task.get("exitstatus") or "").strip().upper()
    if raw_exitstatus == "OK":
        exitstatus = "OK"
    elif raw_exitstatus in {"", "UNKNOWN"}:
        exitstatus = raw_exitstatus
    else:
        exitstatus = "ERROR"
    selected_upid = str(upid or task.get("upid") or "").strip()
    if selected_upid and _PROXMOX_UPID.fullmatch(selected_upid) is None:
        selected_upid = ""
    return {
        # A caller-supplied locator is authoritative. Proxmox response fields
        # are observations, not permission to change the bound target/task.
        "node": str(node or task.get("node") or "")[:255],
        "upid": selected_upid,
        "status": status,
        "exitstatus": exitstatus,
    }


def compact_proxmox_vm_status(
    value: Mapping[str, Any] | None,
    *,
    node: str,
    vmid: int,
) -> dict[str, Any]:
    status = dict(value or {})
    power_status = str(status.get("status") or "").strip().lower()
    if power_status not in {"running", "stopped", "paused", "suspended", "unknown"}:
        power_status = "unknown" if power_status else ""
    name = str(status.get("name") or "").strip()
    if name and _PROXMOX_VM_NAME.fullmatch(name) is None:
        name = "unknown"
    return {
        # The requested locator remains authoritative even when an upstream
        # payload contains a conflicting node/vmid pair.
        "node_id": str(node)[:255],
        "vmid": int(vmid),
        "name": name,
        "status": power_status,
    }


__all__ = [
    "compact_proxmox_connection_evidence",
    "compact_proxmox_error_details",
    "compact_proxmox_task",
    "compact_proxmox_vm_status",
]
