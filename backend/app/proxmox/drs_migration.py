"""Dedicated Proxmox client for DRS live migration execution.

This module intentionally does not import or reuse ``app.proxmox.client``. DRS
live migration has its own environment variables, narrow API surface, and
execution gates.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import requests
import urllib3
from dotenv import load_dotenv

from app.core.redaction import redact_secrets

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_ENV_LOADED = False
_ENV_LOCK = threading.Lock()


class DrsProxmoxMigrationError(RuntimeError):
    """Raised when the DRS-only Proxmox migration client cannot collect evidence or mutate."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = redact_secrets(dict(details or {}))


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


def _as_text(value: Any, fallback: str = "") -> str:
    text = str(value if value is not None else "").strip()
    return text or fallback


def _as_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _empty_not_allowed_detail(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (dict, list, tuple, set)):
        return len(value) == 0
    return False


def _not_allowed_nodes_evidence(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        all_nodes = sorted([node for node in (_as_text(key) for key in value) if node])
        blocking_details = {
            _as_text(node): redact_secrets(detail)
            for node, detail in value.items()
            if _as_text(node) and not _empty_not_allowed_detail(detail)
        }
        return {
            "shape": "object",
            "all_nodes": all_nodes,
            "blocking_nodes": sorted(blocking_details),
            "blocking_details": blocking_details,
        }
    nodes = sorted([node for node in (_as_text(item) for item in _as_list(value)) if node])
    return {
        "shape": "list" if isinstance(value, list) else type(value).__name__,
        "all_nodes": nodes,
        "blocking_nodes": nodes,
        "blocking_details": {},
    }


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _compact_dict(value: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in keys if key in value}


def _compact_tasks(tasks: list[Any]) -> list[dict[str, Any]]:
    keys = ("upid", "id", "node", "type", "user", "status", "pid", "starttime", "endtime")
    return [_compact_dict(task, keys) for task in tasks if isinstance(task, dict)][:10]


def _compact_log(lines: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for line in lines[:50]:
        if isinstance(line, dict):
            entry = _compact_dict(line, ("n", "t", "msg"))
            if "msg" in entry:
                entry["msg"] = _as_text(entry["msg"])[:500]
            result.append(entry)
    return result


class DrsProxmoxMigrationClient:
    """Small DRS-only Proxmox client for live migration prechecks and mutation."""

    def __init__(
        self,
        *,
        api_url: str,
        token_id: str,
        token_secret: str,
        tls_insecure: bool = False,
        request: Callable[..., Any] | None = None,
        connect_timeout_seconds: float = 5.0,
        read_timeout_seconds: float = 30.0,
        task_poll_interval_seconds: float = 2.0,
        task_timeout_seconds: float = 30.0,
    ) -> None:
        self.api_url = str(api_url).rstrip("/")
        self.token_id = str(token_id)
        self.token_secret = str(token_secret)
        self.tls_insecure = bool(tls_insecure)
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 0.1)
        self.read_timeout_seconds = max(float(read_timeout_seconds), 0.5)
        self.task_poll_interval_seconds = max(float(task_poll_interval_seconds), 0.1)
        self.task_timeout_seconds = max(float(task_timeout_seconds), 1.0)
        self._request = request or self._default_request

    @classmethod
    def from_env(cls) -> "DrsProxmoxMigrationClient":
        _load_project_env()
        api_url = str(os.getenv("PROXMOX_DRS_API_URL", "")).strip()
        token_id = str(os.getenv("PROXMOX_DRS_API_TOKEN_ID", "")).strip()
        token_secret = str(os.getenv("PROXMOX_DRS_API_TOKEN_SECRET", "")).strip()
        if not (api_url and token_id and token_secret):
            raise DrsProxmoxMigrationError(
                "PROXMOX_DRS_API_URL, PROXMOX_DRS_API_TOKEN_ID, and PROXMOX_DRS_API_TOKEN_SECRET are required for DRS migration"
            )
        return cls(
            api_url=api_url,
            token_id=token_id,
            token_secret=token_secret,
            tls_insecure=_read_bool_env("PROXMOX_DRS_TLS_INSECURE", default=False),
            connect_timeout_seconds=_read_float_env("PROXMOX_DRS_API_CONNECT_TIMEOUT_SECONDS", 5.0, minimum=0.1),
            read_timeout_seconds=_read_float_env("PROXMOX_DRS_API_READ_TIMEOUT_SECONDS", 30.0, minimum=0.5),
            task_poll_interval_seconds=_read_float_env(
                "PROXMOX_DRS_TASK_POLL_INTERVAL_SECONDS",
                2.0,
                minimum=0.1,
            ),
            task_timeout_seconds=_read_float_env("PROXMOX_DRS_TASK_TIMEOUT_SECONDS", 30.0, minimum=1.0),
        )

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"PVEAPIToken={self.token_id}={self.token_secret}"}

    def redacted_connection_context(self) -> dict[str, Any]:
        return redact_secrets(
            {
                "mode": "drs_migration_mutation",
                "api_url": self.api_url,
                "token_id": self.token_id,
                "token_secret": self.token_secret,
                "tls_insecure": self.tls_insecure,
                "task_timeout_seconds": self.task_timeout_seconds,
            }
        )

    def _default_request(self, method: str, path: str, *, data: Any = None, timeout: tuple[float, float] | None = None) -> Any:
        response = requests.request(
            method,
            f"{self.api_url}{path}",
            headers=self._auth_headers(),
            data=data,
            verify=not self.tls_insecure,
            timeout=timeout or (self.connect_timeout_seconds, self.read_timeout_seconds),
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            response_json: Any | None = None
            with contextlib.suppress(ValueError):
                response_json = response.json()
            raise DrsProxmoxMigrationError(
                f"Proxmox DRS API HTTP {response.status_code}: {method} {path}",
                details={
                    "method": method,
                    "path": path,
                    "status_code": response.status_code,
                    "reason": response.reason,
                    "response_text": response.text[:2000],
                    "response_json": response_json,
                },
            ) from exc
        payload = response.json()
        return payload.get("data", payload)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        data: Any = None,
        timeout: tuple[float, float] | None = None,
    ) -> Any:
        try:
            return self._request(method, path, data=data, timeout=timeout)
        except DrsProxmoxMigrationError:
            raise
        except Exception as exc:
            raise DrsProxmoxMigrationError(
                f"Proxmox DRS API request failed: {method} {path}",
                details={"method": method, "path": path, "error": str(exc)},
            ) from exc

    def list_active_tasks(self, *, node: str, vmid: int) -> list[Any]:
        data = self._request_json("GET", f"/nodes/{node}/tasks?source=active&vmid={int(vmid)}")
        if not isinstance(data, list):
            raise DrsProxmoxMigrationError(
                "Proxmox active task evidence was not a list",
                details={"node": node, "vmid": int(vmid), "response_type": type(data).__name__},
            )
        return data

    def get_cluster_status(self) -> list[Any]:
        data = self._request_json("GET", "/cluster/status")
        if not isinstance(data, list):
            raise DrsProxmoxMigrationError(
                "Proxmox cluster status evidence was not a list",
                details={"response_type": type(data).__name__},
            )
        return data

    def get_ha_resources(self, *, vmid: int) -> list[Any]:
        data = self._request_json("GET", "/cluster/ha/resources?type=vm")
        if not isinstance(data, list):
            raise DrsProxmoxMigrationError(
                "Proxmox HA resource evidence was not a list",
                details={"vmid": int(vmid), "response_type": type(data).__name__},
            )
        return data

    def get_migration_preconditions(self, *, node: str, vmid: int, target: str) -> dict[str, Any]:
        target_query = quote(str(target), safe="")
        data = self._request_json("GET", f"/nodes/{node}/qemu/{int(vmid)}/migrate?target={target_query}")
        if not isinstance(data, dict):
            raise DrsProxmoxMigrationError(
                "Proxmox migration precondition evidence was not an object",
                details={"node": node, "target": target, "vmid": int(vmid), "response_type": type(data).__name__},
            )
        return data

    def migrate_vm(self, *, source_node: str, target_node: str, vmid: int) -> str:
        payload = {"target": target_node, "online": 1}
        data = self._request_json(
            "POST",
            f"/nodes/{source_node}/qemu/{int(vmid)}/migrate",
            data=payload,
        )
        upid = _as_text(data)
        if not upid:
            raise DrsProxmoxMigrationError(
                "Proxmox DRS migrate did not return a UPID",
                details={"source_node": source_node, "target_node": target_node, "vmid": int(vmid), "payload": payload},
            )
        return upid

    def get_task_status(self, *, node: str, upid: str) -> dict[str, Any]:
        data = self._request_json("GET", f"/nodes/{node}/tasks/{upid}/status")
        return dict(data) if isinstance(data, dict) else {}

    def get_task_log(self, *, node: str, upid: str, start: int = 0, limit: int = 50) -> list[dict[str, Any]]:
        data = self._request_json(
            "GET",
            f"/nodes/{node}/tasks/{upid}/log?start={int(start)}&limit={int(limit)}",
        )
        return _compact_log(_as_list(data))

    def get_vm_status(self, *, node: str, vmid: int) -> dict[str, Any]:
        data = self._request_json("GET", f"/nodes/{node}/qemu/{int(vmid)}/status/current")
        if not isinstance(data, dict):
            raise DrsProxmoxMigrationError(
                "Proxmox VM status evidence was not an object",
                details={"node": node, "vmid": int(vmid), "response_type": type(data).__name__},
            )
        return data

    def get_vm_config(self, *, node: str, vmid: int) -> dict[str, Any]:
        data = self._request_json("GET", f"/nodes/{node}/qemu/{int(vmid)}/config")
        if not isinstance(data, dict):
            raise DrsProxmoxMigrationError(
                "Proxmox VM config evidence was not an object",
                details={"node": node, "vmid": int(vmid), "response_type": type(data).__name__},
            )
        return data

    def collect_live_precheck(self, *, source_node: str, target_node: str, vmid: int) -> dict[str, Any]:
        """Collect execution-blocking live Proxmox evidence before a migration POST."""
        checks: dict[str, dict[str, Any]] = {}
        blockers: list[str] = []

        try:
            active_tasks = self.list_active_tasks(node=source_node, vmid=vmid)
            if active_tasks:
                blockers.append("proxmox_active_task_conflict")
                checks["proxmox_active_task"] = {
                    "status": "failed",
                    "blocker": "proxmox_active_task_conflict",
                    "evidence": {"count": len(active_tasks), "tasks": _compact_tasks(active_tasks), "source": "proxmox_live"},
                }
            else:
                checks["proxmox_active_task"] = {
                    "status": "pass",
                    "evidence": {"count": 0, "tasks": [], "source": "proxmox_live"},
                }
        except DrsProxmoxMigrationError as exc:
            blockers.append("proxmox_active_task_unavailable")
            checks["proxmox_active_task"] = {
                "status": "unavailable",
                "blocker": "proxmox_active_task_unavailable",
                "evidence": {"source": "proxmox_live", "error": str(exc), "details": exc.details},
            }

        try:
            cluster_rows = self.get_cluster_status()
            cluster_row = next((row for row in cluster_rows if isinstance(row, dict) and row.get("type") == "cluster"), None)
            if cluster_row is None:
                blockers.append("proxmox_cluster_quorum_unknown")
                checks["proxmox_cluster_quorum"] = {
                    "status": "ambiguous",
                    "blocker": "proxmox_cluster_quorum_unknown",
                    "evidence": {"source": "proxmox_live", "cluster_row_found": False},
                }
            elif _truthy(cluster_row.get("quorate")):
                checks["proxmox_cluster_quorum"] = {
                    "status": "pass",
                    "evidence": {
                        "source": "proxmox_live",
                        "cluster": _compact_dict(cluster_row, ("name", "type", "quorate", "nodes", "votes", "version")),
                    },
                }
            else:
                blockers.append("proxmox_cluster_not_quorate")
                checks["proxmox_cluster_quorum"] = {
                    "status": "failed",
                    "blocker": "proxmox_cluster_not_quorate",
                    "evidence": {
                        "source": "proxmox_live",
                        "cluster": _compact_dict(cluster_row, ("name", "type", "quorate", "nodes", "votes", "version")),
                    },
                }
        except DrsProxmoxMigrationError as exc:
            blockers.append("proxmox_cluster_quorum_unavailable")
            checks["proxmox_cluster_quorum"] = {
                "status": "unavailable",
                "blocker": "proxmox_cluster_quorum_unavailable",
                "evidence": {"source": "proxmox_live", "error": str(exc), "details": exc.details},
            }

        try:
            ha_rows = self.get_ha_resources(vmid=vmid)
            wanted = {f"vm:{int(vmid)}", str(int(vmid))}
            matches = [
                row
                for row in ha_rows
                if isinstance(row, dict) and _as_text(row.get("sid") or row.get("id") or row.get("name")) in wanted
            ]
            bad_states = {"error", "fence", "disabled", "stopped"}
            states = [_as_text(row.get("state") or row.get("status"), "configured").lower() for row in matches]
            bad = [state for state in states if state in bad_states]
            if bad:
                blockers.append("proxmox_ha_state_conflict")
                checks["proxmox_ha_state"] = {
                    "status": "failed",
                    "blocker": "proxmox_ha_state_conflict",
                    "evidence": {
                        "source": "proxmox_live",
                        "managed": True,
                        "states": states,
                        "resources": [_compact_dict(row, ("sid", "id", "state", "status", "group", "node")) for row in matches],
                    },
                }
            else:
                checks["proxmox_ha_state"] = {
                    "status": "pass",
                    "evidence": {
                        "source": "proxmox_live",
                        "managed": bool(matches),
                        "states": states,
                        "resources": [_compact_dict(row, ("sid", "id", "state", "status", "group", "node")) for row in matches],
                    },
                }
        except DrsProxmoxMigrationError as exc:
            blockers.append("proxmox_ha_state_unavailable")
            checks["proxmox_ha_state"] = {
                "status": "unavailable",
                "blocker": "proxmox_ha_state_unavailable",
                "evidence": {"source": "proxmox_live", "error": str(exc), "details": exc.details},
            }

        try:
            preconditions = self.get_migration_preconditions(node=source_node, vmid=vmid, target=target_node)
            allowed_nodes = [_as_text(item) for item in _as_list(preconditions.get("allowed_nodes"))]
            not_allowed_evidence = _not_allowed_nodes_evidence(preconditions.get("not_allowed_nodes"))
            not_allowed_nodes = set(not_allowed_evidence["all_nodes"])
            blocking_not_allowed_nodes = set(not_allowed_evidence["blocking_nodes"])
            local_disks = _as_list(preconditions.get("local_disks"))
            local_resources = _as_list(preconditions.get("local_resources"))
            dependent_ha = _as_list(preconditions.get("dependent-ha-resources"))
            migration_blockers = []
            if target_node in blocking_not_allowed_nodes:
                migration_blockers.append("proxmox_target_not_allowed")
            if allowed_nodes and target_node not in allowed_nodes:
                migration_blockers.append("proxmox_target_not_allowed")
            if not allowed_nodes and target_node not in not_allowed_nodes:
                migration_blockers.append("proxmox_allowed_nodes_unknown")
            if preconditions.get("running") is not True and str(preconditions.get("running")).lower() not in {"1", "true", "yes"}:
                migration_blockers.append("proxmox_vm_not_running")
            if local_disks:
                migration_blockers.append("proxmox_local_disk_dependency")
            if local_resources:
                migration_blockers.append("proxmox_local_resource_dependency")
            if dependent_ha:
                migration_blockers.append("proxmox_dependent_ha_resource")
            if migration_blockers:
                blockers.extend(migration_blockers)
                checks["proxmox_migration_preconditions"] = {
                    "status": "failed",
                    "blocker": migration_blockers[0],
                    "evidence": {
                        "source": "proxmox_live",
                        "running": preconditions.get("running"),
                        "allowed_nodes": allowed_nodes,
                        "not_allowed_nodes": sorted(not_allowed_nodes),
                        "not_allowed_nodes_with_blocking_details": sorted(blocking_not_allowed_nodes),
                        "not_allowed_node_blocking_details": not_allowed_evidence["blocking_details"],
                        "not_allowed_nodes_shape": not_allowed_evidence["shape"],
                        "local_disks": local_disks[:10],
                        "local_resources": local_resources[:10],
                        "dependent_ha_resources": dependent_ha[:10],
                        "mapped_resource_info_present": "mapped-resource-info" in preconditions,
                    },
                }
            else:
                checks["proxmox_migration_preconditions"] = {
                    "status": "pass",
                    "evidence": {
                        "source": "proxmox_live",
                        "running": preconditions.get("running"),
                        "allowed_nodes": allowed_nodes,
                        "not_allowed_nodes": sorted(not_allowed_nodes),
                        "not_allowed_nodes_with_blocking_details": sorted(blocking_not_allowed_nodes),
                        "not_allowed_node_blocking_details": not_allowed_evidence["blocking_details"],
                        "not_allowed_nodes_shape": not_allowed_evidence["shape"],
                        "local_disks": [],
                        "local_resources": [],
                        "dependent_ha_resources": [],
                        "mapped_resource_info_present": "mapped-resource-info" in preconditions,
                    },
                }
        except DrsProxmoxMigrationError as exc:
            blockers.append("proxmox_migration_preconditions_unavailable")
            checks["proxmox_migration_preconditions"] = {
                "status": "unavailable",
                "blocker": "proxmox_migration_preconditions_unavailable",
                "evidence": {"source": "proxmox_live", "error": str(exc), "details": exc.details},
            }

        return {
            "status": "pass" if not blockers else "blocked",
            "blockers": blockers,
            "checks": checks,
        }

    def poll_task_status(self, *, node: str, upid: str, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
        """Poll minimally; running is a classified immediate result."""
        deadline = time.monotonic() + self.task_timeout_seconds
        polls: list[dict[str, Any]] = []
        while True:
            status = self.get_task_status(node=node, upid=upid)
            compact_status = _compact_dict(status, ("upid", "node", "status", "exitstatus", "type", "id", "user", "starttime", "endtime"))
            polls.append(compact_status)
            normalized = _as_text(status.get("status")).lower()
            if normalized == "stopped":
                exitstatus = _as_text(status.get("exitstatus"))
                result = "ok" if exitstatus == "OK" else "failed"
                return {
                    "result": result,
                    "status": compact_status,
                    "polls": polls[:5],
                    "log": self.get_task_log(node=node, upid=upid),
                }
            if normalized == "running":
                return {
                    "result": "running",
                    "status": compact_status,
                    "polls": polls[:5],
                    "log": self.get_task_log(node=node, upid=upid),
                }
            if time.monotonic() >= deadline:
                return {
                    "result": "timeout",
                    "status": compact_status,
                    "polls": polls[:5],
                    "log": self.get_task_log(node=node, upid=upid),
                }
            if normalized:
                return {
                    "result": "ambiguous",
                    "status": compact_status,
                    "polls": polls[:5],
                    "log": self.get_task_log(node=node, upid=upid),
                }
            sleep(self.task_poll_interval_seconds)


def get_default_drs_proxmox_migration_client() -> DrsProxmoxMigrationClient:
    """Build a dedicated DRS live migration client from DRS-only env vars."""
    return DrsProxmoxMigrationClient.from_env()
