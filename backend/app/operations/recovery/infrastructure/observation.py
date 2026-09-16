"""Capability-restricted Proxmox adapter for recovery observation."""

from __future__ import annotations

from typing import Any


class ProxmoxRecoveryObservationAdapter:
    """Expose only read/observation methods to recovery handlers.

    The wrapped client may also support mutation for foreground workflows, but
    this adapter intentionally has no mutation methods. Recovery code therefore
    cannot redispatch Create, Start, Shutdown, or a shell command by accident.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def get_task_status(self, *, node: str, upid: str) -> dict[str, Any]:
        return dict(self._client.get_task_status(node=node, upid=upid) or {})

    def get_vm_status(self, *, node: str, vmid: int) -> dict[str, Any]:
        return dict(self._client.get_vm_status(node=node, vmid=vmid) or {})

    def get_vm_config(self, *, node: str, vmid: int) -> dict[str, Any]:
        return dict(self._client.get_vm_config(node=node, vmid=vmid) or {})

    def has_node_task_audit(self, *, node: str) -> bool:
        return self._client.has_node_task_audit(node=node) is True

    def list_active_vm_tasks(self, *, node: str, vmid: int) -> list[dict[str, Any]]:
        return [dict(task) for task in (self._client.list_active_vm_tasks(node=node, vmid=vmid) or [])]


__all__ = ["ProxmoxRecoveryObservationAdapter"]
