"""Allowlisted, observation-only durable recovery application services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from app.operations.core.domain import OperationActor
from app.operations.core.ports import OperationStorePort
from app.operations.recovery.domain import RecoveryLease, RecoveryLeaseLost
from app.operations.recovery.ports import RecoveryStorePort


SYSTEM_RECOVERY_ACTOR = OperationActor(
    user_id="system:operation-recovery",
    username="operation-recovery",
    role="system",
)


class VmStartRecoveryObservationPort(Protocol):
    def get_task_status(self, *, node: str, upid: str) -> dict[str, Any]: ...

    def get_vm_status(self, *, node: str, vmid: int) -> dict[str, Any]: ...


class VmStartRecoveryProjectionPort(Protocol):
    def record_terminal(
        self,
        *,
        operation_id: str,
        operation_status: str,
        target: Mapping[str, Any],
        task: Mapping[str, Any],
        observed_after: Mapping[str, Any],
    ) -> None: ...


@dataclass(frozen=True)
class RecoveryRunResult:
    operation_id: str
    outcome: str


class VmStartRecoveryHandler:
    """Resume only task/status observation for an already-dispatched VM Start."""

    def __init__(
        self,
        *,
        recovery: RecoveryStorePort,
        operations: OperationStorePort,
        observation_factory: Callable[[], VmStartRecoveryObservationPort],
        compatibility_projection: VmStartRecoveryProjectionPort | None = None,
        release_compatibility_lock: Callable[[str, str, str], bool] | None = None,
    ) -> None:
        self._recovery = recovery
        self._operations = operations
        self._observation_factory = observation_factory
        self._compatibility_projection = compatibility_projection
        self._release_compatibility_lock = release_compatibility_lock

    def handle(self, lease: RecoveryLease) -> RecoveryRunResult:
        operation = self._operations.get(lease.operation_id)
        if operation is None:
            raise RuntimeError(f"Operation is missing for recovery: {lease.operation_id}")
        details = {**dict(operation.details or {}), **dict(lease.item.details or {})}
        node_id = str(details.get("node_id") or dict(operation.details.get("target") or {}).get("node_id") or "").strip()
        try:
            vmid = int(details.get("vmid") or dict(operation.details.get("target") or {}).get("vmid"))
        except (TypeError, ValueError):
            vmid = 0
        upid = str(details.get("upid") or operation.details.get("proxmox_upid") or "").strip()
        if operation.status in {"succeeded", "failed"}:
            return self._complete_terminal_projection(
                lease,
                operation_status=operation.status,
                node_id=node_id,
                vmid=vmid,
                task=_mapping(details.get("task")),
                observed_after=_mapping(details.get("observed_after")),
            )
        if not node_id or vmid <= 0 or not upid:
            next_status = "needs_reconciliation" if operation.status in {"dispatching", "running", "verifying"} else None
            self._recovery.commit_observation(
                lease,
                next_status=next_status,
                event_type="recovery_missing_task_reference",
                stage="reconciliation",
                payload={"node_id": node_id, "vmid": vmid, "task_reference_present": bool(upid)},
                details_patch={"reconciliation_code": "VM_START_RECOVERY_TASK_REFERENCE_MISSING"},
                expected_statuses=[operation.status],
                actor=SYSTEM_RECOVERY_ACTOR,
                recovery_status="paused",
                error_code="VM_START_RECOVERY_TASK_REFERENCE_MISSING",
            )
            return RecoveryRunResult(operation_id=lease.operation_id, outcome="paused_missing_task_reference")

        client = self._observation_factory()
        task = dict(client.get_task_status(node=node_id, upid=upid) or {})
        task_status = str(task.get("status") or "").strip().lower()
        exitstatus = str(task.get("exitstatus") or "").strip().upper()
        if task_status != "stopped":
            self._recovery.commit_observation(
                lease,
                event_type="recovery_task_observed",
                stage="task_poll",
                payload={"task": _compact_task(task, node_id=node_id, upid=upid)},
                expected_statuses=[operation.status],
                actor=SYSTEM_RECOVERY_ACTOR,
                recovery_status="retry_wait",
                retry_delay_seconds=5,
                recovery_details_patch={"upid": upid, "last_task_status": task_status or "unknown"},
            )
            return RecoveryRunResult(operation_id=lease.operation_id, outcome="retry_task_running")

        observed = dict(client.get_vm_status(node=node_id, vmid=vmid) or {})
        observed_status = str(observed.get("status") or "").strip().lower()
        compact_task = _compact_task(task, node_id=node_id, upid=upid)
        compact_observed = _compact_vm_status(observed, node_id=node_id, vmid=vmid)

        if exitstatus == "OK" and observed_status == "running":
            lease = self._advance_to_verifying(
                lease,
                current_status=operation.status,
                task=compact_task,
                observed=compact_observed,
            )
            _, item = self._recovery.commit_observation(
                lease,
                next_status="succeeded",
                event_type="recovery_verification_succeeded",
                stage="post_check",
                payload={"task": compact_task, "observed_after": compact_observed},
                details_patch={"result_status": "completed", "recovered_after_restart": True},
                expected_statuses=["verifying"],
                actor=SYSTEM_RECOVERY_ACTOR,
                recovery_status="leased",
                recovery_details_patch={
                    "terminal_outcome": "succeeded",
                    "task": compact_task,
                    "observed_after": compact_observed,
                },
            )
            return self._complete_terminal_projection(
                RecoveryLease(item=item, token=lease.token),
                operation_status="succeeded",
                node_id=node_id,
                vmid=vmid,
                task=compact_task,
                observed_after=compact_observed,
            )

        if exitstatus and exitstatus != "OK" and observed_status == "stopped":
            _, item = self._recovery.commit_observation(
                lease,
                next_status="failed" if operation.status != "failed" else None,
                event_type="recovery_task_failed",
                stage="task_poll",
                payload={"task": compact_task, "observed_after": compact_observed},
                details_patch={"result_status": "failed", "recovered_after_restart": True},
                expected_statuses=[operation.status],
                actor=SYSTEM_RECOVERY_ACTOR,
                recovery_status="leased",
                error_code="VM_START_TASK_FAILED",
                recovery_details_patch={
                    "terminal_outcome": "failed",
                    "task": compact_task,
                    "observed_after": compact_observed,
                },
            )
            return self._complete_terminal_projection(
                RecoveryLease(item=item, token=lease.token),
                operation_status="failed",
                node_id=node_id,
                vmid=vmid,
                task=compact_task,
                observed_after=compact_observed,
            )

        next_status = "needs_reconciliation" if operation.status != "needs_reconciliation" else None
        self._recovery.commit_observation(
            lease,
            next_status=next_status,
            event_type="recovery_state_mismatch",
            stage="reconciliation",
            payload={"task": compact_task, "observed_after": compact_observed},
            details_patch={"reconciliation_code": "VM_START_RECOVERY_STATE_MISMATCH"},
            expected_statuses=[operation.status],
            actor=SYSTEM_RECOVERY_ACTOR,
            recovery_status="paused",
            error_code="VM_START_RECOVERY_STATE_MISMATCH",
        )
        return RecoveryRunResult(operation_id=lease.operation_id, outcome="paused_state_mismatch")

    def _advance_to_verifying(
        self,
        lease: RecoveryLease,
        *,
        current_status: str,
        task: Mapping[str, Any],
        observed: Mapping[str, Any],
    ) -> RecoveryLease:
        status = current_status
        if status == "dispatching":
            _, item = self._recovery.commit_observation(
                lease,
                next_status="running",
                event_type="recovery_dispatch_task_correlated",
                stage="task_poll",
                payload={"task": dict(task)},
                details_patch={"proxmox_upid": str(task.get("upid") or "")},
                expected_statuses=["dispatching"],
                actor=SYSTEM_RECOVERY_ACTOR,
                recovery_status="leased",
            )
            lease = RecoveryLease(item=item, token=lease.token)
            status = "running"
        if status in {"running", "needs_reconciliation"}:
            _, item = self._recovery.commit_observation(
                lease,
                next_status="verifying",
                event_type="recovery_task_and_state_observed",
                stage="post_check",
                payload={"task": dict(task), "observed_after": dict(observed)},
                expected_statuses=[status],
                actor=SYSTEM_RECOVERY_ACTOR,
                recovery_status="leased",
            )
            return RecoveryLease(item=item, token=lease.token)
        if status == "verifying":
            return lease
        raise RuntimeError(f"VM Start recovery cannot verify status: {status}")

    def _complete_terminal_projection(
        self,
        lease: RecoveryLease,
        *,
        operation_status: str,
        node_id: str,
        vmid: int,
        task: Mapping[str, Any],
        observed_after: Mapping[str, Any],
    ) -> RecoveryRunResult:
        if self._compatibility_projection is not None:
            self._compatibility_projection.record_terminal(
                operation_id=lease.operation_id,
                operation_status=operation_status,
                target={"node_id": node_id, "vmid": vmid},
                task=dict(task),
                observed_after=dict(observed_after),
            )
        self._recovery.commit_observation(
            lease,
            event_type="recovery_compatibility_projection_recorded",
            stage="post_check" if operation_status == "succeeded" else "task_poll",
            payload={"operation_status": operation_status},
            expected_statuses=[operation_status],
            actor=SYSTEM_RECOVERY_ACTOR,
            recovery_status="completed",
            release_target_lock=True,
        )
        self._release_file_lock(vmid, lease.operation_id)
        return RecoveryRunResult(operation_id=lease.operation_id, outcome=operation_status)

    def _release_file_lock(self, vmid: int, operation_id: str) -> None:
        if self._release_compatibility_lock is not None:
            self._release_compatibility_lock("proxmox_vm", f"vmid:{vmid}", operation_id)


class VmShutdownRecoveryHandler:
    """Resume only task/status observation for an already-dispatched shutdown."""

    def __init__(
        self,
        *,
        recovery: RecoveryStorePort,
        operations: OperationStorePort,
        observation_factory: Callable[[], VmStartRecoveryObservationPort],
        compatibility_projection: VmStartRecoveryProjectionPort | None = None,
        release_compatibility_lock: Callable[[str, str, str], bool] | None = None,
    ) -> None:
        self._recovery = recovery
        self._operations = operations
        self._observation_factory = observation_factory
        self._compatibility_projection = compatibility_projection
        self._release_compatibility_lock = release_compatibility_lock

    def handle(self, lease: RecoveryLease) -> RecoveryRunResult:
        operation = self._operations.get(lease.operation_id)
        if operation is None:
            raise RuntimeError(f"Operation is missing for recovery: {lease.operation_id}")
        details = {**dict(operation.details or {}), **dict(lease.item.details or {})}
        target = _mapping(operation.details.get("target"))
        node_id = str(details.get("node_id") or target.get("node_id") or "").strip()
        try:
            vmid = int(details.get("vmid") or target.get("vmid"))
        except (TypeError, ValueError):
            vmid = 0
        upid = str(details.get("upid") or operation.details.get("proxmox_upid") or "").strip()

        if operation.status in {"succeeded", "failed"}:
            return self._complete_terminal_projection(
                lease,
                operation_status=operation.status,
                node_id=node_id,
                vmid=vmid,
                task=_mapping(details.get("task")),
                observed_after=_mapping(details.get("observed_after")),
            )
        if not node_id or vmid <= 0 or not upid:
            next_status = "needs_reconciliation" if operation.status in {"dispatching", "running", "verifying"} else None
            self._recovery.commit_observation(
                lease,
                next_status=next_status,
                event_type="recovery_missing_task_reference",
                stage="reconciliation",
                payload={"node_id": node_id, "vmid": vmid, "task_reference_present": bool(upid)},
                details_patch={"reconciliation_code": "VM_SHUTDOWN_RECOVERY_TASK_REFERENCE_MISSING"},
                expected_statuses=[operation.status],
                actor=SYSTEM_RECOVERY_ACTOR,
                recovery_status="paused",
                error_code="VM_SHUTDOWN_RECOVERY_TASK_REFERENCE_MISSING",
            )
            return RecoveryRunResult(lease.operation_id, "paused_missing_task_reference")

        client = self._observation_factory()
        task = dict(client.get_task_status(node=node_id, upid=upid) or {})
        task_status = str(task.get("status") or "").strip().lower()
        if task_status != "stopped":
            self._recovery.commit_observation(
                lease,
                event_type="recovery_task_observed",
                stage="task_poll",
                payload={"task": _compact_task(task, node_id=node_id, upid=upid)},
                expected_statuses=[operation.status],
                actor=SYSTEM_RECOVERY_ACTOR,
                recovery_status="retry_wait",
                retry_delay_seconds=5,
                recovery_details_patch={"upid": upid, "last_task_status": task_status or "unknown"},
            )
            return RecoveryRunResult(lease.operation_id, "retry_task_running")

        observed = dict(client.get_vm_status(node=node_id, vmid=vmid) or {})
        compact_task = _compact_task(task, node_id=node_id, upid=upid)
        compact_observed = _compact_vm_status(observed, node_id=node_id, vmid=vmid)
        exitstatus = str(task.get("exitstatus") or "").strip().upper()
        observed_status = str(observed.get("status") or "").strip().lower()
        if exitstatus == "OK" and observed_status == "stopped":
            lease = self._advance_to_verifying(
                lease,
                current_status=operation.status,
                task=compact_task,
                observed=compact_observed,
            )
            _, item = self._recovery.commit_observation(
                lease,
                next_status="succeeded",
                event_type="recovery_verification_succeeded",
                stage="post_check",
                payload={"task": compact_task, "observed_after": compact_observed},
                details_patch={"result_status": "completed", "recovered_after_restart": True},
                expected_statuses=["verifying"],
                actor=SYSTEM_RECOVERY_ACTOR,
                recovery_status="leased",
                recovery_details_patch={
                    "terminal_outcome": "succeeded",
                    "task": compact_task,
                    "observed_after": compact_observed,
                },
            )
            return self._complete_terminal_projection(
                RecoveryLease(item=item, token=lease.token),
                operation_status="succeeded",
                node_id=node_id,
                vmid=vmid,
                task=compact_task,
                observed_after=compact_observed,
            )

        next_status = "needs_reconciliation" if operation.status != "needs_reconciliation" else None
        self._recovery.commit_observation(
            lease,
            next_status=next_status,
            event_type="recovery_state_mismatch",
            stage="reconciliation",
            payload={"task": compact_task, "observed_after": compact_observed},
            details_patch={"reconciliation_code": "VM_SHUTDOWN_RECOVERY_STATE_MISMATCH"},
            expected_statuses=[operation.status],
            actor=SYSTEM_RECOVERY_ACTOR,
            recovery_status="paused",
            error_code="VM_SHUTDOWN_RECOVERY_STATE_MISMATCH",
            recovery_details_patch={"task": compact_task, "observed_after": compact_observed},
        )
        return RecoveryRunResult(lease.operation_id, "paused_state_mismatch")

    def _advance_to_verifying(
        self,
        lease: RecoveryLease,
        *,
        current_status: str,
        task: Mapping[str, Any],
        observed: Mapping[str, Any],
    ) -> RecoveryLease:
        status = current_status
        if status == "dispatching":
            _, item = self._recovery.commit_observation(
                lease,
                next_status="running",
                event_type="recovery_dispatch_task_correlated",
                stage="task_poll",
                payload={"task": dict(task)},
                details_patch={"proxmox_upid": str(task.get("upid") or "")},
                expected_statuses=["dispatching"],
                actor=SYSTEM_RECOVERY_ACTOR,
                recovery_status="leased",
            )
            lease = RecoveryLease(item=item, token=lease.token)
            status = "running"
        if status in {"running", "needs_reconciliation"}:
            _, item = self._recovery.commit_observation(
                lease,
                next_status="verifying",
                event_type="recovery_task_and_state_observed",
                stage="post_check",
                payload={"task": dict(task), "observed_after": dict(observed)},
                expected_statuses=[status],
                actor=SYSTEM_RECOVERY_ACTOR,
                recovery_status="leased",
            )
            return RecoveryLease(item=item, token=lease.token)
        if status == "verifying":
            return lease
        raise RuntimeError(f"VM Shutdown recovery cannot verify status: {status}")

    def _complete_terminal_projection(
        self,
        lease: RecoveryLease,
        *,
        operation_status: str,
        node_id: str,
        vmid: int,
        task: Mapping[str, Any],
        observed_after: Mapping[str, Any],
    ) -> RecoveryRunResult:
        if self._compatibility_projection is not None:
            self._compatibility_projection.record_terminal(
                operation_id=lease.operation_id,
                operation_status=operation_status,
                target={"node_id": node_id, "vmid": vmid},
                task=dict(task),
                observed_after=dict(observed_after),
            )
        self._recovery.commit_observation(
            lease,
            event_type="recovery_compatibility_projection_recorded",
            stage="post_check",
            payload={"operation_status": operation_status},
            expected_statuses=[operation_status],
            actor=SYSTEM_RECOVERY_ACTOR,
            recovery_status="completed",
            release_target_lock=True,
        )
        if self._release_compatibility_lock is not None:
            self._release_compatibility_lock("proxmox_vm", f"vmid:{vmid}", lease.operation_id)
        return RecoveryRunResult(lease.operation_id, operation_status)


class OperationRecoveryRunner:
    """Claim a bounded batch and dispatch only allowlisted handlers."""

    def __init__(
        self,
        *,
        recovery: RecoveryStorePort,
        handlers: Mapping[str, Any],
        worker_id: str,
        lease_seconds: float = 60,
    ) -> None:
        self._recovery = recovery
        self._handlers = dict(handlers)
        self._worker_id = str(worker_id)
        self._lease_seconds = max(float(lease_seconds), 1.0)

    def run_once(self) -> list[RecoveryRunResult]:
        leases = self._recovery.claim_due(
            lease_owner=self._worker_id,
            lease_seconds=self._lease_seconds,
            limit=1,
        )
        results: list[RecoveryRunResult] = []
        for lease in leases:
            handler = self._handlers.get(lease.item.recovery_kind)
            if handler is None:
                self._recovery.commit_observation(
                    lease,
                    event_type="recovery_handler_unsupported",
                    stage="reconciliation",
                    payload={"recovery_kind": lease.item.recovery_kind},
                    actor=SYSTEM_RECOVERY_ACTOR,
                    recovery_status="paused",
                    error_code="OPERATION_RECOVERY_HANDLER_UNSUPPORTED",
                )
                results.append(RecoveryRunResult(lease.operation_id, "paused_unsupported"))
                continue
            try:
                results.append(handler.handle(lease))
            except RecoveryLeaseLost:
                results.append(RecoveryRunResult(lease.operation_id, "lease_lost"))
            except Exception as exc:
                try:
                    self._recovery.commit_observation(
                        lease,
                        event_type="recovery_observation_failed",
                        stage="reconciliation",
                        payload={"error_type": type(exc).__name__},
                        actor=SYSTEM_RECOVERY_ACTOR,
                        recovery_status="retry_wait",
                        retry_delay_seconds=30,
                        error_code="OPERATION_RECOVERY_OBSERVATION_FAILED",
                    )
                except RecoveryLeaseLost:
                    results.append(RecoveryRunResult(lease.operation_id, "lease_lost"))
                else:
                    results.append(RecoveryRunResult(lease.operation_id, "retry_observation_failed"))
        return results


def _compact_task(task: Mapping[str, Any], *, node_id: str, upid: str) -> dict[str, Any]:
    return {
        "node": node_id,
        "upid": upid,
        "status": str(task.get("status") or ""),
        "exitstatus": str(task.get("exitstatus") or ""),
    }


def _compact_vm_status(observed: Mapping[str, Any], *, node_id: str, vmid: int) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "vmid": vmid,
        "name": str(observed.get("name") or ""),
        "status": str(observed.get("status") or ""),
    }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}
