"""Native Proxmox runner for the approval-gated Create VM path."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.jobs.artifacts import write_json_artifact
from app.proxmox.client import ProxmoxMutationClient, ProxmoxMutationError
from app.operations.core.evidence import (
    compact_proxmox_error_details,
    compact_proxmox_task,
    compact_proxmox_vm_status,
)
from app.vm_create.models import VmCreatePlan

_DISK_CONFIG_KEY_PATTERN = re.compile(r"^(ide|sata|scsi|virtio)(\d+)$")
_DISK_SIZE_PATTERN = re.compile(r"(?:^|,)size=(\d+(?:\.\d+)?)([KMGTP]?)", re.IGNORECASE)
_DISK_BUS_ORDER = {"scsi": 0, "virtio": 1, "sata": 2, "ide": 3}
_MAC_PATTERN = re.compile(r"(?i)([0-9a-f]{2}(?::[0-9a-f]{2}){5})")
_SSH_PUBLIC_KEY_PATTERN = re.compile(
    r"(?m)(?:^|\s)((?:sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com|ssh-ed25519|ssh-rsa|rsa-sha2-256|rsa-sha2-512|ecdsa-sha2-[A-Za-z0-9@._+-]+)\s+[A-Za-z0-9+/=]+(?:\s+[^\r\n]+)?)"
)
_SSH_KEY_CONFIG_KEYS = {"sshkeys", "sshkey", "ssh_public_key", "sshpublickey"}
_GUEST_AGENT_POLL_INTERVAL_SECONDS = 5.0

VmCreateCheckpoint = Callable[[str, Mapping[str, Any]], None]


def _checkpoint(
    callback: VmCreateCheckpoint | None,
    phase: str,
    evidence: Mapping[str, Any] | None = None,
) -> None:
    if callback is None:
        return
    sanitized = _sanitize_public_key_material(dict(evidence or {}))
    callback(str(phase), sanitized if isinstance(sanitized, dict) else {})


def _heartbeat(callback: Callable[[], None] | None) -> None:
    if callback is not None:
        callback()


def _wait_for_task(
    client: ProxmoxMutationClient,
    *,
    node: str,
    upid: str,
    heartbeat: Callable[[], None] | None,
) -> dict[str, Any]:
    if heartbeat is None:
        task = client.wait_for_task(node=node, upid=upid)
        return compact_proxmox_task(task, node=node, upid=upid)
    try:
        task = client.wait_for_task(node=node, upid=upid, heartbeat=heartbeat)
        return compact_proxmox_task(task, node=node, upid=upid)
    except TypeError as exc:
        # Lightweight contract-test clients can predate the optional heartbeat
        # keyword. Signature binding fails before their read-only poll runs.
        if "heartbeat" not in str(exc):
            raise
        _heartbeat(heartbeat)
        task = client.wait_for_task(node=node, upid=upid)
        return compact_proxmox_task(task, node=node, upid=upid)


def _power_policy(plan: VmCreatePlan) -> str:
    value = str(getattr(plan, "power_policy", "") or "").strip().lower()
    if value:
        return value
    return "boot_and_verify" if bool(getattr(plan, "first_power_on_included", False)) else "stopped"


def _boot_and_verify_requested(plan: VmCreatePlan) -> bool:
    return _power_policy(plan) == "boot_and_verify" or bool(getattr(plan, "first_power_on_included", False))


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sanitize_public_key_material(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[Any, Any] = {}
        for key, item in value.items():
            key_text = str(key).replace("-", "_").lower()
            if key_text in _SSH_KEY_CONFIG_KEYS:
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = _sanitize_public_key_material(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_public_key_material(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_public_key_material(item) for item in value)
    if isinstance(value, str):
        return _SSH_PUBLIC_KEY_PATTERN.sub("[REDACTED_SSH_PUBLIC_KEY]", value)
    return value


def _proxmox_sshkeys_value(ssh_key: str) -> str:
    """Proxmox expects the cloud-init sshkeys field to be URL-encoded."""
    return quote(ssh_key.strip(), safe="")


def _access_from_plan(plan: VmCreatePlan) -> dict[str, Any]:
    access = dict(getattr(plan, "access", {}) or {})
    if not access:
        access = dict((dict(plan.review_confirm).get("access") or {}))
    return access


def _template_vmid(plan: VmCreatePlan) -> int:
    value = dict(plan.review_confirm).get("template_vmid")
    if value is None or str(value).strip() == "":
        raise ProxmoxMutationError("plan review is missing template_vmid")
    return int(value)


def _template_node(plan: VmCreatePlan) -> str:
    value = str(dict(plan.review_confirm).get("template_node_id") or "").strip()
    if not value:
        raise ProxmoxMutationError("plan review is missing template_node_id")
    return value


def _required_ipv4(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ProxmoxMutationError(f"plan network is missing {field_name}")
    try:
        parsed = ip_address(text)
    except ValueError as exc:
        raise ProxmoxMutationError(f"plan network has invalid {field_name}") from exc
    if parsed.version != 4:
        raise ProxmoxMutationError(f"plan network {field_name} must be IPv4")
    return text


def _required_prefix(value: object) -> int:
    text = str(value or "").strip()
    if not text:
        raise ProxmoxMutationError("plan network is missing prefix")
    try:
        prefix = int(text)
    except (TypeError, ValueError) as exc:
        raise ProxmoxMutationError("plan network has invalid prefix") from exc
    if not 1 <= prefix <= 32:
        raise ProxmoxMutationError("plan network prefix must be between 1 and 32")
    return prefix


def _static_ipconfig_from_network(network: dict[str, Any]) -> str:
    static_ip = _required_ipv4(network.get("static_ip") or network.get("ip_address"), "static_ip")
    prefix = _required_prefix(network.get("prefix"))
    gateway = _required_ipv4(network.get("gateway"), "gateway")
    return f"ip={static_ip}/{prefix},gw={gateway}"


def clone_payload_from_plan(plan: VmCreatePlan) -> dict[str, Any]:
    """Return the Proxmox clone payload without invoking the API."""
    if not plan.storage_id:
        raise ProxmoxMutationError("plan is missing storage_id")
    return {
        "endpoint": f"/nodes/{_template_node(plan)}/qemu/{_template_vmid(plan)}/clone",
        "template_node": _template_node(plan),
        "template_vmid": _template_vmid(plan),
        "newid": int(plan.vmid),
        "name": plan.vm_name,
        "target": plan.target_node_id,
        "storage": plan.storage_id,
        "full": 1,
    }


def config_payload_from_plan(plan: VmCreatePlan) -> dict[str, Any]:
    """Return the post-clone VM config payload for native Proxmox create."""
    network = dict(plan.network or {})
    access = _access_from_plan(plan)
    bridge_id = str(network.get("bridge_id") or "").strip()
    if not bridge_id:
        raise ProxmoxMutationError("plan network is missing bridge_id")
    ip_mode = str(network.get("ip_mode") or "").lower()
    if ip_mode not in {"static", "dhcp"}:
        raise ProxmoxMutationError("plan network ip_mode must be static or dhcp")
    username = str(access.get("cloud_init_user") or access.get("username") or "").strip()
    if not username:
        raise ProxmoxMutationError("plan access is missing cloud_init_user")
    payload: dict[str, Any] = {
        "cores": int(plan.hardware.get("cpu") or 1),
        "memory": int(plan.hardware.get("memory_mb") or 1024),
        "agent": "enabled=1",
        "onboot": 0,
        "net0": f"virtio,bridge={bridge_id}",
        "ciuser": username,
    }
    ssh_key = str(getattr(plan, "transient_ssh_public_key", "") or "").strip()
    if ssh_key:
        payload["sshkeys"] = _proxmox_sshkeys_value(ssh_key)
    if ip_mode == "dhcp":
        payload["ipconfig0"] = "ip=dhcp"
    else:
        payload["ipconfig0"] = _static_ipconfig_from_network(network)
    return payload


def _requested_disk_gb(plan: VmCreatePlan) -> int | None:
    try:
        requested = int(dict(plan.hardware).get("disk_gb") or 0)
    except (TypeError, ValueError):
        return None
    return requested if requested > 0 else None


def _parse_disk_size_gb(value: object) -> float | None:
    text = str(value or "").strip()
    match = _DISK_SIZE_PATTERN.search(text)
    if match is None:
        return None
    try:
        amount = float(match.group(1))
    except (TypeError, ValueError):
        return None
    unit = match.group(2).upper() or "G"
    unit_map = {"K": 1 / (1024 * 1024), "M": 1 / 1024, "G": 1, "T": 1024, "P": 1024 * 1024}
    return round(amount * unit_map.get(unit, 1), 2)


def _disk_config_params(value: str) -> dict[str, str]:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    params: dict[str, str] = {}
    for part in parts[1:]:
        key, separator, param_value = part.partition("=")
        params[key.strip()] = param_value.strip() if separator else "true"
    return params


def _disk_entry_from_config(device: str, value: object) -> dict[str, Any] | None:
    match = _DISK_CONFIG_KEY_PATTERN.fullmatch(str(device or ""))
    if match is None or not isinstance(value, str):
        return None
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if not parts:
        return None
    params = _disk_config_params(value)
    if str(params.get("media") or "").strip().lower() == "cdrom":
        return None
    volume_id = parts[0].strip()
    if not volume_id or volume_id.lower() == "none":
        return None
    return {
        "device": str(device),
        "bus": match.group(1),
        "index": int(match.group(2)),
        "size_gb": _parse_disk_size_gb(value),
        "volume_id": volume_id,
        "raw_config": value,
    }


def _extract_boot_disk_devices(config: dict[str, Any]) -> tuple[str, ...]:
    devices: list[str] = []

    def add_device(value: object) -> None:
        device = str(value or "").strip()
        if _DISK_CONFIG_KEY_PATTERN.fullmatch(device) and device not in devices:
            devices.append(device)

    add_device(config.get("bootdisk"))
    boot_config = str(config.get("boot") or "")
    for part in boot_config.split(","):
        key, separator, value = part.partition("=")
        if key.strip() != "order" or not separator:
            continue
        for device in value.split(";"):
            add_device(device)
    return tuple(devices)


def _disk_sort_key(entry: dict[str, Any]) -> tuple[int, int, str]:
    return (
        _DISK_BUS_ORDER.get(str(entry.get("bus") or ""), 99),
        int(entry.get("index") or 0),
        str(entry.get("device") or ""),
    )


def _select_cloned_boot_disk(config: dict[str, Any]) -> dict[str, Any] | None:
    entries = [
        entry
        for key, value in config.items()
        if (entry := _disk_entry_from_config(str(key), value)) is not None
    ]
    by_device = {str(entry["device"]): entry for entry in entries}
    if "scsi0" in by_device:
        return {**by_device["scsi0"], "selection": "scsi0"}
    for device in _extract_boot_disk_devices(config):
        if device in by_device:
            return {**by_device[device], "selection": "boot_order"}
    if entries:
        first = sorted(entries, key=_disk_sort_key)[0]
        return {**first, "selection": "first_disk"}
    return None


def _resize_decision_from_config(plan: VmCreatePlan, config: dict[str, Any]) -> dict[str, Any]:
    requested = _requested_disk_gb(plan)
    result: dict[str, Any] = {
        "requested_disk_gb": requested,
        "action": "skipped",
        "reason": "disk_gb_not_requested",
        "selected_disk": None,
        "success": True,
    }
    if requested is None:
        return result

    selected = _select_cloned_boot_disk(config)
    if selected is None:
        return {
            **result,
            "action": "skipped",
            "reason": "boot_disk_not_found",
            "success": False,
        }

    current_size = selected.get("size_gb")
    disk_evidence = {
        "device": selected.get("device"),
        "selection": selected.get("selection"),
        "size_gb": current_size,
        "volume_id": selected.get("volume_id"),
    }
    result = {
        **result,
        "selected_disk": disk_evidence,
        "current_disk_gb": current_size,
    }
    if current_size is None or float(current_size) <= 0:
        return {
            **result,
            "action": "skipped",
            "reason": "current_disk_size_unknown",
            "success": False,
        }
    if float(requested) > float(current_size):
        return {
            **result,
            "action": "resize_required",
            "reason": "requested_larger_than_current",
            "disk": str(selected["device"]),
            "size": f"{requested}G",
            "success": None,
        }
    return {
        **result,
        "action": "not_needed",
        "reason": "requested_not_larger_than_current",
        "success": True,
    }


def _fingerprint_from_config(config: dict[str, Any]) -> dict[str, Any]:
    mac_addresses: set[str] = set()
    disk_volume_ids: set[str] = set()
    for key, raw_value in config.items():
        value = str(raw_value or "").strip()
        if str(key).startswith("net"):
            for match in _MAC_PATTERN.finditer(value):
                mac_addresses.add(match.group(1).lower())
        if _DISK_CONFIG_KEY_PATTERN.match(str(key)):
            volume = value.split(",", 1)[0].strip()
            if volume and volume.lower() != "none" and ":" in volume:
                disk_volume_ids.add(volume.lower())

    source = {
        "smbios1": str(config.get("smbios1") or "").strip(),
        "vmgenid": str(config.get("vmgenid") or "").strip(),
        "mac_addresses": sorted(mac_addresses),
        "disk_volume_ids": sorted(disk_volume_ids),
    }
    normalized = json.dumps(source, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return {
        **source,
        "hash": "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
    }


def vm_config_fingerprint(config: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the stable, secret-free VM identity fingerprint used by recovery."""

    return _fingerprint_from_config(dict(config or {}))


def _extract_guest_agent_ipv4_addresses(payload: Any) -> tuple[str, ...]:
    if isinstance(payload, dict):
        interfaces = payload.get("result") or payload.get("interfaces") or []
    elif isinstance(payload, list):
        interfaces = payload
    else:
        interfaces = []

    addresses: list[str] = []
    seen: set[str] = set()
    for interface in interfaces:
        if not isinstance(interface, dict):
            continue
        entries = interface.get("ip-addresses") or interface.get("ip_addresses") or []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            raw_ip = str(entry.get("ip-address") or entry.get("ip_address") or "").split("/", 1)[0].strip()
            if not raw_ip:
                continue
            try:
                parsed = ip_address(raw_ip)
            except ValueError:
                continue
            if parsed.version != 4 or parsed.is_loopback or parsed.is_link_local:
                continue
            normalized = str(parsed)
            if normalized not in seen:
                seen.add(normalized)
                addresses.append(normalized)
    return tuple(addresses)


def _guest_agent_attempts(plan: VmCreatePlan) -> int:
    summary = dict(getattr(plan, "smoke_timeout_summary", {}) or {})
    minutes = summary.get("ip_discovery_minutes") or summary.get("guest_agent_minutes") or 5
    try:
        seconds = max(float(minutes) * 60.0, _GUEST_AGENT_POLL_INTERVAL_SECONDS)
    except (TypeError, ValueError):
        seconds = 300.0
    return max(1, int(seconds // _GUEST_AGENT_POLL_INTERVAL_SECONDS))


def _observe_guest_agent_network(
    client: ProxmoxMutationClient,
    *,
    plan: VmCreatePlan,
    sleep: Any = time.sleep,
    heartbeat: Callable[[], None] | None = None,
) -> dict[str, Any]:
    last_error = ""
    last_details: dict[str, Any] = {}
    for attempt in range(1, _guest_agent_attempts(plan) + 1):
        try:
            payload = client.get_guest_network_interfaces(node=plan.target_node_id, vmid=int(plan.vmid))
            ip_addresses = _extract_guest_agent_ipv4_addresses(payload)
            if ip_addresses:
                return {
                    "available": True,
                    "ip_addresses": list(ip_addresses),
                    "primary_ip": ip_addresses[0],
                    "attempts": attempt,
                }
        except ProxmoxMutationError as exc:
            last_error = "proxmox_guest_agent_observation_unavailable"
            last_details = _error_details(exc)
        _heartbeat(heartbeat)
        if attempt < _guest_agent_attempts(plan):
            sleep(_GUEST_AGENT_POLL_INTERVAL_SECONDS)
    return {
        "available": False,
        "ip_addresses": [],
        "primary_ip": "",
        "attempts": _guest_agent_attempts(plan),
        "error": last_error or "guest_agent_ipv4_not_observed",
        "details": last_details,
    }


def _check_cloud_init_status(
    client: ProxmoxMutationClient,
    *,
    plan: VmCreatePlan,
    attempts: int = 3,
    sleep: Any = time.sleep,
    heartbeat: Callable[[], None] | None = None,
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    total_attempts = max(int(attempts), 1)
    for attempt in range(1, total_attempts + 1):
        try:
            pid = client.exec_guest_command(
                node=plan.target_node_id,
                vmid=int(plan.vmid),
                command=("cloud-init", "status", "--wait"),
            )
            status = client.wait_guest_exec(node=plan.target_node_id, vmid=int(plan.vmid), pid=pid, heartbeat=heartbeat)
        except ProxmoxMutationError as exc:
            safe_details = _error_details(exc)
            errors.append(
                {
                    "attempt": attempt,
                    "error": "proxmox_guest_command_observation_unavailable",
                    "details": safe_details,
                }
            )
            if attempt < total_attempts and _is_retryable_cloud_init_probe_error(exc):
                _heartbeat(heartbeat)
                sleep(1)
                continue
            return {
                "checked": True,
                "success": False,
                "status": "unavailable",
                "attempts": attempt,
                "error": "proxmox_guest_command_observation_unavailable",
                "errors": errors,
                "details": safe_details,
            }
        _heartbeat(heartbeat)
        break

    try:
        exitcode = int(status.get("exitcode"))
    except (TypeError, ValueError, OverflowError):
        exitcode = None
    success = exitcode == 0
    return {
        "checked": True,
        "success": success,
        "status": "done" if success else "failed",
        "attempts": attempt,
        "exitcode": exitcode,
        "previous_errors": errors,
    }


def _is_retryable_cloud_init_probe_error(exc: ProxmoxMutationError) -> bool:
    details = getattr(exc, "details", {}) or {}
    haystack = " ".join(
        [
            str(exc),
            str(details.get("reason") or ""),
            str(details.get("response_text") or ""),
            str(details.get("response_json") or ""),
        ]
    ).lower()
    retry_markers = (
        "invalid parameter 'pid'",
        "broken pipe",
        "guest agent is not running",
        "qemu guest agent is not running",
    )
    return any(marker in haystack for marker in retry_markers)


def _boot_verification_summary(
    *,
    running: bool,
    guest_agent: dict[str, Any],
    cloud_init: dict[str, Any],
) -> dict[str, Any]:
    ip_addresses = list(guest_agent.get("ip_addresses") or [])
    checks = {
        "running": bool(running),
        "guest_agent_available": guest_agent.get("available") is True,
        "ip_observed": bool(ip_addresses),
        "cloud_init_completed": cloud_init.get("success") is True,
    }
    return {
        "success": all(checks.values()),
        "checks": checks,
        "primary_ip": ip_addresses[0] if ip_addresses else "",
    }


def _boot_verification_message(verification: dict[str, Any]) -> str:
    checks = dict(verification.get("checks") or {})
    if verification.get("success") is True:
        return "VM is running; guest-agent IP and cloud-init completion were verified"
    missing = []
    if not checks.get("running"):
        missing.append("running state")
    if not checks.get("guest_agent_available"):
        missing.append("guest-agent")
    if not checks.get("ip_observed"):
        missing.append("guest IP")
    if not checks.get("cloud_init_completed"):
        missing.append("cloud-init completion")
    return "Boot verification needs reconciliation: " + ", ".join(missing or ["unknown"])


def build_proxmox_create_preview(plan: VmCreatePlan, *, run_dir: str | Path) -> dict[str, Any]:
    """Build a non-mutating native Proxmox create preview artifact."""
    raw_config = config_payload_from_plan(plan)
    boot_and_verify = _boot_and_verify_requested(plan)
    payload = {
        "job_id": plan.job_id,
        "manifest_id": plan.manifest_id,
        "vmid": plan.vmid,
        "vm_name": plan.vm_name,
        "target_node_id": plan.target_node_id,
        "power_policy": _power_policy(plan),
        "clone": clone_payload_from_plan(plan),
        "config": _sanitize_public_key_material(raw_config),
        "post_check": {
            "status_endpoint": f"/nodes/{plan.target_node_id}/qemu/{int(plan.vmid)}/status/current",
            "config_endpoint": f"/nodes/{plan.target_node_id}/qemu/{int(plan.vmid)}/config",
            "required_status": "running" if boot_and_verify else "stopped",
            "powered_on_success_allowed": boot_and_verify,
            "guest_agent_network_endpoint": f"/nodes/{plan.target_node_id}/qemu/{int(plan.vmid)}/agent/network-get-interfaces" if boot_and_verify else None,
            "cloud_init_check": "cloud-init status --wait" if boot_and_verify else None,
        },
        "proxmox_mutation_enabled": False,
        "side_effects": [],
    }
    artifact = write_json_artifact(
        run_dir=run_dir,
        job_id=plan.job_id,
        artifact_type="proxmox_create_preview",
        filename="proxmox_create_preview.json",
        payload=payload,
    )
    return {**payload, "artifacts": [artifact.to_dict()]}


def _observed_after_payload(
    *,
    plan: VmCreatePlan,
    status: dict[str, Any],
    config: dict[str, Any],
    exists: bool,
    post_check_status: str,
    message: str,
    powered_on_success_allowed: bool = False,
    guest_agent: dict[str, Any] | None = None,
    cloud_init: dict[str, Any] | None = None,
    boot_verification: dict[str, Any] | None = None,
    start_task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    compact_status = compact_proxmox_vm_status(
        status,
        node=plan.target_node_id,
        vmid=int(plan.vmid),
    )
    observed_status = str(compact_status.get("status") or "")
    guest_agent_payload = dict(guest_agent or {})
    ip_addresses = list(guest_agent_payload.get("ip_addresses") or [])
    compact_start_task = compact_proxmox_task(
        start_task,
        node=plan.target_node_id,
        upid=str(dict(start_task or {}).get("upid") or ""),
    )
    if start_task and not compact_start_task.get("status"):
        compact_start_task["status"] = "unknown"
    return {
        "observed_at": _now_utc(),
        "job_id": plan.job_id,
        "manifest_id": plan.manifest_id,
        "vmid": int(plan.vmid),
        "vm_name": plan.vm_name,
        "target_node_id": plan.target_node_id,
        "exists": bool(exists),
        "status": observed_status,
        "post_check_status": post_check_status,
        "message": message,
        "power_policy": _power_policy(plan),
        "powered_on_success_allowed": bool(powered_on_success_allowed),
        "guest_agent": guest_agent_payload,
        "ip_addresses": ip_addresses,
        "primary_ip": ip_addresses[0] if ip_addresses else "",
        "cloud_init": dict(cloud_init or {}),
        "boot_verification": dict(boot_verification or {}),
        "start_task": compact_start_task if start_task else {},
        "fingerprint": _fingerprint_from_config(config),
        "status_current": {**compact_status, "name": plan.vm_name},
    }


def _error_details(exc: ProxmoxMutationError) -> dict[str, Any]:
    """Return bounded allowlisted error evidence without raw upstream payloads."""

    raw = getattr(exc, "details", {}) or {}
    return compact_proxmox_error_details(raw if isinstance(raw, Mapping) else {})


def _is_http_4xx_rejection(exc: ProxmoxMutationError) -> bool:
    clear_rejection_statuses = {400, 401, 403, 404, 405, 409, 422}
    details = getattr(exc, "details", {}) or {}
    try:
        status_code = int(details.get("status_code") or 0)
    except (TypeError, ValueError):
        return False
    return status_code in clear_rejection_statuses


def run_proxmox_create(
    plan: VmCreatePlan,
    *,
    run_dir: str | Path,
    client: ProxmoxMutationClient,
    checkpoint: VmCreateCheckpoint | None = None,
    heartbeat: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Clone, configure, and verify a VM via the native Proxmox API."""
    side_effects: list[str] = []
    clone = clone_payload_from_plan(plan)
    config_payload = config_payload_from_plan(plan)
    task_result: dict[str, Any] = {}

    _checkpoint(
        checkpoint,
        "clone_pending",
        {
            "template_node": clone["template_node"],
            "template_vmid": int(clone["template_vmid"]),
            "target_node_id": plan.target_node_id,
            "vmid": int(plan.vmid),
        },
    )
    try:
        raw_upid = str(
            client.clone_vm(
                template_node=clone["template_node"],
                template_vmid=int(clone["template_vmid"]),
                newid=int(clone["newid"]),
                name=str(clone["name"]),
                target=str(clone["target"]),
                storage=str(clone["storage"]),
            )
            or ""
        ).strip()
        upid = compact_proxmox_task(
            {},
            node=str(clone["template_node"]),
            upid=raw_upid,
        )["upid"]
    except ProxmoxMutationError as exc:
        details = _error_details(exc)
        if _is_http_4xx_rejection(exc):
            status = "failed"
            side_effects.append("proxmox_clone_rejected")
            message = "Proxmox clone request was rejected by the API"
            phase = "clone_rejected"
        else:
            status = "needs_reconciliation"
            side_effects.append("proxmox_clone_state_unknown")
            message = "Proxmox clone request state is unknown and requires reconciliation"
            phase = "clone_ambiguous"
        _checkpoint(
            checkpoint,
            phase,
            {
                "status": status,
                "error_type": type(exc).__name__,
                "details": details,
            },
        )
        return {
            "job_id": plan.job_id,
            "manifest_id": plan.manifest_id,
            "vmid": plan.vmid,
            "target_node_id": plan.target_node_id,
            "success": False,
            "status": status,
            "message": message,
            "clone": clone,
            "config": _sanitize_public_key_material(config_payload),
            "details": details,
            "task": {"status": "unknown"},
            "artifacts": [],
            "side_effects": side_effects,
        }
    side_effects.append("proxmox_clone_invoked")
    if not upid:
        task_result = compact_proxmox_task(
            {"status": "unknown"},
            node=str(clone["template_node"]),
        )
        _checkpoint(
            checkpoint,
            "clone_locator_invalid",
            {
                "status": "needs_reconciliation",
                "task_reference_present": False,
            },
        )
        return {
            "job_id": plan.job_id,
            "manifest_id": plan.manifest_id,
            "vmid": plan.vmid,
            "target_node_id": plan.target_node_id,
            "success": False,
            "status": "needs_reconciliation",
            "message": "Proxmox clone response did not provide a valid task locator; reconciliation is required",
            "clone": clone,
            "config": _sanitize_public_key_material(config_payload),
            "task": task_result,
            "artifacts": [],
            "side_effects": side_effects,
        }
    task_result = {"node": clone["template_node"], "upid": upid, "status": "unknown"}
    _checkpoint(
        checkpoint,
        "clone_dispatched",
        {
            "clone_task_node_id": clone["template_node"],
            "vmid": int(plan.vmid),
            "clone_upid": upid,
        },
    )
    try:
        task_result = _wait_for_task(
            client,
            node=clone["template_node"],
            upid=upid,
            heartbeat=heartbeat,
        )
        side_effects.append("proxmox_task_polled")
        _checkpoint(
            checkpoint,
            "clone_task_observed",
            {
                "clone_upid": upid,
                "task_status": str(task_result.get("status") or ""),
                "task_exitstatus": str(task_result.get("exitstatus") or ""),
            },
        )
    except ProxmoxMutationError as exc:
        details = _error_details(exc)
        side_effects.append("proxmox_task_poll_state_unknown")
        _checkpoint(
            checkpoint,
            "clone_task_ambiguous",
            {
                "clone_upid": upid,
                "error_type": type(exc).__name__,
                "details": details,
            },
        )
        return {
            "job_id": plan.job_id,
            "manifest_id": plan.manifest_id,
            "vmid": plan.vmid,
            "target_node_id": plan.target_node_id,
            "success": False,
            "status": "needs_reconciliation",
            "message": "Proxmox clone task polling is unknown after UPID acquisition and requires reconciliation",
            "clone": clone,
            "config": _sanitize_public_key_material(config_payload),
            "details": details,
            "task": {**task_result, "status": "unknown", "error_type": type(exc).__name__},
            "artifacts": [],
            "side_effects": side_effects,
        }

    if str(task_result.get("exitstatus") or "").upper() != "OK":
        return {
            "job_id": plan.job_id,
            "manifest_id": plan.manifest_id,
            "vmid": plan.vmid,
            "target_node_id": plan.target_node_id,
            "success": False,
            "status": "failed",
            "message": "Proxmox clone task failed.",
            "clone": clone,
            "config": _sanitize_public_key_material(config_payload),
            "task": task_result,
            "artifacts": [],
            "side_effects": side_effects,
        }

    try:
        cloned_config = client.get_vm_config(node=plan.target_node_id, vmid=int(plan.vmid))
    except ProxmoxMutationError as exc:
        resize_result = {
            "requested_disk_gb": _requested_disk_gb(plan),
            "action": "skipped",
            "reason": "cloned_config_unavailable",
            "selected_disk": None,
            "success": False,
            "error": "proxmox_cloned_config_observation_unavailable",
        }
        side_effects.append("proxmox_disk_resize_skipped_unknown")
        return {
            "job_id": plan.job_id,
            "manifest_id": plan.manifest_id,
            "vmid": plan.vmid,
            "target_node_id": plan.target_node_id,
            "success": False,
            "status": "needs_reconciliation",
            "message": "Unable to inspect the cloned VM disk before resize",
            "clone": clone,
            "config": _sanitize_public_key_material(config_payload),
            "resize": resize_result,
            "details": _error_details(exc),
            "task": task_result,
            "artifacts": [],
            "side_effects": side_effects,
        }

    resize_result = _resize_decision_from_config(plan, cloned_config)
    if resize_result.get("action") == "resize_required":
        _checkpoint(
            checkpoint,
            "resize_pending",
            {
                "disk": str(resize_result["disk"]),
                "requested_disk_gb": int(_requested_disk_gb(plan) or 0),
                "current_disk_gb": resize_result.get("current_disk_gb"),
            },
        )
        side_effects.append("proxmox_disk_resize_invoked")
        try:
            resize_response = client.resize_vm_disk(
                node=plan.target_node_id,
                vmid=int(plan.vmid),
                disk=str(resize_result["disk"]),
                size=int(_requested_disk_gb(plan) or 0),
            )
            resize_result = {
                **resize_result,
                "action": "resized",
                "success": True,
                "response_received": resize_response is not None,
            }
            side_effects.append("proxmox_disk_resize_succeeded")
            _checkpoint(
                checkpoint,
                "resize_completed",
                {
                    "disk": str(resize_result["disk"]),
                    "requested_disk_gb": int(_requested_disk_gb(plan) or 0),
                },
            )
        except ProxmoxMutationError as exc:
            resize_result = {
                **resize_result,
                "action": "failed",
                "success": False,
                "error": "proxmox_disk_resize_state_unknown",
                "details": _error_details(exc),
            }
            side_effects.append("proxmox_disk_resize_failed")
            _checkpoint(
                checkpoint,
                "resize_ambiguous",
                {
                    "disk": str(resize_result.get("disk") or ""),
                    "requested_disk_gb": int(_requested_disk_gb(plan) or 0),
                    "error_type": type(exc).__name__,
                    "details": _error_details(exc),
                },
            )
            return {
                "job_id": plan.job_id,
                "manifest_id": plan.manifest_id,
                "vmid": plan.vmid,
                "target_node_id": plan.target_node_id,
                "success": False,
                "status": "needs_reconciliation",
                "message": "Proxmox disk resize state is unknown and requires reconciliation",
                "clone": clone,
                "config": _sanitize_public_key_material(config_payload),
                "resize": resize_result,
                "task": task_result,
                "artifacts": [],
                "side_effects": side_effects,
            }
    elif resize_result.get("success") is False:
        side_effects.append("proxmox_disk_resize_skipped_unknown")
        return {
            "job_id": plan.job_id,
            "manifest_id": plan.manifest_id,
            "vmid": plan.vmid,
            "target_node_id": plan.target_node_id,
            "success": False,
            "status": "needs_reconciliation",
            "message": f"Unable to confirm cloned boot disk size: {resize_result.get('reason')}",
            "clone": clone,
            "config": _sanitize_public_key_material(config_payload),
            "resize": resize_result,
            "task": task_result,
            "artifacts": [],
            "side_effects": side_effects,
        }
    elif resize_result.get("action") == "not_needed":
        side_effects.append("proxmox_disk_resize_not_needed")

    _checkpoint(
        checkpoint,
        "config_pending",
        {
            "config_keys": sorted(str(key) for key in config_payload),
            "target_node_id": plan.target_node_id,
            "vmid": int(plan.vmid),
        },
    )
    try:
        client.set_vm_config(node=plan.target_node_id, vmid=int(plan.vmid), config=config_payload)
        side_effects.append("proxmox_config_updated")
        _checkpoint(
            checkpoint,
            "config_completed",
            {
                "config_keys": sorted(str(key) for key in config_payload),
                "target_node_id": plan.target_node_id,
                "vmid": int(plan.vmid),
            },
        )
    except ProxmoxMutationError as exc:
        _checkpoint(
            checkpoint,
            "config_ambiguous",
            {
                "error_type": type(exc).__name__,
                "details": _error_details(exc),
            },
        )
        return {
            "job_id": plan.job_id,
            "manifest_id": plan.manifest_id,
            "vmid": plan.vmid,
            "target_node_id": plan.target_node_id,
            "success": False,
            "status": "needs_reconciliation",
            "message": "Proxmox VM configuration state is unknown and requires reconciliation",
            "clone": clone,
            "config": _sanitize_public_key_material(config_payload),
            "resize": resize_result,
            "details": _error_details(exc),
            "task": task_result,
            "artifacts": [],
            "side_effects": side_effects,
        }

    try:
        observed_status = compact_proxmox_vm_status(
            client.get_vm_status(node=plan.target_node_id, vmid=int(plan.vmid)),
            node=plan.target_node_id,
            vmid=int(plan.vmid),
        )
        observed_config = client.get_vm_config(node=plan.target_node_id, vmid=int(plan.vmid))
        side_effects.append("proxmox_post_check_observed")
        exists = True
        _checkpoint(
            checkpoint,
            "post_check_observed",
            {
                "exists": True,
                "status": str(observed_status.get("status") or ""),
                "fingerprint": vm_config_fingerprint(observed_config),
            },
        )
    except ProxmoxMutationError as exc:
        observed_status = {}
        observed_config = {}
        exists = False
        message = "VM post-check observation is unavailable and requires reconciliation"
        observed_after = _observed_after_payload(
            plan=plan,
            status=observed_status,
            config=observed_config,
            exists=exists,
            post_check_status="needs_reconciliation",
            message=message,
        )
        _checkpoint(
            checkpoint,
            "post_check_ambiguous",
            {
                "exists": False,
                "status": "unknown",
                "error_type": type(exc).__name__,
                "details": _error_details(exc),
            },
        )
        artifact = write_json_artifact(
            run_dir=run_dir,
            job_id=plan.job_id,
            artifact_type="observed_after",
            filename="observed_after.json",
            payload=observed_after,
        )
        _checkpoint(
            checkpoint,
            "observed_after_artifact_recorded",
            {
                "result_success": False,
                "result_status": "needs_reconciliation",
                "observed_after": observed_after,
                "observed_after_artifact": artifact.to_dict(),
            },
        )
        return {
            "job_id": plan.job_id,
            "manifest_id": plan.manifest_id,
            "vmid": plan.vmid,
            "target_node_id": plan.target_node_id,
            "success": False,
            "status": "needs_reconciliation",
            "message": message,
            "clone": clone,
            "config": _sanitize_public_key_material(config_payload),
            "resize": resize_result,
            "task": task_result,
            "observed_after": observed_after,
            "observed_after_artifact": artifact.to_dict(),
            "artifacts": [artifact.to_dict()],
            "side_effects": side_effects,
        }

    observed_power = str(observed_status.get("status") or "")
    start_task_result: dict[str, Any] = {}
    guest_agent: dict[str, Any] = {}
    cloud_init: dict[str, Any] = {}
    boot_verification: dict[str, Any] = {}
    boot_and_verify = _boot_and_verify_requested(plan)

    if boot_and_verify:
        if observed_power not in {"running", "stopped"}:
            message = "VM power state could not be verified after create; reconciliation is required"
            observed_after = _observed_after_payload(
                plan=plan,
                status=observed_status,
                config=observed_config,
                exists=exists,
                post_check_status="needs_reconciliation",
                message=message,
                powered_on_success_allowed=True,
            )
            artifact = write_json_artifact(
                run_dir=run_dir,
                job_id=plan.job_id,
                artifact_type="observed_after",
                filename="observed_after.json",
                payload=observed_after,
            )
            _checkpoint(
                checkpoint,
                "observed_after_artifact_recorded",
                {
                    "result_success": False,
                    "result_status": "needs_reconciliation",
                    "observed_after": observed_after,
                    "observed_after_artifact": artifact.to_dict(),
                    "clone_upid": str(task_result.get("upid") or ""),
                },
            )
            return {
                "job_id": plan.job_id,
                "manifest_id": plan.manifest_id,
                "vmid": plan.vmid,
                "target_node_id": plan.target_node_id,
                "success": False,
                "status": "needs_reconciliation",
                "message": message,
                "clone": clone,
                "config": _sanitize_public_key_material(config_payload),
                "resize": resize_result,
                "task": task_result,
                "observed_after": observed_after,
                "observed_after_artifact": artifact.to_dict(),
                "artifacts": [artifact.to_dict()],
                "side_effects": side_effects,
            }
        if observed_power == "stopped":
            _checkpoint(
                checkpoint,
                "start_pending",
                {
                    "target_node_id": plan.target_node_id,
                    "vmid": int(plan.vmid),
                    "observed_power": observed_power,
                },
            )
            start_upid = ""
            try:
                raw_start_upid = str(
                    client.start_vm(node=plan.target_node_id, vmid=int(plan.vmid)) or ""
                ).strip()
                start_upid = compact_proxmox_task(
                    {},
                    node=plan.target_node_id,
                    upid=raw_start_upid,
                )["upid"]
                side_effects.append("proxmox_start_invoked")
                if not start_upid:
                    message = "Proxmox VM start response did not provide a valid task locator; reconciliation is required"
                    start_task_result = compact_proxmox_task(
                        {"status": "unknown"},
                        node=plan.target_node_id,
                    )
                    observed_after = _observed_after_payload(
                        plan=plan,
                        status=observed_status,
                        config=observed_config,
                        exists=exists,
                        post_check_status="needs_reconciliation",
                        message=message,
                        powered_on_success_allowed=True,
                        start_task=start_task_result,
                    )
                    _checkpoint(
                        checkpoint,
                        "start_locator_invalid",
                        {
                            "task_reference_present": False,
                            "status": "needs_reconciliation",
                        },
                    )
                    artifact = write_json_artifact(
                        run_dir=run_dir,
                        job_id=plan.job_id,
                        artifact_type="observed_after",
                        filename="observed_after.json",
                        payload=observed_after,
                    )
                    _checkpoint(
                        checkpoint,
                        "observed_after_artifact_recorded",
                        {
                            "result_success": False,
                            "result_status": "needs_reconciliation",
                            "observed_after": observed_after,
                            "observed_after_artifact": artifact.to_dict(),
                        },
                    )
                    return {
                        "job_id": plan.job_id,
                        "manifest_id": plan.manifest_id,
                        "vmid": plan.vmid,
                        "target_node_id": plan.target_node_id,
                        "success": False,
                        "status": "needs_reconciliation",
                        "message": message,
                        "clone": clone,
                        "config": _sanitize_public_key_material(config_payload),
                        "resize": resize_result,
                        "task": task_result,
                        "start_task": start_task_result,
                        "observed_after": observed_after,
                        "observed_after_artifact": artifact.to_dict(),
                        "artifacts": [artifact.to_dict()],
                        "side_effects": side_effects,
                    }
                _checkpoint(
                    checkpoint,
                    "start_dispatched",
                    {
                        "target_node_id": plan.target_node_id,
                        "vmid": int(plan.vmid),
                        "start_upid": start_upid,
                    },
                )
                start_task_result = _wait_for_task(
                    client,
                    node=plan.target_node_id,
                    upid=start_upid,
                    heartbeat=heartbeat,
                )
                side_effects.append("proxmox_start_task_polled")
                _checkpoint(
                    checkpoint,
                    "start_task_observed",
                    {
                        "start_upid": start_upid,
                        "task_status": str(start_task_result.get("status") or ""),
                        "task_exitstatus": str(start_task_result.get("exitstatus") or ""),
                    },
                )
            except ProxmoxMutationError as exc:
                message = "Proxmox VM start state is unknown and requires reconciliation"
                start_error = {
                    "status": "unknown",
                    "error_type": type(exc).__name__,
                    "details": _error_details(exc),
                }
                observed_after = _observed_after_payload(
                    plan=plan,
                    status=observed_status,
                    config=observed_config,
                    exists=exists,
                    post_check_status="needs_reconciliation",
                    message=message,
                    powered_on_success_allowed=True,
                    start_task=start_task_result or start_error,
                )
                _checkpoint(
                    checkpoint,
                    "start_ambiguous",
                    {
                        "start_upid": start_upid,
                        "error_type": type(exc).__name__,
                        "details": _error_details(exc),
                    },
                )
                artifact = write_json_artifact(
                    run_dir=run_dir,
                    job_id=plan.job_id,
                    artifact_type="observed_after",
                    filename="observed_after.json",
                    payload=observed_after,
                )
                _checkpoint(
                    checkpoint,
                    "observed_after_artifact_recorded",
                    {
                        "result_success": False,
                        "result_status": "needs_reconciliation",
                        "observed_after": observed_after,
                        "observed_after_artifact": artifact.to_dict(),
                    },
                )
                return {
                    "job_id": plan.job_id,
                    "manifest_id": plan.manifest_id,
                    "vmid": plan.vmid,
                    "target_node_id": plan.target_node_id,
                    "success": False,
                    "status": "needs_reconciliation",
                    "message": message,
                    "clone": clone,
                    "config": _sanitize_public_key_material(config_payload),
                    "resize": resize_result,
                    "task": task_result,
                    "start_task": start_task_result,
                    "observed_after": observed_after,
                    "observed_after_artifact": artifact.to_dict(),
                    "artifacts": [artifact.to_dict()],
                    "side_effects": side_effects,
                }
            if str(start_task_result.get("exitstatus") or "").upper() != "OK":
                message = "Proxmox start task failed."
                observed_after = _observed_after_payload(
                    plan=plan,
                    status=observed_status,
                    config=observed_config,
                    exists=exists,
                    post_check_status="needs_reconciliation",
                    message=message,
                    powered_on_success_allowed=True,
                    start_task=start_task_result,
                )
                artifact = write_json_artifact(
                    run_dir=run_dir,
                    job_id=plan.job_id,
                    artifact_type="observed_after",
                    filename="observed_after.json",
                    payload=observed_after,
                )
                _checkpoint(
                    checkpoint,
                    "observed_after_artifact_recorded",
                    {
                        "result_success": False,
                        "result_status": "needs_reconciliation",
                        "observed_after": observed_after,
                        "observed_after_artifact": artifact.to_dict(),
                    },
                )
                return {
                    "job_id": plan.job_id,
                    "manifest_id": plan.manifest_id,
                    "vmid": plan.vmid,
                    "target_node_id": plan.target_node_id,
                    "success": False,
                    "status": "needs_reconciliation",
                    "message": message,
                    "clone": clone,
                    "config": _sanitize_public_key_material(config_payload),
                    "resize": resize_result,
                    "task": task_result,
                    "start_task": start_task_result,
                    "observed_after": observed_after,
                    "observed_after_artifact": artifact.to_dict(),
                    "artifacts": [artifact.to_dict()],
                    "side_effects": side_effects,
                }
            try:
                observed_status = compact_proxmox_vm_status(
                    client.get_vm_status(node=plan.target_node_id, vmid=int(plan.vmid)),
                    node=plan.target_node_id,
                    vmid=int(plan.vmid),
                )
                observed_config = client.get_vm_config(node=plan.target_node_id, vmid=int(plan.vmid))
            except ProxmoxMutationError as exc:
                message = "VM boot post-check observation is unavailable and requires reconciliation"
                observed_after = _observed_after_payload(
                    plan=plan,
                    status=observed_status,
                    config=observed_config,
                    exists=exists,
                    post_check_status="needs_reconciliation",
                    message=message,
                    powered_on_success_allowed=True,
                    start_task=start_task_result,
                )
                _checkpoint(
                    checkpoint,
                    "boot_post_check_ambiguous",
                    {
                        "start_upid": str(start_task_result.get("upid") or ""),
                        "error_type": type(exc).__name__,
                        "details": _error_details(exc),
                    },
                )
                artifact = write_json_artifact(
                    run_dir=run_dir,
                    job_id=plan.job_id,
                    artifact_type="observed_after",
                    filename="observed_after.json",
                    payload=observed_after,
                )
                _checkpoint(
                    checkpoint,
                    "observed_after_artifact_recorded",
                    {
                        "result_success": False,
                        "result_status": "needs_reconciliation",
                        "observed_after": observed_after,
                        "observed_after_artifact": artifact.to_dict(),
                    },
                )
                return {
                    "job_id": plan.job_id,
                    "manifest_id": plan.manifest_id,
                    "vmid": plan.vmid,
                    "target_node_id": plan.target_node_id,
                    "success": False,
                    "status": "needs_reconciliation",
                    "message": message,
                    "clone": clone,
                    "config": _sanitize_public_key_material(config_payload),
                    "resize": resize_result,
                    "task": task_result,
                    "start_task": start_task_result,
                    "details": _error_details(exc),
                    "observed_after": observed_after,
                    "observed_after_artifact": artifact.to_dict(),
                    "artifacts": [artifact.to_dict()],
                    "side_effects": side_effects,
                }
            observed_power = str(observed_status.get("status") or "")
            side_effects.append("proxmox_boot_post_check_observed")

        guest_agent = _observe_guest_agent_network(client, plan=plan, heartbeat=heartbeat)
        side_effects.append("proxmox_guest_agent_observed" if guest_agent.get("available") is True else "proxmox_guest_agent_unavailable")
        cloud_init = _check_cloud_init_status(client, plan=plan, heartbeat=heartbeat)
        side_effects.append("proxmox_cloud_init_status_checked" if cloud_init.get("success") is True else "proxmox_cloud_init_status_unavailable")
        boot_verification = _boot_verification_summary(
            running=observed_power == "running",
            guest_agent=guest_agent,
            cloud_init=cloud_init,
        )
        success = exists and boot_verification.get("success") is True
        result_status = "completed" if success else "needs_reconciliation"
        message = _boot_verification_message(boot_verification)
    else:
        success = exists and observed_power == "stopped"
        result_status = "completed" if success else "needs_reconciliation"
        message = (
            "VM exists on target node and is stopped"
            if success
            else "VM post-check did not verify the expected stopped state"
        )

    observed_after = _observed_after_payload(
        plan=plan,
        status=observed_status,
        config=observed_config,
        exists=exists,
        post_check_status=result_status,
        message=message,
        powered_on_success_allowed=boot_and_verify,
        guest_agent=guest_agent,
        cloud_init=cloud_init,
        boot_verification=boot_verification,
        start_task=start_task_result,
    )
    _checkpoint(
        checkpoint,
        "readiness_observed",
        {
            "result_success": success,
            "result_status": result_status,
            "observed_after": observed_after,
            "clone_upid": str(task_result.get("upid") or ""),
            "start_upid": str(start_task_result.get("upid") or ""),
        },
    )
    artifact = write_json_artifact(
        run_dir=run_dir,
        job_id=plan.job_id,
        artifact_type="observed_after",
        filename="observed_after.json",
        payload=observed_after,
    )
    _checkpoint(
        checkpoint,
        "observed_after_artifact_recorded",
        {
            "result_success": success,
            "result_status": result_status,
            "observed_after": observed_after,
            "observed_after_artifact": artifact.to_dict(),
            "clone_upid": str(task_result.get("upid") or ""),
            "start_upid": str(start_task_result.get("upid") or ""),
        },
    )
    return {
        "job_id": plan.job_id,
        "manifest_id": plan.manifest_id,
        "vmid": plan.vmid,
        "target_node_id": plan.target_node_id,
        "success": success,
        "status": result_status,
        "message": message,
        "clone": clone,
        "config": _sanitize_public_key_material(config_payload),
        "resize": resize_result,
        "task": task_result,
        "start_task": start_task_result,
        "guest_agent": guest_agent,
        "cloud_init": cloud_init,
        "boot_verification": boot_verification,
        "observed_after": observed_after,
        "observed_after_artifact": artifact.to_dict(),
        "artifacts": [artifact.to_dict()],
        "side_effects": side_effects,
    }
