"""Proxmox mutation client for explicit VM create operations.

This module is intentionally separate from ``app.proxmox.inventory``.  The
inventory adapter remains read-only; callers import this client only for
approval-gated native Proxmox mutations.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

import requests
import urllib3
from dotenv import load_dotenv

from app.core.redaction import redact_secrets

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_ENV_LOADED = False
_ENV_LOCK = threading.Lock()


class ProxmoxMutationError(RuntimeError):
    """Raised when an approval-gated Proxmox mutation cannot complete."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})


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


class ProxmoxMutationClient:
    """Small Proxmox API client for clone/config/post-check calls."""

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
        task_timeout_seconds: float = 900.0,
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
    def from_env(cls) -> "ProxmoxMutationClient":
        _load_project_env()
        api_url = str(os.getenv("PROXMOX_API_URL", "")).strip()
        token_id = str(os.getenv("PROXMOX_API_TOKEN_ID", "")).strip()
        token_secret = str(os.getenv("PROXMOX_API_TOKEN_SECRET", "")).strip()
        if not (api_url and token_id and token_secret):
            raise ProxmoxMutationError(
                "PROXMOX_API_URL, PROXMOX_API_TOKEN_ID, and PROXMOX_API_TOKEN_SECRET are required for native create"
            )
        return cls(
            api_url=api_url,
            token_id=token_id,
            token_secret=token_secret,
            tls_insecure=_read_bool_env("PROXMOX_TLS_INSECURE", default=False),
            connect_timeout_seconds=_read_float_env("PROXMOX_API_CONNECT_TIMEOUT_SECONDS", 5.0, minimum=0.1),
            read_timeout_seconds=_read_float_env(
                "PROXMOX_API_READ_TIMEOUT_SECONDS",
                _read_float_env("PROXMOX_API_TIMEOUT_SECONDS", 30.0, minimum=0.5),
                minimum=0.5,
            ),
            task_poll_interval_seconds=_read_float_env(
                "PROXMOX_TASK_POLL_INTERVAL_SECONDS",
                _read_float_env("GJALLAR_PROXMOX_TASK_POLL_INTERVAL_SECONDS", 2.0, minimum=0.1),
                minimum=0.1,
            ),
            task_timeout_seconds=_read_float_env(
                "PROXMOX_TASK_TIMEOUT_SECONDS",
                _read_float_env("GJALLAR_PROXMOX_TASK_TIMEOUT_SECONDS", 900.0, minimum=1.0),
                minimum=1.0,
            ),
        )

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"PVEAPIToken={self.token_id}={self.token_secret}"}

    def redacted_connection_context(self) -> dict[str, Any]:
        return redact_secrets(
            {
                "mode": "native_mutation",
                "api_url": self.api_url,
                "token_id": self.token_id,
                "token_secret": self.token_secret,
                "tls_insecure": self.tls_insecure,
                "task_timeout_seconds": self.task_timeout_seconds,
            }
        )

    def _default_request(self, method: str, path: str, *, data: dict[str, Any] | None = None, timeout: tuple[float, float] | None = None) -> Any:
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
            raise ProxmoxMutationError(
                f"Proxmox API HTTP {response.status_code}: {method} {path}",
                details={
                    "method": method,
                    "path": path,
                    "status_code": response.status_code,
                    "reason": response.reason,
                    "response_text": response.text,
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
        data: dict[str, Any] | None = None,
        timeout: tuple[float, float] | None = None,
    ) -> Any:
        try:
            return self._request(method, path, data=data, timeout=timeout)
        except ProxmoxMutationError:
            raise
        except Exception as exc:
            raise ProxmoxMutationError(
                f"Proxmox API request failed: {method} {path}",
                details={"method": method, "path": path, "error": str(exc)},
            ) from exc

    def clone_vm(
        self,
        *,
        template_node: str,
        template_vmid: int,
        newid: int,
        name: str,
        target: str,
        storage: str,
    ) -> str:
        payload = {
            "newid": int(newid),
            "name": name,
            "target": target,
            "storage": storage,
            "full": 1,
        }
        data = self._request_json(
            "POST",
            f"/nodes/{template_node}/qemu/{int(template_vmid)}/clone",
            data=payload,
        )
        upid = str(data or "").strip()
        if not upid:
            raise ProxmoxMutationError("Proxmox clone did not return a UPID", details={"payload": payload})
        return upid

    def get_task_status(self, *, node: str, upid: str) -> dict[str, Any]:
        data = self._request_json("GET", f"/nodes/{node}/tasks/{upid}/status")
        return dict(data) if isinstance(data, dict) else {}

    def wait_for_task(
        self,
        *,
        node: str,
        upid: str,
        sleep: Callable[[float], None] = time.sleep,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.task_timeout_seconds
        polls: list[dict[str, Any]] = []
        while True:
            status = self.get_task_status(node=node, upid=upid)
            polls.append(status)
            if str(status.get("status") or "").lower() == "stopped":
                return {
                    "node": node,
                    "upid": upid,
                    "status": status.get("status"),
                    "exitstatus": status.get("exitstatus"),
                    "polls": polls,
                }
            if time.monotonic() >= deadline:
                raise ProxmoxMutationError(
                    "Timed out waiting for Proxmox task",
                    details={"node": node, "upid": upid, "polls": polls},
                )
            sleep(self.task_poll_interval_seconds)

    def set_vm_config(self, *, node: str, vmid: int, config: dict[str, Any]) -> Any:
        return self._request_json("PUT", f"/nodes/{node}/qemu/{int(vmid)}/config", data=config)

    def resize_vm_disk(self, *, node: str, vmid: int, disk: str, size: int) -> Any:
        payload = {
            "disk": str(disk),
            "size": f"{int(size)}G",
        }
        return self._request_json("PUT", f"/nodes/{node}/qemu/{int(vmid)}/resize", data=payload)

    def start_vm(self, *, node: str, vmid: int) -> str:
        data = self._request_json("POST", f"/nodes/{node}/qemu/{int(vmid)}/status/start")
        upid = str(data or "").strip()
        if not upid:
            raise ProxmoxMutationError("Proxmox start did not return a UPID", details={"node": node, "vmid": int(vmid)})
        return upid

    def get_vm_status(self, *, node: str, vmid: int) -> dict[str, Any]:
        data = self._request_json("GET", f"/nodes/{node}/qemu/{int(vmid)}/status/current")
        return dict(data) if isinstance(data, dict) else {}

    def get_vm_config(self, *, node: str, vmid: int) -> dict[str, Any]:
        data = self._request_json("GET", f"/nodes/{node}/qemu/{int(vmid)}/config")
        return dict(data) if isinstance(data, dict) else {}


def get_default_proxmox_mutation_client() -> ProxmoxMutationClient:
    """Build a native Proxmox mutation client from the existing inventory env."""
    return ProxmoxMutationClient.from_env()
