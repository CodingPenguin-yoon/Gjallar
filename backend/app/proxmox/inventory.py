"""Read-only Proxmox inventory adapters for the Gjallar MVP."""

from __future__ import annotations

import ipaddress
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests
import urllib3
from dotenv import load_dotenv

from app.core.redaction import redact_secrets
from app.proxmox.models import (
    DiskInventory,
    GuestAgentInventory,
    InventorySnapshot,
    NetworkInventory,
    NodeInventory,
    StorageInventory,
    TemplateInventory,
    VmInventory,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_ENV_LOADED = False
_ENV_LOCK = threading.Lock()
_DEFAULT_ADAPTER_LOCK = threading.Lock()
_DEFAULT_ADAPTER_SIGNATURE: tuple[Any, ...] | None = None
_DEFAULT_ADAPTER: FakeProxmoxInventoryAdapter | LiveProxmoxInventoryAdapter | None = None
_DISK_SIZE_PATTERN = re.compile(r"(?:^|,)size=(\d+(?:\.\d+)?)([KMGTP]?)", re.IGNORECASE)
_DISK_CONFIG_KEY_PATTERN = re.compile(r"^(ide|sata|scsi|virtio)(\d+)$")
_NATURAL_SPLIT_PATTERN = re.compile(r"(\d+)")


def _load_project_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    with _ENV_LOCK:
        if _ENV_LOADED:
            return
        env_path = Path(__file__).resolve().parents[3] / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
        _ENV_LOADED = True


def _read_bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _read_float_env(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(float(raw), minimum)
    except (TypeError, ValueError):
        return default


def _read_int_env(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(int(raw), minimum)
    except (TypeError, ValueError):
        return default


def _natural_sort_key(value: object) -> list[object]:
    text = str(value or "").lower()
    return [int(part) if part.isdigit() else part for part in _NATURAL_SPLIT_PATTERN.split(text)]


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _first_unused_vmid(used_vmids: set[int], *, start: int = 100) -> int:
    candidate = max(int(start), 100)
    while candidate in used_vmids:
        candidate += 1
    return candidate


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _bytes_to_mb(value: object) -> int:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0
    if parsed <= 0:
        return 0
    return int(round(parsed / (1024 * 1024)))


def _node_cpu_usage_percent(node_row: dict[str, Any]) -> float:
    cpu = _safe_float(node_row.get("cpu"), 0.0)
    if cpu <= 0:
        return 0.0
    if cpu <= 1:
        return round(cpu * 100, 2)
    return round(min(cpu, 100.0), 2)


def _node_memory_usage_percent(*, used_mb: int, total_mb: int) -> float:
    if total_mb <= 0 or used_mb <= 0:
        return 0.0
    return round(min((used_mb / total_mb) * 100, 100.0), 2)


def _bytes_to_gb(value: object) -> int:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0
    if parsed <= 0:
        return 0
    return int(round(parsed / (1024 * 1024 * 1024)))


def _normalize_ipv4_address(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if "/" in text:
        text = text.split("/", 1)[0].strip()
    if not text or text.lower() in {"dhcp", "auto"}:
        return None
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return None
    if address.version != 4 or address.is_loopback or address.is_link_local:
        return None
    return str(address)


def _merge_ip_addresses(*groups: list[str]) -> tuple[str, ...]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for candidate in group:
            normalized = _normalize_ipv4_address(candidate)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            merged.append(normalized)
    return tuple(merged)


def _extract_configured_ipv4_addresses(config_data: dict[str, Any]) -> tuple[str, ...]:
    candidates: list[str] = []
    for key, value in config_data.items():
        if not str(key).startswith("ipconfig"):
            continue
        raw = str(value or "").strip()
        if not raw:
            continue
        for part in raw.split(","):
            name, _, part_value = part.partition("=")
            if name.strip() != "ip":
                continue
            normalized = _normalize_ipv4_address(part_value)
            if normalized:
                candidates.append(normalized)
    return _merge_ip_addresses(candidates)


def _extract_guest_agent_ipv4_addresses(payload: Any) -> tuple[str, ...]:
    interfaces: list[dict[str, Any]] = []
    if isinstance(payload, list):
        interfaces = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict):
        result = payload.get("result")
        if isinstance(result, list):
            interfaces = [item for item in result if isinstance(item, dict)]
        elif isinstance(payload.get("interfaces"), list):
            interfaces = [item for item in payload.get("interfaces", []) if isinstance(item, dict)]

    addresses: list[str] = []
    for interface in interfaces:
        ip_list = interface.get("ip-addresses") or interface.get("ip_addresses") or []
        if not isinstance(ip_list, list):
            continue
        for ip_info in ip_list:
            if not isinstance(ip_info, dict):
                continue
            ip_type = str(ip_info.get("ip-address-type") or ip_info.get("ip_address_type") or "").strip().lower()
            if ip_type and ip_type not in {"ipv4", "inet"}:
                continue
            normalized = _normalize_ipv4_address(ip_info.get("ip-address") or ip_info.get("ip_address"))
            if normalized:
                addresses.append(normalized)
    return _merge_ip_addresses(addresses)


def _extract_disk_size_gb(config_data: dict[str, Any], vm_row: dict[str, Any]) -> int:
    disks = _extract_disks(config_data, vm_row)
    if disks:
        return int(round(sum(disk.size_gb for disk in disks)))
    return _bytes_to_gb(vm_row.get("maxdisk") or vm_row.get("disk"))


def _extract_storage_id(config_data: dict[str, Any]) -> str:
    disks = _extract_disks(config_data, {})
    for disk in disks:
        if disk.storage_id != "unknown":
            return disk.storage_id
    return "unknown"


def _parse_disk_size_gb(value: object) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([KMGTP]?)(?:i?b?)?", text, re.IGNORECASE)
    if match is None:
        return 0.0
    amount = _safe_float(match.group(1), 0.0)
    unit = match.group(2).upper() or "G"
    unit_map = {"K": 1 / (1024 * 1024), "M": 1 / 1024, "G": 1, "T": 1024, "P": 1024 * 1024}
    return amount * unit_map.get(unit, 1)


def _extract_boot_disk_devices(config_data: dict[str, Any]) -> tuple[str, ...]:
    devices: list[str] = []

    def add_device(value: object) -> None:
        device = str(value or "").strip()
        if _DISK_CONFIG_KEY_PATTERN.fullmatch(device) and device not in devices:
            devices.append(device)

    add_device(config_data.get("bootdisk"))
    boot_config = str(config_data.get("boot") or "")
    for part in boot_config.split(","):
        key, separator, value = part.partition("=")
        if key.strip() != "order" or not separator:
            continue
        for device in value.split(";"):
            add_device(device)
    return tuple(devices)


def _parse_disk_config(device: str, value: object, *, boot_devices: tuple[str, ...]) -> DiskInventory | None:
    match = _DISK_CONFIG_KEY_PATTERN.fullmatch(str(device or ""))
    if match is None or not isinstance(value, str):
        return None

    parts = [part.strip() for part in value.split(",") if part.strip()]
    if not parts:
        return None

    params: dict[str, str] = {}
    for part in parts[1:]:
        key, separator, param_value = part.partition("=")
        params[key.strip()] = param_value.strip() if separator else "true"

    if str(params.get("media") or "").strip().lower() == "cdrom":
        return None

    volume_id = parts[0]
    storage_id = "unknown"
    volume = volume_id
    if ":" in volume_id:
        storage_id, volume = volume_id.split(":", 1)
        storage_id = storage_id.strip() or "unknown"
        volume = volume.strip()

    return DiskInventory(
        device=device,
        bus=match.group(1),
        index=_safe_int(match.group(2), 0),
        size_gb=round(_parse_disk_size_gb(params.get("size")), 2),
        storage_id=storage_id,
        volume_id=volume_id,
        volume=volume,
        boot=device in boot_devices,
        format=params.get("format", ""),
        cache=params.get("cache", ""),
        discard=params.get("discard", ""),
        iothread=params.get("iothread", ""),
        ssd=params.get("ssd", ""),
        backup=params.get("backup", ""),
        readonly=params.get("readonly", ""),
    )


def _extract_disks(config_data: dict[str, Any], vm_row: dict[str, Any]) -> tuple[DiskInventory, ...]:
    boot_devices = _extract_boot_disk_devices(config_data)
    disks = [
        disk
        for key, value in config_data.items()
        if (disk := _parse_disk_config(str(key), value, boot_devices=boot_devices)) is not None
    ]
    disks.sort(key=lambda disk: (disk.bus, disk.index, disk.device))
    if disks:
        return tuple(disks)

    fallback_gb = _bytes_to_gb(vm_row.get("maxdisk") or vm_row.get("disk"))
    if fallback_gb <= 0:
        return ()
    return (
        DiskInventory(
            device="unknown",
            bus="unknown",
            index=0,
            size_gb=fallback_gb,
            storage_id="unknown",
            volume_id="unknown",
            volume="unknown",
        ),
    )


def _extract_tags(config_data: dict[str, Any]) -> tuple[str, ...]:
    raw = str(config_data.get("tags") or "").strip()
    if not raw:
        return ()
    values = [item.strip() for item in re.split(r"[;,]", raw) if item.strip()]
    return tuple(dict.fromkeys(values))


def _config_guest_agent_enabled(config_data: dict[str, Any]) -> bool:
    if "agent" not in config_data:
        return False
    raw = str(config_data.get("agent") or "").strip().lower()
    if not raw:
        return False
    true_values = {"1", "true", "on", "enabled", "yes"}
    false_values = {"0", "false", "off", "disabled", "no"}
    enabled = False
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        key, separator, value = token.partition("=")
        if separator:
            key = key.strip()
            if key == "enabled":
                normalized = value.strip()
                if normalized in false_values:
                    return False
                if normalized in true_values:
                    enabled = True
                else:
                    return False
            continue
        if token in false_values:
            return False
        if token in true_values:
            enabled = True
    return enabled


def _config_cloud_init_ready(config_data: dict[str, Any]) -> bool:
    if not config_data:
        return False
    for value in config_data.values():
        lowered = str(value or "").lower()
        if "cloudinit" in lowered:
            return True
    return False


def _template_family(name: str) -> str:
    lowered = str(name or "").lower()
    for family in ("ubuntu", "debian", "rocky", "alma", "centos", "rhel", "fedora", "windows"):
        if family in lowered:
            return family
    return "generic"


class FakeProxmoxInventoryAdapter:
    """Fixture-backed read-only inventory adapter for tests and dev mode."""

    source = "fake_read_only"

    def __init__(
        self,
        *,
        source_config: dict[str, Any] | None = None,
        observed_at: str = "2026-05-09T02:38:00+09:00",
    ) -> None:
        self._source_config = dict(source_config or {"mode": self.source})
        self._observed_at = observed_at
        self._storages = (
            StorageInventory(
                storage_id="local-lvm",
                node_id="yoonmanserver2",
                type="lvmthin",
                total_gb=512,
                free_gb=240,
                content=("images", "rootdir"),
            ),
            StorageInventory(
                storage_id="local-lvm",
                node_id="yoonmanserver3",
                type="lvmthin",
                total_gb=512,
                free_gb=256,
                content=("images", "rootdir"),
            ),
        )
        self._networks = (
            NetworkInventory(bridge_id="vmbr0", node_id="yoonmanserver2"),
            NetworkInventory(bridge_id="vmbr0", node_id="yoonmanserver3"),
        )
        self._nodes = (
            NodeInventory(
                node_id="yoonmanserver2",
                display_name="yoonmanserver2",
                status="online",
                cpu_total=16,
                memory_total_mb=65536,
                cpu_usage_percent=18.0,
                memory_used_mb=27525,
                memory_usage_percent=42.0,
                storage=tuple(item for item in self._storages if item.node_id == "yoonmanserver2"),
                networks=tuple(item for item in self._networks if item.node_id == "yoonmanserver2"),
            ),
            NodeInventory(
                node_id="yoonmanserver3",
                display_name="yoonmanserver3",
                status="online",
                cpu_total=16,
                memory_total_mb=65536,
                cpu_usage_percent=12.0,
                memory_used_mb=20316,
                memory_usage_percent=31.0,
                storage=tuple(item for item in self._storages if item.node_id == "yoonmanserver3"),
                networks=tuple(item for item in self._networks if item.node_id == "yoonmanserver3"),
            ),
        )
        self._templates = (
            TemplateInventory(
                template_id="ubuntu-template",
                vmid=9000,
                name="ubuntu-cloudinit-template",
                node_id="yoonmanserver2",
                storage_id="local-lvm",
                family="ubuntu",
                cloud_init_ready=True,
                guest_agent_ready=True,
                cpu=2,
                memory_mb=4096,
                disk_gb=50,
            ),
        )
        self._vms = (
            VmInventory(
                vmid=101,
                name="gjallar-fixture-vm",
                node_id="yoonmanserver2",
                status="running",
                template=False,
                cpu=2,
                memory_mb=4096,
                disk_gb=40,
                ip_addresses=("192.168.2.141",),
                guest_agent=GuestAgentInventory(available=True, ip_addresses=("192.168.2.141",)),
                tags=("gjallar", "fixture"),
                storage_id="local-lvm",
                disks=(
                    DiskInventory(
                        device="scsi0",
                        bus="scsi",
                        index=0,
                        size_gb=40,
                        storage_id="local-lvm",
                        volume_id="local-lvm:vm-101-disk-0",
                        volume="vm-101-disk-0",
                        boot=True,
                        format="raw",
                        discard="on",
                    ),
                ),
            ),
        )

    def redacted_connection_context(self) -> dict[str, Any]:
        return redact_secrets({"source": self.source, **self._source_config})

    def snapshot(self) -> InventorySnapshot:
        return InventorySnapshot(
            source=self.source,
            observed_at=self._observed_at,
            nodes=self._nodes,
            vms=self._vms,
            templates=self._templates,
            connection=self.redacted_connection_context(),
        )

    def list_nodes(self) -> list[NodeInventory]:
        return list(self._nodes)

    def list_vms(self) -> list[VmInventory]:
        return list(self._vms)

    def get_vm(self, vmid: int) -> VmInventory | None:
        for vm in self._vms:
            if vm.vmid == vmid:
                return vm
        return None

    def list_templates(self) -> list[TemplateInventory]:
        return list(self._templates)

    def list_storage(self, node_id: str | None = None) -> list[StorageInventory]:
        if node_id is None:
            return list(self._storages)
        return [storage for storage in self._storages if storage.node_id == node_id]

    def list_networks(self, node_id: str | None = None) -> list[NetworkInventory]:
        if node_id is None:
            return list(self._networks)
        return [network for network in self._networks if network.node_id == node_id]

    def suggest_next_vmid(self) -> int:
        used = {vm.vmid for vm in self._vms} | {template.vmid for template in self._templates}
        return _first_unused_vmid(used, start=102)


class LiveProxmoxInventoryAdapter:
    """Read-only live Proxmox inventory adapter with short TTL caching."""

    source = "live_read_only"

    def __init__(
        self,
        *,
        api_url: str,
        token_id: str,
        token_secret: str,
        tls_insecure: bool = False,
        request_get: Callable[..., Any] | None = None,
        connect_timeout_seconds: float = 5.0,
        read_timeout_seconds: float = 15.0,
        guest_agent_timeout_seconds: float = 3.0,
        cache_ttl_seconds: float = 10.0,
        detail_workers: int = 8,
    ) -> None:
        self.api_url = str(api_url).rstrip("/")
        self.token_id = str(token_id)
        self.token_secret = str(token_secret)
        self.tls_insecure = bool(tls_insecure)
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 0.1)
        self.read_timeout_seconds = max(float(read_timeout_seconds), 0.5)
        self.guest_agent_timeout_seconds = max(float(guest_agent_timeout_seconds), 0.5)
        self.cache_ttl_seconds = max(float(cache_ttl_seconds), 0.0)
        self.detail_workers = max(int(detail_workers), 1)
        self._request_get = request_get or self._default_request_get
        self._snapshot_lock = threading.Lock()
        self._snapshot_cached_at = 0.0
        self._snapshot_cache: InventorySnapshot | None = None
        self._detail_cache_lock = threading.Lock()
        self._detail_cache: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}
        self._source_config = {
            "mode": self.source,
            "api_url": self.api_url,
            "token_id": self.token_id,
            "token_secret": self.token_secret,
            "tls_insecure": self.tls_insecure,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "detail_workers": self.detail_workers,
            "read_timeout_seconds": self.read_timeout_seconds,
        }

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"PVEAPIToken={self.token_id}={self.token_secret}"}

    def _default_request_get(self, path: str, *, timeout: tuple[float, float] | None = None) -> Any:
        response = requests.get(
            f"{self.api_url}{path}",
            headers=self._auth_headers(),
            verify=not self.tls_insecure,
            timeout=timeout or (self.connect_timeout_seconds, self.read_timeout_seconds),
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("data", payload)

    def redacted_connection_context(self) -> dict[str, Any]:
        return redact_secrets({"source": self.source, **self._source_config})

    def _get_json(self, path: str, *, timeout: tuple[float, float] | None = None) -> Any:
        return self._request_get(path, timeout=timeout)

    def _list_nodes_payload(self) -> list[dict[str, Any]]:
        payload = self._get_json("/nodes")
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    def _list_qemu_payload(self, node_id: str) -> list[dict[str, Any]]:
        payload = self._get_json(f"/nodes/{node_id}/qemu")
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    def _list_storage_payload(self, node_id: str) -> list[dict[str, Any]]:
        try:
            payload = self._get_json(f"/nodes/{node_id}/storage")
        except Exception:
            return []
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    def _list_network_payload(self, node_id: str) -> list[dict[str, Any]]:
        try:
            payload = self._get_json(f"/nodes/{node_id}/network")
        except Exception:
            return []
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    def _load_vm_detail(self, node_id: str, vm_row: dict[str, Any]) -> dict[str, Any]:
        vmid = _safe_int(vm_row.get("vmid"))
        cache_key = (node_id, vmid)
        now = time.time()
        with self._detail_cache_lock:
            cached = self._detail_cache.get(cache_key)
            if cached and now - cached[0] <= self.cache_ttl_seconds:
                return dict(cached[1])

        config_timeout = (self.connect_timeout_seconds, min(self.read_timeout_seconds, 5.0))
        guest_timeout = (self.connect_timeout_seconds, min(self.guest_agent_timeout_seconds, self.read_timeout_seconds))
        config_data: dict[str, Any] = {}
        guest_ips: tuple[str, ...] = ()

        try:
            payload = self._get_json(f"/nodes/{node_id}/qemu/{vmid}/config", timeout=config_timeout)
            if isinstance(payload, dict):
                config_data = payload
        except Exception:
            config_data = {}

        if str(vm_row.get("status") or "").lower() == "running":
            try:
                payload = self._get_json(
                    f"/nodes/{node_id}/qemu/{vmid}/agent/network-get-interfaces",
                    timeout=guest_timeout,
                )
                guest_ips = _extract_guest_agent_ipv4_addresses(payload)
            except Exception:
                guest_ips = ()

        configured_ips = _extract_configured_ipv4_addresses(config_data)
        disks = _extract_disks(config_data, vm_row)
        detail = {
            "disk_gb": int(round(sum(disk.size_gb for disk in disks))) if disks else _extract_disk_size_gb(config_data, vm_row),
            "disks": disks,
            "ip_addresses": _merge_ip_addresses(list(configured_ips), list(guest_ips)),
            "guest_agent": GuestAgentInventory(available=bool(guest_ips), ip_addresses=guest_ips),
            "guest_agent_configured": _config_guest_agent_enabled(config_data),
            "cloud_init_ready": _config_cloud_init_ready(config_data),
            "tags": _extract_tags(config_data),
            "storage_id": next((disk.storage_id for disk in disks if disk.storage_id != "unknown"), _extract_storage_id(config_data)),
        }
        with self._detail_cache_lock:
            self._detail_cache[cache_key] = (time.time(), detail)
        return dict(detail)

    def _template_from_row(self, node_id: str, vm_row: dict[str, Any]) -> TemplateInventory:
        vmid = _safe_int(vm_row.get("vmid"))
        name = str(vm_row.get("name") or f"template-{vmid}")
        detail = self._load_vm_detail(node_id, vm_row)
        return TemplateInventory(
            template_id=name,
            vmid=vmid,
            name=name,
            node_id=node_id,
            storage_id=str(detail.get("storage_id") or "unknown"),
            family=_template_family(name),
            cloud_init_ready=detail.get("cloud_init_ready") is True,
            guest_agent_ready=detail.get("guest_agent_configured") is True,
            cpu=_safe_int(vm_row.get("cpus") or vm_row.get("cpu") or vm_row.get("cores")),
            memory_mb=_bytes_to_mb(vm_row.get("maxmem") or vm_row.get("mem") or vm_row.get("memory")),
            disk_gb=_safe_int(detail.get("disk_gb")),
        )

    def _vm_from_row(self, node_id: str, vm_row: dict[str, Any], detail: dict[str, Any]) -> VmInventory:
        vmid = _safe_int(vm_row.get("vmid"))
        name = str(vm_row.get("name") or f"vm-{vmid}")
        cpu = _safe_int(vm_row.get("cpus") or vm_row.get("cpu") or vm_row.get("cores"))
        memory_mb = _bytes_to_mb(vm_row.get("maxmem") or vm_row.get("mem") or vm_row.get("memory"))
        guest_agent = detail.get("guest_agent")
        if not isinstance(guest_agent, GuestAgentInventory):
            guest_agent = GuestAgentInventory(available=False)
        return VmInventory(
            vmid=vmid,
            name=name,
            node_id=node_id,
            status=str(vm_row.get("status") or "unknown"),
            template=False,
            cpu=cpu,
            memory_mb=memory_mb,
            disk_gb=_safe_int(detail.get("disk_gb")),
            ip_addresses=tuple(detail.get("ip_addresses") or ()),
            guest_agent=guest_agent,
            tags=tuple(detail.get("tags") or ()),
            storage_id=str(detail.get("storage_id") or "unknown"),
            disks=tuple(detail.get("disks") or ()),
        )

    def _collect_inventory(self) -> InventorySnapshot:
        node_rows = sorted(self._list_nodes_payload(), key=lambda item: _natural_sort_key(item.get("node")))
        node_storage: dict[str, tuple[StorageInventory, ...]] = {}
        node_networks: dict[str, tuple[NetworkInventory, ...]] = {}
        node_vm_rows: dict[str, list[dict[str, Any]]] = {}
        template_rows: list[tuple[str, dict[str, Any]]] = []
        live_vm_rows: list[tuple[str, dict[str, Any]]] = []

        for node_row in node_rows:
            node_id = str(node_row.get("node") or node_row.get("id") or "unknown")
            storages = [
                StorageInventory(
                    storage_id=str(item.get("storage") or item.get("storage_id") or "unknown"),
                    node_id=node_id,
                    type=str(item.get("type") or "unknown"),
                    total_gb=_bytes_to_gb(item.get("total")),
                    free_gb=_bytes_to_gb(item.get("avail") or item.get("available")),
                    content=tuple(
                        piece.strip()
                        for piece in str(item.get("content") or "").split(",")
                        if piece.strip()
                    ),
                )
                for item in self._list_storage_payload(node_id)
            ]
            node_storage[node_id] = tuple(storages)

            networks = [
                NetworkInventory(
                    bridge_id=str(item.get("iface") or item.get("bridge") or item.get("id") or "unknown"),
                    node_id=node_id,
                    type=str(item.get("type") or "bridge"),
                    active=bool(item.get("active", True)),
                )
                for item in self._list_network_payload(node_id)
                if str(item.get("iface") or item.get("bridge") or "").startswith("vmbr")
            ]
            node_networks[node_id] = tuple(networks)

            qemu_rows = self._list_qemu_payload(node_id)
            node_vm_rows[node_id] = qemu_rows
            for vm_row in qemu_rows:
                if bool(vm_row.get("template")):
                    template_rows.append((node_id, vm_row))
                else:
                    live_vm_rows.append((node_id, vm_row))

        detail_map: dict[tuple[str, int], dict[str, Any]] = {}
        if live_vm_rows:
            with ThreadPoolExecutor(max_workers=self.detail_workers) as executor:
                future_map = {
                    executor.submit(self._load_vm_detail, node_id, vm_row): (node_id, _safe_int(vm_row.get("vmid")))
                    for node_id, vm_row in live_vm_rows
                }
                for future, cache_key in future_map.items():
                    try:
                        detail_map[cache_key] = future.result()
                    except Exception:
                        detail_map[cache_key] = {
                            "disk_gb": _bytes_to_gb(0),
                            "ip_addresses": (),
                            "guest_agent": GuestAgentInventory(available=False),
                            "tags": (),
                            "storage_id": "unknown",
                        }

        nodes = []
        for node_id, node_row in (
            (str(item.get("node") or item.get("id") or "unknown"), item) for item in node_rows
        ):
            memory_total_mb = _bytes_to_mb(node_row.get("maxmem"))
            memory_used_mb = _bytes_to_mb(node_row.get("mem"))
            nodes.append(
                NodeInventory(
                    node_id=node_id,
                    display_name=str(node_row.get("node") or node_row.get("name") or node_id),
                    status=str(node_row.get("status") or "unknown"),
                    cpu_total=_safe_int(node_row.get("maxcpu")),
                    memory_total_mb=memory_total_mb,
                    cpu_usage_percent=_node_cpu_usage_percent(node_row),
                    memory_used_mb=memory_used_mb,
                    memory_usage_percent=_node_memory_usage_percent(
                        used_mb=memory_used_mb,
                        total_mb=memory_total_mb,
                    ),
                    storage=node_storage.get(node_id, ()),
                    networks=node_networks.get(node_id, ()),
                )
            )

        vms = [
            self._vm_from_row(node_id, vm_row, detail_map.get((node_id, _safe_int(vm_row.get("vmid"))), {}))
            for node_id, vm_row in sorted(
                live_vm_rows,
                key=lambda item: (
                    _natural_sort_key(item[0]),
                    _safe_int(item[1].get("vmid")),
                    _natural_sort_key(item[1].get("name")),
                ),
            )
        ]
        templates = [
            self._template_from_row(node_id, vm_row)
            for node_id, vm_row in sorted(
                template_rows,
                key=lambda item: (
                    _natural_sort_key(item[0]),
                    _safe_int(item[1].get("vmid")),
                    _natural_sort_key(item[1].get("name")),
                ),
            )
        ]

        return InventorySnapshot(
            source=self.source,
            observed_at=datetime.now(timezone.utc).isoformat(),
            nodes=tuple(nodes),
            vms=tuple(vms),
            templates=tuple(templates),
            connection=self.redacted_connection_context(),
        )

    def snapshot(self) -> InventorySnapshot:
        now = time.time()
        with self._snapshot_lock:
            if self._snapshot_cache and now - self._snapshot_cached_at <= self.cache_ttl_seconds:
                return self._snapshot_cache
            snapshot = self._collect_inventory()
            self._snapshot_cache = snapshot
            self._snapshot_cached_at = time.time()
            return snapshot

    def list_nodes(self) -> list[NodeInventory]:
        return list(self.snapshot().nodes)

    def list_vms(self) -> list[VmInventory]:
        return list(self.snapshot().vms)

    def get_vm(self, vmid: int) -> VmInventory | None:
        for vm in self.snapshot().vms:
            if vm.vmid == vmid:
                return vm
        return None

    def list_templates(self) -> list[TemplateInventory]:
        return list(self.snapshot().templates)

    def list_storage(self, node_id: str | None = None) -> list[StorageInventory]:
        items = [storage for node in self.snapshot().nodes for storage in node.storage]
        if node_id is None:
            return items
        return [storage for storage in items if storage.node_id == node_id]

    def list_networks(self, node_id: str | None = None) -> list[NetworkInventory]:
        items = [network for node in self.snapshot().nodes for network in node.networks]
        if node_id is None:
            return items
        return [network for network in items if network.node_id == node_id]

    def suggest_next_vmid(self) -> int:
        try:
            resolved = _safe_int(self._get_json("/cluster/nextid"))
            if resolved >= 100:
                return resolved
        except Exception:
            pass
        snapshot = self.snapshot()
        used = {vm.vmid for vm in snapshot.vms} | {template.vmid for template in snapshot.templates}
        return _first_unused_vmid(used)


def _build_adapter_from_env() -> FakeProxmoxInventoryAdapter | LiveProxmoxInventoryAdapter:
    _load_project_env()

    mode = str(os.getenv("GJALLAR_INVENTORY_MODE", "auto") or "auto").strip().lower()
    api_url = str(os.getenv("PROXMOX_API_URL", "")).strip()
    token_id = str(os.getenv("PROXMOX_API_TOKEN_ID", "")).strip()
    token_secret = str(os.getenv("PROXMOX_API_TOKEN_SECRET", "")).strip()
    tls_insecure = _read_bool_env("PROXMOX_TLS_INSECURE", default=False)
    connect_timeout_seconds = _read_float_env("PROXMOX_API_CONNECT_TIMEOUT_SECONDS", 5.0, minimum=0.1)
    read_timeout_seconds = _read_float_env(
        "PROXMOX_API_READ_TIMEOUT_SECONDS",
        _read_float_env("PROXMOX_API_TIMEOUT_SECONDS", 15.0, minimum=0.5),
        minimum=0.5,
    )
    cache_ttl_seconds = _read_float_env("PROXMOX_VM_INVENTORY_CACHE_TTL_SECONDS", 10.0, minimum=0.0)
    detail_workers = _read_int_env("PROXMOX_VM_INVENTORY_WORKERS", 8, minimum=1)
    guest_agent_timeout_seconds = _read_float_env("PROXMOX_GUEST_AGENT_TIMEOUT_SECONDS", 3.0, minimum=0.5)

    if mode == "fake" or not (api_url and token_id and token_secret):
        return FakeProxmoxInventoryAdapter(
            source_config={
                "mode": "fake" if mode == "fake" else "fallback_fake_read_only",
                "api_url": api_url,
                "token_id": token_id,
                "token_secret": token_secret,
                "tls_insecure": tls_insecure,
            }
        )

    return LiveProxmoxInventoryAdapter(
        api_url=api_url,
        token_id=token_id,
        token_secret=token_secret,
        tls_insecure=tls_insecure,
        connect_timeout_seconds=connect_timeout_seconds,
        read_timeout_seconds=read_timeout_seconds,
        guest_agent_timeout_seconds=guest_agent_timeout_seconds,
        cache_ttl_seconds=cache_ttl_seconds,
        detail_workers=detail_workers,
    )


def get_default_inventory_adapter() -> FakeProxmoxInventoryAdapter | LiveProxmoxInventoryAdapter:
    """Return the current non-mutating inventory adapter for /api/v1."""
    global _DEFAULT_ADAPTER_SIGNATURE, _DEFAULT_ADAPTER

    _load_project_env()
    signature = (
        os.getenv("GJALLAR_INVENTORY_MODE", "auto"),
        os.getenv("PROXMOX_API_URL", ""),
        os.getenv("PROXMOX_API_TOKEN_ID", ""),
        os.getenv("PROXMOX_API_TOKEN_SECRET", ""),
        os.getenv("PROXMOX_TLS_INSECURE", ""),
        os.getenv("PROXMOX_API_CONNECT_TIMEOUT_SECONDS", ""),
        os.getenv("PROXMOX_API_READ_TIMEOUT_SECONDS", ""),
        os.getenv("PROXMOX_API_TIMEOUT_SECONDS", ""),
        os.getenv("PROXMOX_VM_INVENTORY_CACHE_TTL_SECONDS", ""),
        os.getenv("PROXMOX_VM_INVENTORY_WORKERS", ""),
        os.getenv("PROXMOX_GUEST_AGENT_TIMEOUT_SECONDS", ""),
    )

    with _DEFAULT_ADAPTER_LOCK:
        if _DEFAULT_ADAPTER is None or _DEFAULT_ADAPTER_SIGNATURE != signature:
            _DEFAULT_ADAPTER = _build_adapter_from_env()
            _DEFAULT_ADAPTER_SIGNATURE = signature
        return _DEFAULT_ADAPTER
