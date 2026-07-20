"""Proxmox observation and shared target-lock adapters for Guided `qm`."""

from __future__ import annotations

from typing import Any

from app.operations.guided_qm.ports import (
    GuidedQmObservationFailure,
    GuidedQmTargetLockBusy,
    GuidedQmTargetLockHandle,
)
from app.operations.target_lock import (
    TargetOperationLockBusy,
    acquire_target_operation_lock,
    get_target_operation_lock,
    release_target_operation_lock,
    release_target_operation_lock_for_owner,
)
from app.proxmox.client import ProxmoxMutationError


class ProxmoxGuidedQmObservationAdapter:
    def __init__(self, client: Any) -> None:
        self._client = client

    def get_vm_config(self, *, node: str, vmid: int) -> dict[str, Any]:
        try:
            return self._client.get_vm_config(node=node, vmid=vmid)
        except ProxmoxMutationError as exc:
            raise GuidedQmObservationFailure(str(exc)) from exc
        except Exception as exc:
            raise GuidedQmObservationFailure("Proxmox VM config observation failed") from exc

    def has_node_task_audit(self, *, node: str) -> bool:
        try:
            return self._client.has_node_task_audit(node=node) is True
        except ProxmoxMutationError as exc:
            raise GuidedQmObservationFailure(str(exc)) from exc
        except Exception as exc:
            raise GuidedQmObservationFailure("Proxmox permission observation failed") from exc

    def list_active_vm_tasks(self, *, node: str, vmid: int) -> list[dict[str, Any]]:
        try:
            return self._client.list_active_vm_tasks(node=node, vmid=vmid)
        except ProxmoxMutationError as exc:
            raise GuidedQmObservationFailure(str(exc)) from exc
        except Exception as exc:
            raise GuidedQmObservationFailure("Proxmox active task observation failed") from exc


class SharedGuidedQmTargetLockAdapter:
    def acquire(self, target_type: str, target_id: str, operation_id: str) -> GuidedQmTargetLockHandle:
        try:
            handle = acquire_target_operation_lock(target_type, target_id, operation_id)
        except TargetOperationLockBusy as exc:
            raise GuidedQmTargetLockBusy(exc.to_dict()) from exc
        return GuidedQmTargetLockHandle(token=handle, evidence=handle.to_dict())

    def current(self, target_type: str, target_id: str) -> dict[str, Any] | None:
        return get_target_operation_lock(target_type, target_id)

    def release(self, handle: GuidedQmTargetLockHandle) -> None:
        release_target_operation_lock(handle.token)

    def release_owned(self, target_type: str, target_id: str, operation_id: str) -> bool:
        return release_target_operation_lock_for_owner(target_type, target_id, operation_id)
