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
from urllib.parse import quote
from typing import Any, Callable, Sequence

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

    def _default_request(self, method: str, path: str, *, data: Any = None, timeout: tuple[float, float] | None = None,
                         response_metadata: bool = False, host_network_configuration: bool = False) -> Any:
        # PVE only parses request bodies for POST/PUT; DELETE flags belong in the query.
        payload_options = {"params": data} if method == "DELETE" else {"data": data}
        response = requests.request(
            method,
            f"{self.api_url}{path}",
            headers=self._auth_headers(),
            **payload_options,
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
        return payload if response_metadata else payload.get("data", payload)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        data: Any = None,
        timeout: tuple[float, float] | None = None,
        response_metadata: bool = False,
        host_network_configuration: bool = False,
    ) -> Any:
        try:
            options = {"response_metadata": True} if response_metadata else {}
            if host_network_configuration:
                options['host_network_configuration'] = True
            return self._request(method, path, data=data, timeout=timeout, **options)
        except ProxmoxMutationError:
            raise
        except Exception as exc:
            raise ProxmoxMutationError(
                f"Proxmox API request failed: {method} {path}",
                details={"method": method, "path": path, "error": str(exc)},
            ) from exc

    def get_monitoring_data(self, *, kind, node, vmid=None, storage=None, timeframe=None):
        from app.setup_integration.contracts import SetupError
        paths = {
            "node": f"/nodes/{quote(node, safe='')}",
            "vm": f"/nodes/{quote(node, safe='')}/qemu/{vmid}",
            "storage": f"/nodes/{quote(node, safe='')}/storage/{quote(storage or '', safe='')}",
        }
        if kind not in paths or (timeframe is not None and timeframe not in {'hour', 'day', 'week', 'month', 'year'}):
            raise ProxmoxMutationError("Unsupported monitoring target or timeframe")
        path = paths[kind] + ('/rrddata' if timeframe else '/status/current' if kind == 'vm' else '/status')
        if timeframe:
            path += f'?timeframe={timeframe}&cf=AVERAGE'
        try:
            return self._request('GET', path, timeout=(self.connect_timeout_seconds, self.read_timeout_seconds))
        except (SetupError, ProxmoxMutationError):
            raise
        except (requests.RequestException, ValueError, OSError):
            raise ProxmoxMutationError("Monitoring observation unavailable") from None

    def list_nodes(self):
        data = self._request_json("GET", "/nodes")
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise ProxmoxMutationError("Invalid node inventory response")
        return data

    def get_node_status(self, *, node):
        data = self._request_json("GET", f"/nodes/{node}/status")
        if not isinstance(data, dict):
            raise ProxmoxMutationError("Invalid node status response")
        return data

    def get_vm_migration_preconditions(self, *, node, vmid, destination):
        data = self._request_json("GET", f"/nodes/{node}/qemu/{vmid}/migrate?target={quote(destination, safe='')}")
        if not isinstance(data, dict):
            raise ProxmoxMutationError("Invalid migration precondition response")
        return data

    def migrate_vm_reviewed(self, *, node, vmid, destination):
        from app.operations.vm_migrate.domain import request_body
        return self._request_json("POST", f"/nodes/{node}/qemu/{vmid}/migrate", data=request_body(destination))

    def get_node_network_snapshot(self, *, node):
        payload = self._request_json("GET", f"/nodes/{node}/network", response_metadata=True)
        if (not isinstance(payload, dict) or not isinstance(payload.get("data"), list)
                or any(not isinstance(row, dict) for row in payload["data"])
                or ("changes" in payload and not isinstance(payload["changes"], str))):
            raise ProxmoxMutationError("Invalid network snapshot envelope")
        # Do not expose the host configuration diff (addresses and other data).
        return {"interfaces": payload["data"], "pending_changes": bool(payload.get("changes"))}

    def get_bridge_permissions(self, *, bridge):
        path = f"/sdn/zones/localnetwork/{bridge}"
        payload = self._request_json("GET", "/access/permissions?path=" + quote(path, safe=""))
        if not isinstance(payload, dict) or not isinstance(payload.get(path), dict):
            raise ProxmoxMutationError("Invalid bridge permission response")
        return set(payload[path])

    def get_host_network_snapshot(self, *, node):
        # The caller validates the full pending diff in memory; do not log this envelope.
        payload = self._request_json('GET', f'/nodes/{node}/network', response_metadata=True, host_network_configuration=True)
        if (not isinstance(payload, dict) or not isinstance(payload.get('data'), list)
                or any(not isinstance(row, dict) for row in payload['data'])
                or ('changes' in payload and not isinstance(payload['changes'], str))):
            raise ProxmoxMutationError('Invalid host network snapshot envelope')
        return {'interfaces': payload['data'], 'changes': payload.get('changes', '')}

    def get_host_network_permissions(self, *, node):
        permissions = {}
        for path in (f'/nodes/{node}', '/sdn/zones/localnetwork'):
            payload = self._request_json('GET', '/access/permissions?path=' + quote(path, safe=''))
            if not isinstance(payload, dict) or not isinstance(payload.get(path), dict):
                raise ProxmoxMutationError('Invalid host network permission response')
            permissions[path] = set(payload[path])
        return permissions

    def stage_host_bridge(self, *, node, bridge, change):
        from app.operations.host_network.domain import mutation_body
        path = f'/nodes/{node}/network' + (f'/{bridge}' if change.mode == 'update' else '')
        return self._request_json('PUT' if change.mode == 'update' else 'POST', path,
                                  data=mutation_body(change, bridge_id=bridge))

    def reload_host_network(self, *, node):
        return self._request_json('PUT', f'/nodes/{node}/network', data={'regenerate-frr': 0})

    def list_vm_resources(self):
        result = self._request_json("GET", "/cluster/resources?type=vm")
        if not isinstance(result, list) or any(not isinstance(row, dict) or type(row.get("vmid")) is not int for row in result):
            raise ProxmoxMutationError("Invalid VM resource inventory")
        return result

    def assert_vmid_unused(self, *, vmid):
        result = self._request_json("GET", f"/cluster/nextid?vmid={vmid}")
        if not ((type(result) is int and result == vmid) or (isinstance(result, str) and result == str(vmid))):
            raise ProxmoxMutationError("VMID absence is unconfirmed")
        return True

    def get_vm_snapshots(self, *, node, vmid):
        result = self._request_json("GET", f"/nodes/{node}/qemu/{vmid}/snapshot")
        if not isinstance(result, list) or any(not isinstance(row, dict) or not isinstance(row.get("name"), str) for row in result):
            raise ProxmoxMutationError("Invalid snapshot inventory")
        return result

    def list_vm_storage_images(self, *, node, storage, vmid):
        result = self._request_json("GET", f"/nodes/{node}/storage/{storage}/content?content=images&vmid={vmid}")
        if not isinstance(result, list) or any(not isinstance(row, dict) or not isinstance(row.get("volid"), str) for row in result):
            raise ProxmoxMutationError("Invalid VM volume inventory")
        return result

    def create_vm_from_image(self, *, node, config):
        return self._request_json("POST", f"/nodes/{node}/qemu", data=config)

    def convert_vm_to_template(self, *, node, vmid):
        return self._request_json("POST", f"/nodes/{node}/qemu/{vmid}/template", data={})

    def delete_vm_reviewed(self, *, node, vmid):
        return self._request_json("DELETE", f"/nodes/{node}/qemu/{vmid}",
                                  data={"purge": 0, "destroy-unreferenced-disks": 0})

    def clone_vm_reviewed(self, *, node, vmid, new_vmid, name, storage, disk_format, description):
        return self._request_json("POST", f"/nodes/{node}/qemu/{vmid}/clone", data={
            "newid": new_vmid, "name": name, "storage": storage, "format": disk_format,
            "full": 1, "description": description,
        })

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
        heartbeat: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.task_timeout_seconds
        polls: list[dict[str, Any]] = []
        while True:
            status = self.get_task_status(node=node, upid=upid)
            if heartbeat is not None:
                heartbeat()
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

    def shutdown_vm(self, *, node: str, vmid: int) -> str:
        """Request guest-aware shutdown without force-stop or reboot fallback."""

        data = self._request_json("POST", f"/nodes/{node}/qemu/{int(vmid)}/status/shutdown")
        upid = str(data or "").strip()
        if not upid:
            raise ProxmoxMutationError(
                "Proxmox shutdown did not return a UPID",
                details={"node": node, "vmid": int(vmid)},
            )
        return upid

    def get_vm_status(self, *, node: str, vmid: int) -> dict[str, Any]:
        data = self._request_json("GET", f"/nodes/{node}/qemu/{int(vmid)}/status/current")
        return dict(data) if isinstance(data, dict) else {}

    def get_vm_config(self, *, node: str, vmid: int) -> dict[str, Any]:
        data = self._request_json("GET", f"/nodes/{node}/qemu/{int(vmid)}/config")
        return dict(data) if isinstance(data, dict) else {}

    def get_vm_current_config(self, *, node: str, vmid: int) -> dict[str, Any]:
        data = self._request_json("GET", f"/nodes/{node}/qemu/{int(vmid)}/config?current=1")
        if not isinstance(data, dict):
            raise ProxmoxMutationError("Invalid current VM configuration response")
        return dict(data)

    def get_vm_pending(self, *, node: str, vmid: int) -> list[dict[str, Any]]:
        data = self._request_json("GET", f"/nodes/{node}/qemu/{int(vmid)}/pending")
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise ProxmoxMutationError("Invalid pending VM configuration response")
        return data

    def get_vm_permissions(self, *, vmid: int) -> set[str]:
        path = f"/vms/{int(vmid)}"
        data = self._request_json("GET", f"/access/permissions?path={path}")
        if not isinstance(data, dict) or not isinstance(data.get(path), dict):
            raise ProxmoxMutationError("Invalid VM permission response")
        return set(data[path])

    def get_storage_permissions(self, *, storage: str) -> set[str]:
        path = f"/storage/{storage}"
        data = self._request_json("GET", "/access/permissions?path=" + quote(path, safe="/"))
        if not isinstance(data, dict) or not isinstance(data.get(path), dict):
            raise ProxmoxMutationError("Invalid storage permission response")
        return set(data[path])

    def get_storage_configuration_permissions(self) -> set[str]:
        data = self._request_json('GET', '/access/permissions?path=/storage')
        if not isinstance(data, dict) or not isinstance(data.get('/storage'), dict):
            raise ProxmoxMutationError('Invalid storage configuration permissions')
        return set(data['/storage'])

    def list_storage_configurations(self):
        data = self._request_json('GET', '/storage')
        if not isinstance(data, list) or any(not isinstance(row, dict) or not isinstance(row.get('storage'), str) for row in data):
            raise ProxmoxMutationError('Invalid storage configuration list')
        return data

    def get_storage_configuration(self, *, storage):
        data = self._request_json('GET', '/storage/' + quote(storage, safe=''))
        if not isinstance(data, dict) or data.get('storage') != storage:
            raise ProxmoxMutationError('Invalid storage configuration target')
        return data

    def configure_directory_storage(self, *, node, storage, change, before):
        from app.operations.host_storage.domain import mutation_body
        body = mutation_body(change, node_id=node, storage_id=storage, before=before)
        method, path = ('POST', '/storage') if change.mode == 'create' else ('PUT', '/storage/' + quote(storage, safe=''))
        return self._request_json(method, path, data=body)

    def get_node_storages(self, *, node: str) -> list[dict[str, Any]]:
        data = self._request_json("GET", f"/nodes/{node}/storage")
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise ProxmoxMutationError("Invalid storage response")
        return data

    def get_backup_defaults(self, *, node: str, storage: str) -> dict[str, Any]:
        data = self._request_json("GET", f"/nodes/{node}/vzdump/defaults?storage={quote(storage, safe='')}")
        if not isinstance(data, dict) or not data:
            raise ProxmoxMutationError("Invalid backup defaults response")
        return data

    def list_vm_backups(self, *, node: str, storage: str, vmid: int) -> list[dict[str, Any]]:
        data = self._request_json("GET", f"/nodes/{node}/storage/{storage}/content?content=backup&vmid={vmid}")
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise ProxmoxMutationError("Invalid backup list response")
        return data

    def create_vm_backup(self, *, node: str, vmid: int, storage: str, operation_id: str) -> Any:
        from app.backups.contracts import backup_body
        return self._request_json("POST", f"/nodes/{node}/vzdump", data=backup_body(vmid, storage, operation_id))

    def get_backup_config(self, *, node: str, archive: str) -> str:
        data = self._request_json("GET", f"/nodes/{node}/vzdump/extractconfig?volume={quote(archive, safe='')}")
        if not isinstance(data, str) or not data or len(data.encode('utf-8')) > 262144:
            raise ProxmoxMutationError("Invalid backup configuration response")
        return data

    def restore_vm_backup(self, *, node: str, **kwargs) -> Any:
        from app.backups.contracts import restore_body
        return self._request_json("POST", f"/nodes/{node}/qemu", data=restore_body(**kwargs))

    def get_volume_info(self, *, node: str, storage: str, volume: str) -> dict[str, Any]:
        data = self._request_json("GET", f"/nodes/{node}/storage/{storage}/content/{quote(volume, safe='')}")
        if not isinstance(data, dict):
            raise ProxmoxMutationError("Invalid volume response")
        return data

    def resize_vm_disk_reviewed(self, *, node: str, vmid: int, size_gib: int, digest: str) -> Any:
        return self._request_json("PUT", f"/nodes/{node}/qemu/{vmid}/resize",
                                  data={"disk": "scsi0", "size": f"{size_gib}G", "digest": digest})

    def list_active_vm_tasks(self, *, node: str, vmid: int) -> list[dict[str, Any]]:
        data = self._request_json("GET", f"/nodes/{node}/tasks?source=active&vmid={int(vmid)}")
        if not isinstance(data, list):
            return []
        return [dict(item) for item in data if isinstance(item, dict)]

    def has_node_task_audit(self, *, node: str) -> bool:
        path = f"/nodes/{node}"
        data = self._request_json("GET", f"/access/permissions?path={path}")
        if not isinstance(data, dict):
            return False
        permissions = data.get(path)
        return isinstance(permissions, dict) and "Sys.Audit" in permissions

    def get_guest_network_interfaces(self, *, node: str, vmid: int) -> dict[str, Any]:
        data = self._request_json("GET", f"/nodes/{node}/qemu/{int(vmid)}/agent/network-get-interfaces")
        return dict(data) if isinstance(data, dict) else {"result": data}

    def exec_guest_command(self, *, node: str, vmid: int, command: str | Sequence[str]) -> int:
        if isinstance(command, str):
            command_payload: Any = {"command": command}
        else:
            command_parts = [str(part) for part in command if str(part).strip()]
            if not command_parts:
                raise ProxmoxMutationError("Proxmox guest exec command must not be empty", details={"node": node, "vmid": int(vmid)})
            command_payload = [("command", part) for part in command_parts]
        data = self._request_json(
            "POST",
            f"/nodes/{node}/qemu/{int(vmid)}/agent/exec",
            data=command_payload,
        )
        payload = dict(data) if isinstance(data, dict) else {}
        pid = payload.get("pid")
        if pid is None or str(pid).strip() == "":
            raise ProxmoxMutationError(
                "Proxmox guest exec did not return a pid",
                details={"node": node, "vmid": int(vmid), "command": command, "response": payload},
            )
        return int(pid)

    def get_guest_exec_status(self, *, node: str, vmid: int, pid: int) -> dict[str, Any]:
        data = self._request_json(
            "GET",
            f"/nodes/{node}/qemu/{int(vmid)}/agent/exec-status?pid={int(pid)}",
        )
        return dict(data) if isinstance(data, dict) else {}

    def wait_guest_exec(
        self,
        *,
        node: str,
        vmid: int,
        pid: int,
        sleep: Callable[[float], None] = time.sleep,
        heartbeat: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.task_timeout_seconds
        polls: list[dict[str, Any]] = []
        while True:
            status = self.get_guest_exec_status(node=node, vmid=vmid, pid=pid)
            if heartbeat is not None:
                heartbeat()
            polls.append(status)
            if status.get("exited") is True or str(status.get("exited") or "").lower() in {"1", "true", "yes"}:
                return {**status, "polls": polls}
            if "exitcode" in status:
                return {**status, "polls": polls}
            if time.monotonic() >= deadline:
                raise ProxmoxMutationError(
                    "Timed out waiting for Proxmox guest exec",
                    details={"node": node, "vmid": int(vmid), "pid": int(pid), "polls": polls},
                )
            sleep(self.task_poll_interval_seconds)


def get_default_proxmox_mutation_client() -> ProxmoxMutationClient:
    """Use the selected server credential; never fall back after managed failure."""
    from app.setup_integration.contracts import SetupError
    from app.setup_integration.runtime import managed_mutation_client, selected_credential

    try:
        selection = selected_credential()
        if selection is not None:
            return managed_mutation_client(selection)
    except SetupError as exc:
        raise ProxmoxMutationError(str(exc), details={"reason": exc.code}) from None
    return ProxmoxMutationClient.from_env()
