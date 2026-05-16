"""Native Proxmox runner for the approval-gated Create VM path."""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.jobs.artifacts import write_json_artifact
from app.proxmox.client import ProxmoxMutationClient, ProxmoxMutationError
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
        "raw_config": selected.get("raw_config"),
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
) -> dict[str, Any]:
    last_error = ""
    last_payload: dict[str, Any] = {}
    for attempt in range(1, _guest_agent_attempts(plan) + 1):
        try:
            payload = client.get_guest_network_interfaces(node=plan.target_node_id, vmid=int(plan.vmid))
            last_payload = payload
            ip_addresses = _extract_guest_agent_ipv4_addresses(payload)
            if ip_addresses:
                return {
                    "available": True,
                    "ip_addresses": list(ip_addresses),
                    "primary_ip": ip_addresses[0],
                    "attempts": attempt,
                }
        except ProxmoxMutationError as exc:
            last_error = str(exc)
            last_payload = _sanitize_public_key_material(getattr(exc, "details", {}))
        if attempt < _guest_agent_attempts(plan):
            sleep(_GUEST_AGENT_POLL_INTERVAL_SECONDS)
    return {
        "available": False,
        "ip_addresses": [],
        "primary_ip": "",
        "attempts": _guest_agent_attempts(plan),
        "error": last_error,
        "last_payload": _sanitize_public_key_material(last_payload),
    }


def _check_cloud_init_status(
    client: ProxmoxMutationClient,
    *,
    plan: VmCreatePlan,
    attempts: int = 3,
    sleep: Any = time.sleep,
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
            status = client.wait_guest_exec(node=plan.target_node_id, vmid=int(plan.vmid), pid=pid)
        except ProxmoxMutationError as exc:
            errors.append(
                {
                    "attempt": attempt,
                    "error": str(exc),
                    "details": _sanitize_public_key_material(getattr(exc, "details", {})),
                }
            )
            if attempt < total_attempts and _is_retryable_cloud_init_probe_error(exc):
                sleep(1)
                continue
            return {
                "checked": True,
                "success": False,
                "status": "unavailable",
                "attempts": attempt,
                "error": str(exc),
                "errors": errors,
                "details": _sanitize_public_key_material(getattr(exc, "details", {})),
            }
        break

    exitcode = status.get("exitcode")
    output = str(status.get("out-data") or status.get("out_data") or "").strip()
    error_output = str(status.get("err-data") or status.get("err_data") or "").strip()
    success = exitcode == 0 or str(exitcode).strip() == "0"
    return {
        "checked": True,
        "success": success,
        "status": "done" if success else "failed",
        "pid": pid,
        "attempts": attempt,
        "exitcode": exitcode,
        "output": output[:2000],
        "error_output": error_output[:2000],
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
    observed_status = str(status.get("status") or "").lower()
    guest_agent_payload = dict(guest_agent or {})
    ip_addresses = list(guest_agent_payload.get("ip_addresses") or [])
    return {
        "observed_at": _now_utc(),
        "job_id": plan.job_id,
        "manifest_id": plan.manifest_id,
        "vmid": int(plan.vmid),
        "vm_name": status.get("name") or plan.vm_name,
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
        "start_task": dict(start_task or {}),
        "fingerprint": _fingerprint_from_config(config),
        "status_current": status,
        "config": _sanitize_public_key_material(config),
    }


def run_proxmox_create(
    plan: VmCreatePlan,
    *,
    run_dir: str | Path,
    client: ProxmoxMutationClient,
) -> dict[str, Any]:
    """Clone, configure, and verify a VM via the native Proxmox API."""
    side_effects: list[str] = []
    clone = clone_payload_from_plan(plan)
    config_payload = config_payload_from_plan(plan)
    task_result: dict[str, Any] = {}

    try:
        upid = client.clone_vm(
            template_node=clone["template_node"],
            template_vmid=int(clone["template_vmid"]),
            newid=int(clone["newid"]),
            name=str(clone["name"]),
            target=str(clone["target"]),
            storage=str(clone["storage"]),
        )
        side_effects.append("proxmox_clone_invoked")
        task_result = client.wait_for_task(node=clone["template_node"], upid=upid)
        side_effects.append("proxmox_task_polled")
    except ProxmoxMutationError as exc:
        return {
            "job_id": plan.job_id,
            "manifest_id": plan.manifest_id,
            "vmid": plan.vmid,
            "target_node_id": plan.target_node_id,
            "success": False,
            "status": "failed",
            "message": str(exc),
            "clone": clone,
            "config": _sanitize_public_key_material(config_payload),
            "task": task_result or getattr(exc, "details", {}),
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
            "message": f"Proxmox clone task failed: {task_result.get('exitstatus') or 'unknown'}",
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
            "error": str(exc),
        }
        side_effects.append("proxmox_disk_resize_skipped_unknown")
        return {
            "job_id": plan.job_id,
            "manifest_id": plan.manifest_id,
            "vmid": plan.vmid,
            "target_node_id": plan.target_node_id,
            "success": False,
            "status": "needs_reconciliation",
            "message": f"Unable to inspect cloned VM disk before resize: {exc}",
            "clone": clone,
            "config": _sanitize_public_key_material(config_payload),
            "resize": resize_result,
            "details": _sanitize_public_key_material(getattr(exc, "details", {})),
            "task": task_result,
            "artifacts": [],
            "side_effects": side_effects,
        }

    resize_result = _resize_decision_from_config(plan, cloned_config)
    if resize_result.get("action") == "resize_required":
        side_effects.append("proxmox_disk_resize_invoked")
        try:
            resize_response = client.resize_vm_disk(
                node=plan.target_node_id,
                vmid=int(plan.vmid),
                disk=str(resize_result["disk"]),
                size=int(_requested_disk_gb(plan) or 0),
            )
            resize_result = {**resize_result, "action": "resized", "success": True, "response": resize_response}
            side_effects.append("proxmox_disk_resize_succeeded")
        except ProxmoxMutationError as exc:
            resize_result = {
                **resize_result,
                "action": "failed",
                "success": False,
                "error": str(exc),
                "details": getattr(exc, "details", {}),
            }
            side_effects.append("proxmox_disk_resize_failed")
            return {
                "job_id": plan.job_id,
                "manifest_id": plan.manifest_id,
                "vmid": plan.vmid,
                "target_node_id": plan.target_node_id,
                "success": False,
                "status": "needs_reconciliation",
                "message": f"Proxmox disk resize failed: {exc}",
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

    try:
        client.set_vm_config(node=plan.target_node_id, vmid=int(plan.vmid), config=config_payload)
        side_effects.append("proxmox_config_updated")
    except ProxmoxMutationError as exc:
        return {
            "job_id": plan.job_id,
            "manifest_id": plan.manifest_id,
            "vmid": plan.vmid,
            "target_node_id": plan.target_node_id,
            "success": False,
            "status": "needs_reconciliation",
            "message": str(exc),
            "clone": clone,
            "config": _sanitize_public_key_material(config_payload),
            "resize": resize_result,
            "details": _sanitize_public_key_material(getattr(exc, "details", {})),
            "task": task_result,
            "artifacts": [],
            "side_effects": side_effects,
        }

    try:
        observed_status = client.get_vm_status(node=plan.target_node_id, vmid=int(plan.vmid))
        observed_config = client.get_vm_config(node=plan.target_node_id, vmid=int(plan.vmid))
        side_effects.append("proxmox_post_check_observed")
        exists = True
    except ProxmoxMutationError as exc:
        observed_status = {}
        observed_config = {}
        exists = False
        message = f"VM post-check failed: {exc}"
        observed_after = _observed_after_payload(
            plan=plan,
            status=observed_status,
            config=observed_config,
            exists=exists,
            post_check_status="needs_reconciliation",
            message=message,
        )
        artifact = write_json_artifact(
            run_dir=run_dir,
            job_id=plan.job_id,
            artifact_type="observed_after",
            filename="observed_after.json",
            payload=observed_after,
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

    observed_power = str(observed_status.get("status") or "").lower()
    start_task_result: dict[str, Any] = {}
    guest_agent: dict[str, Any] = {}
    cloud_init: dict[str, Any] = {}
    boot_verification: dict[str, Any] = {}
    boot_and_verify = _boot_and_verify_requested(plan)

    if boot_and_verify:
        if observed_power != "running":
            try:
                start_upid = client.start_vm(node=plan.target_node_id, vmid=int(plan.vmid))
                side_effects.append("proxmox_start_invoked")
                start_task_result = client.wait_for_task(node=plan.target_node_id, upid=start_upid)
                side_effects.append("proxmox_start_task_polled")
            except ProxmoxMutationError as exc:
                message = f"Proxmox VM start failed: {exc}"
                observed_after = _observed_after_payload(
                    plan=plan,
                    status=observed_status,
                    config=observed_config,
                    exists=exists,
                    post_check_status="needs_reconciliation",
                    message=message,
                    powered_on_success_allowed=True,
                    start_task=start_task_result or _sanitize_public_key_material(getattr(exc, "details", {})),
                )
                artifact = write_json_artifact(
                    run_dir=run_dir,
                    job_id=plan.job_id,
                    artifact_type="observed_after",
                    filename="observed_after.json",
                    payload=observed_after,
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
                message = f"Proxmox start task failed: {start_task_result.get('exitstatus') or 'unknown'}"
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
                observed_status = client.get_vm_status(node=plan.target_node_id, vmid=int(plan.vmid))
                observed_config = client.get_vm_config(node=plan.target_node_id, vmid=int(plan.vmid))
            except ProxmoxMutationError as exc:
                message = f"VM boot post-check failed: {exc}"
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
                    "details": _sanitize_public_key_material(getattr(exc, "details", {})),
                    "observed_after": observed_after,
                    "observed_after_artifact": artifact.to_dict(),
                    "artifacts": [artifact.to_dict()],
                    "side_effects": side_effects,
                }
            observed_power = str(observed_status.get("status") or "").lower()
            side_effects.append("proxmox_boot_post_check_observed")

        guest_agent = _observe_guest_agent_network(client, plan=plan)
        side_effects.append("proxmox_guest_agent_observed" if guest_agent.get("available") is True else "proxmox_guest_agent_unavailable")
        cloud_init = _check_cloud_init_status(client, plan=plan)
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
        message = "VM exists on target node and is stopped" if success else f"VM post-check expected stopped, observed {observed_power or 'unknown'}"

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
    artifact = write_json_artifact(
        run_dir=run_dir,
        job_id=plan.job_id,
        artifact_type="observed_after",
        filename="observed_after.json",
        payload=observed_after,
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
