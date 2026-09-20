"""Allowlisted, observation-only durable recovery application services."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol

from app.operations.locks.binding import expected_lock_count, lock_references
from app.operations.core.domain import OperationActor, OperationSnapshot, verify_event_chain
from app.operations.core.ports import OperationStorePort
from app.operations.recovery.domain import (
    PRE_DISPATCH_RECOVERY_CONTRACT,
    RecoveryLease,
    RecoveryLeaseBusy,
    RecoveryLeaseLost,
    RecoveryNotFound,
    RecoveryOperationConflict,
    RecoverySpec,
    is_pre_dispatch_terminal_no_effect,
)
from app.operations.recovery.ports import RecoveryStorePort
from app.operations.core.evidence import compact_proxmox_task, compact_proxmox_vm_status


SYSTEM_RECOVERY_ACTOR = OperationActor(
    user_id="system:operation-recovery",
    username="operation-recovery",
    role="system",
)
_OPERATOR_OBSERVE_LEDGER_LIMIT = 64


def _observe_key_digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def recovery_error_semantics(error_code: str) -> str | None:
    """Classify whether a public observation is ineligible or unavailable."""

    normalized = str(error_code or "").strip().upper()
    if not normalized:
        return None
    ineligible_codes = {
        "OPERATION_RECOVERY_BINDING_MISMATCH",
        "OPERATION_RECOVERY_HANDLER_UNSUPPORTED",
        "PROXMOX_CREATE_RECOVERY_ARTIFACT_MISSING",
        "PROXMOX_CREATE_RECOVERY_ARTIFACT_BINDING_INVALID",
        "PROXMOX_CREATE_RECOVERY_ARTIFACT_PROJECTION_INVALID",
        "PROXMOX_CREATE_RECOVERY_BINDING_MISMATCH",
        "PROXMOX_CREATE_RECOVERY_OPERATION_STATE_INVALID",
        "PROXMOX_CREATE_RECOVERY_MANUAL_DECISION_REQUIRED",
        "PROXMOX_CREATE_RECOVERY_TARGET_INVALID",
        "VM_START_RECOVERY_TASK_REFERENCE_MISSING",
        "VM_SHUTDOWN_RECOVERY_TASK_REFERENCE_MISSING",
        "GUIDED_QM_ATTESTATION_REQUIRED",
        "GUIDED_QM_EXPIRY_RECONCILIATION_REQUIRED",
        "GUIDED_QM_LATE_ATTESTATION_MANUAL_VERIFICATION_REQUIRED",
        "GUIDED_QM_PROVISIONAL_LOCK_MISSING",
        "GUIDED_QM_RECOVERY_BINDING_MISMATCH",
        "GUIDED_QM_RECOVERY_STATE_INELIGIBLE",
        "GUIDED_QM_TARGET_LOCK_LOST",
    }
    if normalized in ineligible_codes:
        return "ineligible"
    unavailable_markers = (
        "OBSERVATION_UNAVAILABLE",
        "OBSERVATION_FAILED",
        "PROJECTION_FAILED",
        "PROJECTION_UNAVAILABLE",
        "FILE_GUARD_CLEANUP_FAILED",
        "PERSISTENCE_UNAVAILABLE",
        "RECOVERY_UNAVAILABLE",
        "RETRY_EXHAUSTED",
        "VERIFICATION_UNAVAILABLE",
    )
    if any(marker in normalized for marker in unavailable_markers):
        return "unavailable"
    return None


def _guided_unissued_plan_proven(
    operation: OperationSnapshot,
    events: list[Any],
) -> bool:
    """Accept only a checksum-backed Guided plan whose command was never exposed."""

    if (
        operation.operation_type != "guided_qm_vm_unlock"
        or operation.execution_mode != "guided_manual"
        or operation.status != "planned"
        or operation.details.get("recovery_contract") != PRE_DISPATCH_RECOVERY_CONTRACT
        or operation.details.get("instruction_exposed") is not False
        or operation.details.get("instruction_bundle") is not None
        or not events
        or not verify_event_chain(events)
        or str(getattr(events[-1], "checksum", "")) != operation.last_event_checksum
    ):
        return False
    created = events[0]
    if (
        str(getattr(created, "event_type", "")) != "operation_created"
        or str(getattr(created, "to_status", "")) != "planned"
        or dict(getattr(created, "payload", {}) or {}).get("instruction_exposed") is not False
    ):
        return False
    return all(
        str(getattr(event, "event_type", "")) != "guided_instruction_issued"
        and dict(getattr(event, "payload", {}) or {}).get("instruction_exposed") is not True
        for event in events
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
        mutation_dispatched: bool = True,
    ) -> None: ...

    def record_terminal_in_transaction(
        self,
        transaction: Any,
        *,
        operation_id: str,
        operation_status: str,
        target: Mapping[str, Any],
        task: Mapping[str, Any],
        observed_after: Mapping[str, Any],
        mutation_dispatched: bool = True,
    ) -> None: ...


@dataclass(frozen=True)
class RecoveryRunResult:
    operation_id: str
    outcome: str


class RecoveryBindingError(RuntimeError):
    """Raised when a recovery item is not bound to its exact Operation target."""


def _validate_recovery_binding(
    lease: RecoveryLease,
    operation: OperationSnapshot,
    *,
    recovery_kind: str,
    operation_type: str,
    execution_mode: str,
    target_lock_reader: Callable[[str, str], Mapping[str, Any] | None] | None,
) -> None:
    details = dict(lease.item.details or {})
    if lease.item.recovery_kind != recovery_kind:
        raise RecoveryBindingError("recovery_kind_mismatch")
    if operation.operation_type != operation_type:
        raise RecoveryBindingError("operation_type_mismatch")
    if operation.execution_mode != execution_mode:
        raise RecoveryBindingError("execution_mode_mismatch")
    declared_operation_type = str(details.get("operation_type") or operation.operation_type).strip()
    declared_execution_mode = str(details.get("execution_mode") or operation.execution_mode).strip()
    if declared_operation_type != operation.operation_type:
        raise RecoveryBindingError("recovery_operation_type_mismatch")
    if declared_execution_mode != operation.execution_mode:
        raise RecoveryBindingError("recovery_execution_mode_mismatch")
    if operation.target_type != "proxmox_vm" or not operation.target_id.startswith("vmid:"):
        raise RecoveryBindingError("operation_target_invalid")
    declared_type = str(details.get("target_type") or operation.target_type).strip()
    declared_id = str(details.get("target_id") or operation.target_id).strip()
    if declared_type != operation.target_type or declared_id != operation.target_id:
        raise RecoveryBindingError("recovery_target_mismatch")
    try:
        declared_vmid = int(details.get("vmid") or operation.target_id.split(":", 1)[1])
    except (TypeError, ValueError, IndexError) as exc:
        raise RecoveryBindingError("recovery_vmid_invalid") from exc
    if operation.target_id != f"vmid:{declared_vmid}":
        raise RecoveryBindingError("recovery_vmid_mismatch")
    operation_target = _mapping(operation.details.get("target"))
    operation_node_id = str(operation_target.get("node_id") or "").strip()
    declared_node_id = str(details.get("node_id") or "").strip()
    if not operation_node_id or declared_node_id != operation_node_id:
        raise RecoveryBindingError("recovery_node_mismatch")
    operation_upid = str(operation.details.get("proxmox_upid") or "").strip()
    recovery_upid = str(details.get("upid") or "").strip()
    if operation_upid and not compact_proxmox_task({}, upid=operation_upid).get("upid"):
        raise RecoveryBindingError("operation_task_reference_invalid")
    if recovery_upid and not compact_proxmox_task({}, upid=recovery_upid).get("upid"):
        raise RecoveryBindingError("recovery_task_reference_invalid")
    if operation_upid != recovery_upid:
        raise RecoveryBindingError("recovery_task_reference_mismatch")
    if target_lock_reader is None:
        raise RecoveryBindingError("target_lock_reader_unavailable")
    lock = target_lock_reader(operation.target_type, operation.target_id)
    if not lock or str(lock.get("owner_id") or "") != operation.operation_id:
        raise RecoveryBindingError("target_lock_owner_mismatch")
    durable = _mapping(lock.get("durable"))
    if not durable:
        raise RecoveryBindingError("durable_target_lock_missing")
    if str(durable.get("operation_type") or "") != operation.operation_type:
        raise RecoveryBindingError("target_lock_operation_type_mismatch")
    if str(durable.get("owner_id") or "") != operation.operation_id:
        raise RecoveryBindingError("durable_target_lock_owner_mismatch")
    try:
        durable_vmid = int(durable.get("vmid") or 0)
    except (TypeError, ValueError) as exc:
        raise RecoveryBindingError("durable_target_lock_vmid_mismatch") from exc
    if durable_vmid != declared_vmid:
        raise RecoveryBindingError("durable_target_lock_vmid_mismatch")
    expected_cluster_id = str(details.get("cluster_id") or "").strip()
    observed_cluster_id = str(durable.get("cluster_id") or "").strip()
    if not expected_cluster_id or observed_cluster_id != expected_cluster_id:
        raise RecoveryBindingError("target_lock_cluster_mismatch")
    expected_lock_id = str(details.get("target_lock_id") or "").strip()
    durable_lock_id = str(durable.get("operation_lock_id") or "").strip()
    wrapper_lock_id = str(lock.get("lock_id") or "").strip()
    if not expected_lock_id or not durable_lock_id or not wrapper_lock_id:
        raise RecoveryBindingError("target_lock_id_missing")
    if durable_lock_id != expected_lock_id:
        raise RecoveryBindingError("target_lock_id_mismatch")
    if wrapper_lock_id != durable_lock_id:
        raise RecoveryBindingError("target_lock_identity_mismatch")
    if expected_lock_count(operation.operation_type) == 2:
        references = lock_references(operation_type=operation.operation_type, target_id=operation.target_id,
            operation_details=operation.details, recovery_details=details)
        if len(references) != expected_lock_count(operation.operation_type):
            raise RecoveryBindingError("related_target_lock_binding_mismatch")
        for reference in references[1:]:
            related = target_lock_reader("proxmox_vm", f"vmid:{reference['vmid']}")
            durable_related = _mapping(related.get("durable")) if related else {}
            if (not related or related.get("owner_id") != operation.operation_id
                    or related.get("lock_id") != reference["lock_id"]
                    or durable_related.get("operation_lock_id") != reference["lock_id"]
                    or durable_related.get("owner_id") != operation.operation_id
                    or durable_related.get("operation_type") != operation.operation_type
                    or durable_related.get("cluster_id") != expected_cluster_id
                    or durable_related.get("vmid") != reference["vmid"]):
                raise RecoveryBindingError("related_target_lock_identity_mismatch")



def _pause_binding_failure(
    recovery: RecoveryStorePort,
    lease: RecoveryLease,
    operation: OperationSnapshot,
    exc: RecoveryBindingError,
) -> RecoveryRunResult:
    reason = str(exc)
    invalid_task_reference = reason in {
        "operation_task_reference_invalid",
        "recovery_task_reference_invalid",
    }
    next_status = (
        "needs_reconciliation"
        if operation.status in {"dispatching", "running", "verifying"}
        else None
    )
    recovery.commit_observation(
        lease,
        next_status=next_status,
        event_type="recovery_binding_mismatch",
        stage="reconciliation",
        payload={"reason": reason},
        details_patch={
            "reconciliation_code": "OPERATION_RECOVERY_BINDING_MISMATCH",
            **({"proxmox_upid": ""} if invalid_task_reference else {}),
        },
        expected_statuses=[operation.status],
        actor=SYSTEM_RECOVERY_ACTOR,
        recovery_status="paused",
        error_code="OPERATION_RECOVERY_BINDING_MISMATCH",
        recovery_details_patch={
            "binding_error": reason,
            **({"upid": ""} if invalid_task_reference else {}),
        },
        require_exact_reconciliation_lock=False,
    )
    return RecoveryRunResult(lease.operation_id, "paused_binding_mismatch")


def _retry_state(lease: RecoveryLease, *, max_attempts: int) -> tuple[str, float]:
    if lease.item.attempt_count >= max(int(max_attempts), 1):
        return "paused", 0
    return "retry_wait", 5


class VmStartRecoveryHandler:
    """Resume only task/status observation for an already-dispatched VM Start."""

    def __init__(
        self,
        *,
        recovery: RecoveryStorePort,
        operations: OperationStorePort,
        observation_factory: Callable[[], VmStartRecoveryObservationPort],
        compatibility_projection: VmStartRecoveryProjectionPort | None = None,

        target_lock_reader: Callable[[str, str], Mapping[str, Any] | None] | None = None,
        max_attempts: int = 5,
    ) -> None:
        self._recovery = recovery
        self._operations = operations
        self._observation_factory = observation_factory
        self._compatibility_projection = compatibility_projection

        self._target_lock_reader = target_lock_reader
        self._max_attempts = max(int(max_attempts), 1)

    def handle(self, lease: RecoveryLease) -> RecoveryRunResult:
        operation = self._operations.get(lease.operation_id)
        if operation is None:
            raise RuntimeError(f"Operation is missing for recovery: {lease.operation_id}")
        try:
            _validate_recovery_binding(
                lease,
                operation,
                recovery_kind="vm_start_observation",
                operation_type="vm_start",
                execution_mode="managed_api",
                target_lock_reader=self._target_lock_reader,
            )
        except RecoveryBindingError as exc:
            return _pause_binding_failure(self._recovery, lease, operation, exc)
        details = {**dict(operation.details or {}), **dict(lease.item.details or {})}
        node_id = str(details.get("node_id") or dict(operation.details.get("target") or {}).get("node_id") or "").strip()
        try:
            vmid = int(details.get("vmid") or dict(operation.details.get("target") or {}).get("vmid"))
        except (TypeError, ValueError):
            vmid = 0
        upid = str(details.get("upid") or operation.details.get("proxmox_upid") or "").strip()
        terminal_no_effect = is_pre_dispatch_terminal_no_effect(
            operation_type=operation.operation_type,
            status=operation.status,
            details=operation.details,
        ) and all(
            lease.item.details.get(field) == operation.details.get(field)
            for field in (
                "pre_dispatch_terminal_no_effect",
                "mutation_dispatched",
                "pre_dispatch_terminal_reason",
                "target_lock_id",
                "cluster_id",
            )
        )
        if details.get("phase") == "pre_dispatch" and not upid and (
            operation.status in {"planned", "dispatching"} or terminal_no_effect
        ):
            return self._complete_pre_dispatch(lease, operation_status=operation.status, node_id=node_id, vmid=vmid)
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
        compact_task = _compact_task(task, node_id=node_id, upid=upid)
        task_status = str(compact_task.get("status") or "")
        exitstatus = str(compact_task.get("exitstatus") or "")
        if task_status != "stopped":
            retry_status, retry_delay = _retry_state(lease, max_attempts=self._max_attempts)
            self._recovery.commit_observation(
                lease,
                event_type="recovery_task_observed",
                stage="task_poll",
                payload={"task": compact_task},
                expected_statuses=[operation.status],
                actor=SYSTEM_RECOVERY_ACTOR,
                recovery_status=retry_status,
                retry_delay_seconds=retry_delay,
                error_code=("OPERATION_RECOVERY_RETRY_EXHAUSTED" if retry_status == "paused" else None),
                recovery_details_patch={"upid": upid, "last_task_status": task_status or "unknown"},
            )
            outcome = "paused_retry_exhausted" if retry_status == "paused" else "retry_task_running"
            return RecoveryRunResult(operation_id=lease.operation_id, outcome=outcome)

        observed = dict(client.get_vm_status(node=node_id, vmid=vmid) or {})
        compact_observed = _compact_vm_status(observed, node_id=node_id, vmid=vmid)
        observed_status = str(compact_observed.get("status") or "")

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
        projector = None
        if self._compatibility_projection is not None:
            projector = lambda transaction: self._compatibility_projection.record_terminal_in_transaction(
                transaction,
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
            projector=projector,
        )
        return RecoveryRunResult(operation_id=lease.operation_id, outcome=operation_status)

    def _complete_pre_dispatch(
        self,
        lease: RecoveryLease,
        *,
        operation_status: str,
        node_id: str,
        vmid: int,
    ) -> RecoveryRunResult:
        terminal_status = operation_status in {"failed", "blocked"}
        completed_status = operation_status if terminal_status else "failed"
        projector = None
        if self._compatibility_projection is not None:
            projector = lambda transaction: self._compatibility_projection.record_terminal_in_transaction(
                transaction,
                operation_id=lease.operation_id,
                operation_status=completed_status,
                target={"node_id": node_id, "vmid": vmid},
                task={},
                observed_after={},
                mutation_dispatched=False,
            )
        self._recovery.commit_observation(
            lease,
            next_status=None if terminal_status else "failed",
            event_type="recovery_pre_dispatch_closed",
            stage="reconciliation",
            payload={
                "mutation_dispatched": False,
                "terminal_status_preserved": terminal_status,
                "terminal_outcome": completed_status,
            },
            details_patch={"result_status": completed_status, "recovered_pre_dispatch": True},
            expected_statuses=[operation_status],
            actor=SYSTEM_RECOVERY_ACTOR,
            recovery_status="completed",
            recovery_details_patch={"terminal_outcome": completed_status},
            release_target_lock=True,
            projector=projector,
        )
        return RecoveryRunResult(
            lease.operation_id,
            completed_status if terminal_status else "failed_pre_dispatch",
        )




class VmShutdownRecoveryHandler:
    """Resume only task/status observation for an already-dispatched shutdown."""

    def __init__(
        self,
        *,
        recovery: RecoveryStorePort,
        operations: OperationStorePort,
        observation_factory: Callable[[], VmStartRecoveryObservationPort],
        compatibility_projection: VmStartRecoveryProjectionPort | None = None,

        target_lock_reader: Callable[[str, str], Mapping[str, Any] | None] | None = None,
        max_attempts: int = 5,
    ) -> None:
        self._recovery = recovery
        self._operations = operations
        self._observation_factory = observation_factory
        self._compatibility_projection = compatibility_projection

        self._target_lock_reader = target_lock_reader
        self._max_attempts = max(int(max_attempts), 1)

    def handle(self, lease: RecoveryLease) -> RecoveryRunResult:
        operation = self._operations.get(lease.operation_id)
        if operation is None:
            raise RuntimeError(f"Operation is missing for recovery: {lease.operation_id}")
        try:
            _validate_recovery_binding(
                lease,
                operation,
                recovery_kind="vm_shutdown_observation",
                operation_type="vm_shutdown",
                execution_mode="managed_api",
                target_lock_reader=self._target_lock_reader,
            )
        except RecoveryBindingError as exc:
            return _pause_binding_failure(self._recovery, lease, operation, exc)
        details = {**dict(operation.details or {}), **dict(lease.item.details or {})}
        target = _mapping(operation.details.get("target"))
        node_id = str(details.get("node_id") or target.get("node_id") or "").strip()
        try:
            vmid = int(details.get("vmid") or target.get("vmid"))
        except (TypeError, ValueError):
            vmid = 0
        upid = str(details.get("upid") or operation.details.get("proxmox_upid") or "").strip()

        terminal_no_effect = is_pre_dispatch_terminal_no_effect(
            operation_type=operation.operation_type,
            status=operation.status,
            details=operation.details,
        ) and all(
            lease.item.details.get(field) == operation.details.get(field)
            for field in (
                "pre_dispatch_terminal_no_effect",
                "mutation_dispatched",
                "pre_dispatch_terminal_reason",
                "target_lock_id",
                "cluster_id",
            )
        )
        if details.get("phase") == "pre_dispatch" and not upid and (
            operation.status in {"planned", "dispatching"} or terminal_no_effect
        ):
            return self._complete_pre_dispatch(lease, operation_status=operation.status, node_id=node_id, vmid=vmid)

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
        compact_task = _compact_task(task, node_id=node_id, upid=upid)
        task_status = str(compact_task.get("status") or "")
        if task_status != "stopped":
            retry_status, retry_delay = _retry_state(lease, max_attempts=self._max_attempts)
            self._recovery.commit_observation(
                lease,
                event_type="recovery_task_observed",
                stage="task_poll",
                payload={"task": compact_task},
                expected_statuses=[operation.status],
                actor=SYSTEM_RECOVERY_ACTOR,
                recovery_status=retry_status,
                retry_delay_seconds=retry_delay,
                error_code=("OPERATION_RECOVERY_RETRY_EXHAUSTED" if retry_status == "paused" else None),
                recovery_details_patch={"upid": upid, "last_task_status": task_status or "unknown"},
            )
            outcome = "paused_retry_exhausted" if retry_status == "paused" else "retry_task_running"
            return RecoveryRunResult(lease.operation_id, outcome)

        observed = dict(client.get_vm_status(node=node_id, vmid=vmid) or {})
        compact_observed = _compact_vm_status(observed, node_id=node_id, vmid=vmid)
        exitstatus = str(compact_task.get("exitstatus") or "")
        observed_status = str(compact_observed.get("status") or "")
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
        projector = None
        if self._compatibility_projection is not None:
            projector = lambda transaction: self._compatibility_projection.record_terminal_in_transaction(
                transaction,
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
            projector=projector,
        )
        return RecoveryRunResult(lease.operation_id, operation_status)

    def _complete_pre_dispatch(
        self,
        lease: RecoveryLease,
        *,
        operation_status: str,
        node_id: str,
        vmid: int,
    ) -> RecoveryRunResult:
        terminal_status = operation_status in {"failed", "blocked"}
        completed_status = operation_status if terminal_status else "failed"
        projector = None
        if self._compatibility_projection is not None:
            projector = lambda transaction: self._compatibility_projection.record_terminal_in_transaction(
                transaction,
                operation_id=lease.operation_id,
                operation_status=completed_status,
                target={"node_id": node_id, "vmid": vmid},
                task={},
                observed_after={},
                mutation_dispatched=False,
            )
        self._recovery.commit_observation(
            lease,
            next_status=None if terminal_status else "failed",
            event_type="recovery_pre_dispatch_closed",
            stage="reconciliation",
            payload={
                "mutation_dispatched": False,
                "terminal_status_preserved": terminal_status,
                "terminal_outcome": completed_status,
            },
            details_patch={"result_status": completed_status, "recovered_pre_dispatch": True},
            expected_statuses=[operation_status],
            actor=SYSTEM_RECOVERY_ACTOR,
            recovery_status="completed",
            recovery_details_patch={"terminal_outcome": completed_status},
            release_target_lock=True,
            projector=projector,
        )
        return RecoveryRunResult(
            lease.operation_id,
            completed_status if terminal_status else "failed_pre_dispatch",
        )




class OperationRecoveryRunner:
    """Claim a bounded batch and dispatch only allowlisted handlers."""

    def __init__(
        self,
        *,
        recovery: RecoveryStorePort,
        handlers: Mapping[str, Any],
        worker_id: str,
        lease_seconds: float = 60,
        max_attempts: int = 5,
    ) -> None:
        self._recovery = recovery
        self._handlers = dict(handlers)
        self._worker_id = str(worker_id)
        self._lease_seconds = max(float(lease_seconds), 1.0)
        self._max_attempts = max(int(max_attempts), 1)

    def run_once(self) -> list[RecoveryRunResult]:
        leases = self._recovery.claim_due(
            lease_owner=self._worker_id,
            lease_seconds=self._lease_seconds,
            limit=1,
        )
        return [self.run_claimed(lease) for lease in leases]

    def run_claimed(self, lease: RecoveryLease) -> RecoveryRunResult:
        """Dispatch one already-fenced lease through the same allowlist."""

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
            return RecoveryRunResult(lease.operation_id, "paused_unsupported")
        try:
            return handler.handle(lease)
        except RecoveryLeaseLost:
            return RecoveryRunResult(lease.operation_id, "lease_lost")
        except Exception as exc:
            try:
                retry_status = (
                    "paused"
                    if lease.item.attempt_count >= self._max_attempts
                    else "retry_wait"
                )
                self._recovery.commit_observation(
                    lease,
                    event_type="recovery_observation_failed",
                    stage="reconciliation",
                    payload={"error_type": type(exc).__name__},
                    actor=SYSTEM_RECOVERY_ACTOR,
                    recovery_status=retry_status,
                    retry_delay_seconds=30 if retry_status == "retry_wait" else 0,
                    error_code=(
                        "OPERATION_RECOVERY_RETRY_EXHAUSTED"
                        if retry_status == "paused"
                        else "OPERATION_RECOVERY_OBSERVATION_FAILED"
                    ),
                )
            except RecoveryLeaseLost:
                return RecoveryRunResult(lease.operation_id, "lease_lost")
            outcome = (
                "paused_retry_exhausted"
                if retry_status == "paused"
                else "retry_observation_failed"
            )
            return RecoveryRunResult(lease.operation_id, outcome)

    def supports(self, recovery_kind: str) -> bool:
        return str(recovery_kind) in self._handlers


class OperationRecoveryObserveError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = str(code)
        self.message = str(message)
        self.status_code = int(status_code)
        self.details = dict(details or {})
        super().__init__(self.message)

    def to_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.details}


class OperationRecoveryCoordinator:
    """Operator-triggered, GET-only observation for one exact recovery item."""

    def __init__(
        self,
        *,
        recovery: RecoveryStorePort,
        operations: OperationStorePort,
        runner: OperationRecoveryRunner,
        lock_reader: Callable[[str, str], Mapping[str, Any] | None],
        worker_id: str,
        lease_seconds: float = 60,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._recovery = recovery
        self._operations = operations
        self._runner = runner
        self._lock_reader = lock_reader
        self._worker_id = str(worker_id).strip() or "operator-recovery-observer"
        self._lease_seconds = max(float(lease_seconds), 1.0)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def observe(
        self,
        operation_id: str,
        *,
        actor: OperationActor,
        expected_version: int,
        expected_checksum: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        normalized_id = str(operation_id).strip()
        request_key = str(idempotency_key).strip()
        checksum = str(expected_checksum).strip()
        if actor.role not in {"operator", "admin"}:
            raise OperationRecoveryObserveError(
                "OPERATION_RECOVERY_OPERATOR_REQUIRED",
                "Operator or admin authority is required to request recovery observation",
                status_code=403,
            )
        if (
            not normalized_id
            or not request_key
            or len(request_key) > 160
            or isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
            or expected_version < 1
            or not checksum
            or len(checksum) > 160
        ):
            raise OperationRecoveryObserveError(
                "INVALID_OPERATION_RECOVERY_OBSERVE_REQUEST",
                "operation id, expected version/checksum, and idempotency key are required",
                status_code=422,
            )
        request_key_digest = _observe_key_digest(request_key)
        try:
            operation = self._operations.get(normalized_id)
        except Exception as exc:
            raise self._unavailable(normalized_id) from exc
        if operation is None:
            raise OperationRecoveryObserveError(
                "OPERATION_NOT_FOUND",
                "Operation was not found",
                status_code=404,
                details={"operation_id": normalized_id},
            )
        try:
            item = self._recovery.get(normalized_id)
            observe_ledger: list[dict[str, Any]] | None = None
            same_request = self._same_observe_request(
                item,
                idempotency_key_digest=request_key_digest,
                expected_version=int(expected_version),
                expected_checksum=checksum,
            )
            if same_request and item is not None:
                if item.status == "leased" and self._lease_is_live(item.lease_expires_at):
                    raise OperationRecoveryObserveError(
                        "OPERATION_RECOVERY_OBSERVATION_IN_PROGRESS",
                        "The same recovery observation request already has a live lease",
                        status_code=409,
                        details={
                            "operation_id": normalized_id,
                            "idempotent_replay": True,
                            "recovery_status": item.status,
                        },
                    )
                if item.status != "leased":
                    return self._replay_observe_result(normalized_id, operation=operation, item=item)
                lease = self._recovery.claim_operation(
                    normalized_id,
                    lease_owner=self._worker_id,
                    lease_seconds=self._lease_seconds,
                    expected_operation_version=operation.version,
                    expected_operation_checksum=operation.last_event_checksum,
                )
                result = self._runner.run_claimed(lease)
                return self._result_or_error(
                    normalized_id,
                    result,
                    idempotent_replay=True,
                )
            if item is not None and recovery_error_semantics(item.last_error_code) == "ineligible":
                raise OperationRecoveryObserveError(
                    "OPERATION_RECOVERY_INELIGIBLE",
                    "Recovery observation cannot proceed because manual authority or binding repair is required",
                    status_code=409,
                    details={
                        "operation_id": normalized_id,
                        "recovery_error_code": str(item.last_error_code or ""),
                    },
                )
            if operation.version != int(expected_version) or operation.last_event_checksum != checksum:
                raise self._conflict(normalized_id, operation=operation)
            if item is not None:
                # Validate capacity and the key's first-fence identity before
                # claiming. A rejected request must not consume a lease,
                # generation, or attempt from the recovery item.
                observe_ledger = self._next_observe_ledger(
                    item,
                    idempotency_key_digest=request_key_digest,
                    expected_version=int(expected_version),
                    expected_checksum=checksum,
                )
            if item is None:
                lease = self._prepare_pre_dispatch_item(
                    operation,
                    expected_version=int(expected_version),
                    expected_checksum=checksum,
                )
            else:
                if not self._runner.supports(item.recovery_kind):
                    raise OperationRecoveryObserveError(
                        "OPERATION_RECOVERY_UNSUPPORTED",
                        "This operation has no allowlisted recovery observer",
                        status_code=409,
                        details={"operation_id": normalized_id, "recovery_kind": item.recovery_kind},
                    )
                lease = self._recovery.claim_operation(
                    normalized_id,
                    lease_owner=self._worker_id,
                    lease_seconds=self._lease_seconds,
                    expected_operation_version=int(expected_version),
                    expected_operation_checksum=checksum,
                )
            if observe_ledger is None:
                observe_ledger = self._next_observe_ledger(
                    lease.item,
                    idempotency_key_digest=request_key_digest,
                    expected_version=int(expected_version),
                    expected_checksum=checksum,
                )
            _, claimed_item = self._recovery.commit_observation(
                lease,
                event_type="operator_recovery_observation_requested",
                stage="reconciliation",
                payload={
                    "idempotency_key_digest": request_key_digest,
                    "expected_version": int(expected_version),
                    "expected_checksum": checksum,
                    "observation_only": True,
                },
                expected_statuses=[operation.status],
                actor=actor,
                recovery_status="leased",
                recovery_details_patch={
                    "operator_observe_requests": observe_ledger,
                    "last_operator_observe_key_digest": request_key_digest,
                    "last_operator_observe_expected_version": int(expected_version),
                    "last_operator_observe_expected_checksum": checksum,
                },
                expected_operation_version=int(expected_version),
                expected_operation_checksum=checksum,
            )
            result = self._runner.run_claimed(RecoveryLease(item=claimed_item, token=lease.token))
        except OperationRecoveryObserveError:
            raise
        except RecoveryNotFound as exc:
            raise OperationRecoveryObserveError(
                "OPERATION_RECOVERY_NOT_FOUND",
                "Recovery coordination was not found for this operation",
                status_code=409,
                details={"operation_id": normalized_id},
            ) from exc
        except (RecoveryLeaseBusy, RecoveryOperationConflict) as exc:
            raise self._conflict(normalized_id, operation=self._operations.get(normalized_id)) from exc
        except Exception as exc:
            raise self._unavailable(normalized_id) from exc

        return self._result_or_error(normalized_id, result, idempotent_replay=False)

    @staticmethod
    def _observe_request_records(item: Any) -> list[dict[str, Any]]:
        if item is None:
            return []
        details = dict(item.details or {})
        raw_records = details.get("operator_observe_requests")
        if raw_records is None:
            raw_records = []
        if not isinstance(raw_records, list):
            raise OperationRecoveryObserveError(
                "OPERATION_RECOVERY_IDEMPOTENCY_CONFLICT",
                "The recovery observation idempotency ledger is invalid",
                status_code=409,
                details={"operation_id": item.operation_id},
            )

        records: list[dict[str, Any]] = []
        seen: dict[str, tuple[int, str]] = {}
        candidates = list(raw_records)
        legacy_digest = str(details.get("last_operator_observe_key_digest") or "")
        if legacy_digest:
            candidates.append(
                {
                    "idempotency_key_digest": legacy_digest,
                    "expected_version": details.get("last_operator_observe_expected_version"),
                    "expected_checksum": details.get("last_operator_observe_expected_checksum"),
                }
            )
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                raise OperationRecoveryObserveError(
                    "OPERATION_RECOVERY_IDEMPOTENCY_CONFLICT",
                    "The recovery observation idempotency ledger contains an invalid entry",
                    status_code=409,
                    details={"operation_id": item.operation_id},
                )
            digest = str(candidate.get("idempotency_key_digest") or "")
            checksum = str(candidate.get("expected_checksum") or "")
            version = candidate.get("expected_version")
            digest_hex = digest.removeprefix("sha256:")
            if (
                not digest.startswith("sha256:")
                or len(digest_hex) != 64
                or any(character not in "0123456789abcdef" for character in digest_hex)
                or isinstance(version, bool)
                or not isinstance(version, int)
                or version < 1
                or not checksum
                or len(checksum) > 160
            ):
                raise OperationRecoveryObserveError(
                    "OPERATION_RECOVERY_IDEMPOTENCY_CONFLICT",
                    "The recovery observation idempotency ledger contains an invalid state fence",
                    status_code=409,
                    details={"operation_id": item.operation_id},
                )
            fence = (version, checksum)
            if digest in seen:
                if seen[digest] != fence:
                    raise OperationRecoveryObserveError(
                        "OPERATION_RECOVERY_IDEMPOTENCY_CONFLICT",
                        "The recovery observation idempotency ledger contains conflicting state fences",
                        status_code=409,
                        details={"operation_id": item.operation_id},
                    )
                continue
            seen[digest] = fence
            records.append(
                {
                    "idempotency_key_digest": digest,
                    "expected_version": version,
                    "expected_checksum": checksum,
                }
            )
        if len(records) > _OPERATOR_OBSERVE_LEDGER_LIMIT:
            raise OperationRecoveryObserveError(
                "OPERATION_RECOVERY_IDEMPOTENCY_CONFLICT",
                "The recovery observation idempotency ledger exceeds its safe bound",
                status_code=409,
                details={"operation_id": item.operation_id},
            )
        return records

    @classmethod
    def _same_observe_request(
        cls,
        item: Any,
        *,
        idempotency_key_digest: str,
        expected_version: int,
        expected_checksum: str,
    ) -> bool:
        matching = [
            record
            for record in cls._observe_request_records(item)
            if record["idempotency_key_digest"] == idempotency_key_digest
        ]
        if not matching:
            return False
        stored_version_number = int(matching[0]["expected_version"])
        stored_checksum = str(matching[0]["expected_checksum"])
        if stored_version_number != int(expected_version) or stored_checksum != expected_checksum:
            raise OperationRecoveryObserveError(
                "OPERATION_RECOVERY_IDEMPOTENCY_CONFLICT",
                "The recovery observation idempotency key was already used with a different state fence",
                status_code=409,
                details={"operation_id": item.operation_id},
            )
        return True

    @classmethod
    def _next_observe_ledger(
        cls,
        item: Any,
        *,
        idempotency_key_digest: str,
        expected_version: int,
        expected_checksum: str,
    ) -> list[dict[str, Any]]:
        records = cls._observe_request_records(item)
        if any(
            record["idempotency_key_digest"] == idempotency_key_digest
            for record in records
        ):
            cls._same_observe_request(
                item,
                idempotency_key_digest=idempotency_key_digest,
                expected_version=expected_version,
                expected_checksum=expected_checksum,
            )
            return records
        if len(records) >= _OPERATOR_OBSERVE_LEDGER_LIMIT:
            raise OperationRecoveryObserveError(
                "OPERATION_RECOVERY_IDEMPOTENCY_LEDGER_FULL",
                "No additional recovery observation idempotency keys can be recorded safely",
                status_code=409,
                details={"operation_id": item.operation_id},
            )
        return [
            *records,
            {
                "idempotency_key_digest": idempotency_key_digest,
                "expected_version": int(expected_version),
                "expected_checksum": str(expected_checksum),
            },
        ]

    def _lease_is_live(self, expires_at: datetime | None) -> bool:
        if expires_at is None:
            return False
        normalized = expires_at if expires_at.tzinfo is not None else expires_at.replace(tzinfo=timezone.utc)
        now = self._clock()
        normalized_now = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
        return normalized > normalized_now

    def _replay_observe_result(
        self,
        operation_id: str,
        *,
        operation: OperationSnapshot,
        item: Any,
    ) -> dict[str, Any]:
        error_code = str(item.last_error_code or "")
        details = {
            "operation_id": operation_id,
            "idempotent_replay": True,
            "recovery_status": item.status,
        }
        semantics = self._recovery_error_semantics(error_code)
        if semantics == "ineligible":
            raise OperationRecoveryObserveError(
                "OPERATION_RECOVERY_INELIGIBLE",
                "Recovery observation cannot proceed because coordination binding is invalid",
                status_code=409,
                details={**details, "recovery_error_code": error_code},
            )
        if semantics == "unavailable":
            raise OperationRecoveryObserveError(
                "OPERATION_RECOVERY_OBSERVATION_UNAVAILABLE",
                "Authoritative recovery observation is unavailable",
                status_code=503,
                details={**details, "recovery_error_code": error_code},
            )
        outcome = str(item.details.get("terminal_outcome") or operation.status or item.status)
        return {
            **details,
            "outcome": outcome,
            "observation_only": True,
        }

    def _result_or_error(
        self,
        operation_id: str,
        result: RecoveryRunResult,
        *,
        idempotent_replay: bool,
    ) -> dict[str, Any]:
        if result.outcome == "lease_lost":
            raise self._conflict(operation_id, operation=self._operations.get(operation_id))
        try:
            item = self._recovery.get(operation_id)
        except Exception as exc:
            raise self._unavailable(operation_id) from exc
        error_code = str(item.last_error_code or "") if item is not None else ""
        semantics = self._recovery_error_semantics(error_code)
        if semantics == "ineligible":
            raise OperationRecoveryObserveError(
                "OPERATION_RECOVERY_INELIGIBLE",
                "Recovery observation cannot proceed because coordination binding or state is invalid",
                status_code=409,
                details={
                    "operation_id": operation_id,
                    "outcome": result.outcome,
                    "recovery_error_code": error_code,
                    "idempotent_replay": idempotent_replay,
                },
            )
        if semantics == "unavailable":
            raise OperationRecoveryObserveError(
                "OPERATION_RECOVERY_OBSERVATION_UNAVAILABLE",
                "Recovery observation or its local completion is unavailable",
                status_code=503,
                details={
                    "operation_id": operation_id,
                    "outcome": result.outcome,
                    "recovery_error_code": error_code,
                    "idempotent_replay": idempotent_replay,
                },
            )
        if result.outcome in {"retry_observation_failed", "paused_retry_exhausted"}:
            raise OperationRecoveryObserveError(
                "OPERATION_RECOVERY_OBSERVATION_UNAVAILABLE",
                "Authoritative recovery observation is unavailable",
                status_code=503,
                details={
                    "operation_id": operation_id,
                    "outcome": result.outcome,
                    "idempotent_replay": idempotent_replay,
                },
            )
        if result.outcome in {"paused_binding_mismatch", "paused_unsupported"}:
            raise OperationRecoveryObserveError(
                "OPERATION_RECOVERY_INELIGIBLE",
                "Recovery observation cannot proceed because coordination binding is invalid",
                status_code=409,
                details={
                    "operation_id": operation_id,
                    "outcome": result.outcome,
                    "idempotent_replay": idempotent_replay,
                },
            )
        return {
            "operation_id": operation_id,
            "outcome": result.outcome,
            "observation_only": True,
            "idempotent_replay": idempotent_replay,
        }

    @staticmethod
    def _recovery_error_semantics(error_code: str) -> str | None:
        return recovery_error_semantics(error_code)

    def _prepare_pre_dispatch_item(
        self,
        operation: OperationSnapshot,
        *,
        expected_version: int,
        expected_checksum: str,
    ) -> RecoveryLease:
        kind_by_type = {
            "vm_start": "vm_start_observation",
            "vm_shutdown": "vm_shutdown_observation",
            "vm_create": "vm_create_observation",
            "guided_qm_vm_unlock": "guided_qm_unlock_observation",
        }
        recovery_kind = kind_by_type.get(operation.operation_type)
        has_task_reference = bool(
            str(operation.details.get("proxmox_upid") or "").strip()
            or str(operation.details.get("upid") or "").strip()
        )
        terminal_no_effect = False
        if operation.operation_type in {"vm_start", "vm_shutdown"} and operation.status in {
            "failed",
            "blocked",
        }:
            events = self._operations.list_events(operation.operation_id)
            latest_event = events[-1] if events else None
            terminal_no_effect = bool(
                latest_event is not None
                and is_pre_dispatch_terminal_no_effect(
                    operation_type=operation.operation_type,
                    status=operation.status,
                    details=operation.details,
                    event_type=latest_event.event_type,
                    event_payload=latest_event.payload,
                    event_to_status=latest_event.to_status,
                    event_checksum=latest_event.checksum,
                    operation_checksum=operation.last_event_checksum,
                )
            )
        start_or_shutdown_pre_dispatch = operation.operation_type in {
            "vm_start",
            "vm_shutdown",
        } and (operation.status in {"planned", "dispatching"} or terminal_no_effect)
        guided_events = (
            self._operations.list_events(operation.operation_id)
            if operation.operation_type == "guided_qm_vm_unlock"
            else []
        )
        guided_pre_dispatch = _guided_unissued_plan_proven(operation, guided_events)
        if (
            recovery_kind is None
            or (operation.operation_type in {"vm_start", "vm_shutdown"} and not start_or_shutdown_pre_dispatch)
            or (operation.operation_type == "vm_create" and operation.status != "approved")
            or (operation.operation_type == "guided_qm_vm_unlock" and not guided_pre_dispatch)
            or has_task_reference
            or operation.details.get("recovery_contract") != PRE_DISPATCH_RECOVERY_CONTRACT
        ):
            raise OperationRecoveryObserveError(
                "OPERATION_RECOVERY_NOT_PREPARED",
                "This operation cannot be proven side-effect-free without a durable recovery item",
                status_code=409,
                details={"operation_id": operation.operation_id, "operation_status": operation.status},
            )
        target = _mapping(operation.details.get("target"))
        try:
            vmid = int(target.get("vmid") or operation.target_id.split(":", 1)[1])
        except (TypeError, ValueError, IndexError) as exc:
            raise OperationRecoveryObserveError(
                "OPERATION_RECOVERY_TARGET_MISMATCH",
                "The operation target is not a valid Proxmox VM locator",
                status_code=409,
                details={"operation_id": operation.operation_id},
            ) from exc
        lock = self._lock_reader(operation.target_type, operation.target_id)
        durable = _mapping(lock.get("durable")) if lock else {}
        try:
            durable_vmid = int(durable.get("vmid") or 0)
        except (TypeError, ValueError):
            durable_vmid = 0
        durable_lock_id = str(durable.get("operation_lock_id") or "").strip()
        cluster_id = str(durable.get("cluster_id") or "").strip()
        exact_binding = bool(
            lock
            and operation.target_type == "proxmox_vm"
            and operation.target_id == f"vmid:{vmid}"
            and str(lock.get("target_type") or "") == operation.target_type
            and str(lock.get("target_id") or "") == operation.target_id
            and str(lock.get("owner_id") or "") == operation.operation_id
            and str(lock.get("lock_id") or "") == durable_lock_id
            and durable
            and str(durable.get("owner_id") or "") == operation.operation_id
            and str(durable.get("operation_type") or "") == operation.operation_type
            and str(durable.get("scope_type") or "") == "proxmox_locator"
            and durable_vmid == vmid
            and durable_lock_id
            and cluster_id
            and (
                not terminal_no_effect
                or (
                    str(operation.details.get("target_lock_id") or "") == durable_lock_id
                    and str(operation.details.get("cluster_id") or "") == cluster_id
                )
            )
        )
        if not exact_binding and not guided_pre_dispatch:
            raise OperationRecoveryObserveError(
                "OPERATION_RECOVERY_TARGET_LOCK_MISMATCH",
                "The exact owned target lock is required for pre-dispatch recovery",
                status_code=409,
                details={"operation_id": operation.operation_id},
            )
        recovery_phase = (
            "lock_acquired"
            if operation.operation_type == "vm_create" or (guided_pre_dispatch and exact_binding)
            else "plan_prepared"
            if guided_pre_dispatch
            else "pre_dispatch"
        )
        terminal_details = (
            {
                "pre_dispatch_terminal_no_effect": True,
                "mutation_dispatched": False,
                "pre_dispatch_terminal_reason": operation.details["pre_dispatch_terminal_reason"],
                "terminal_outcome": operation.status,
            }
            if terminal_no_effect
            else {}
        )
        lease = self._recovery.prepare_and_claim(
            RecoverySpec(
                operation_id=operation.operation_id,
                recovery_kind=recovery_kind,
                details={
                    "operation_type": operation.operation_type,
                    "execution_mode": operation.execution_mode,
                    "target_type": operation.target_type,
                    "target_id": operation.target_id,
                    "node_id": str(target.get("node_id") or ""),
                    "vmid": vmid,
                    "vm_name": str(target.get("name") or ""),
                    "plan_digest": operation.plan_digest,
                    "phase": recovery_phase,
                    "target_lock_id": durable_lock_id if exact_binding else "",
                    "cluster_id": cluster_id if exact_binding else "",
                    "mutation_replay_allowed": False,
                    "recovery_contract": PRE_DISPATCH_RECOVERY_CONTRACT,
                    **(
                        {
                            "original_config_lock": str(
                                _mapping(operation.details.get("observed_before")).get(
                                    "config_lock"
                                )
                                or ""
                            )
                        }
                        if guided_pre_dispatch
                        else {}
                    ),
                    **terminal_details,
                },
            ),
            lease_owner=self._worker_id,
            lease_seconds=self._lease_seconds,
            expected_operation_version=expected_version,
            expected_operation_checksum=expected_checksum,
        )
        if not self._runner.supports(recovery_kind):
            raise OperationRecoveryObserveError(
                "OPERATION_RECOVERY_UNSUPPORTED",
                "This operation has no allowlisted recovery observer",
                status_code=409,
                details={"operation_id": operation.operation_id, "recovery_kind": recovery_kind},
            )
        return lease

    @staticmethod
    def _conflict(
        operation_id: str,
        *,
        operation: OperationSnapshot | None,
    ) -> OperationRecoveryObserveError:
        return OperationRecoveryObserveError(
            "OPERATION_RECOVERY_STATE_CONFLICT",
            "Operation or recovery state changed concurrently",
            status_code=409,
            details={
                "operation_id": operation_id,
                "current_version": operation.version if operation is not None else None,
                "current_checksum": operation.last_event_checksum if operation is not None else None,
                "current_status": operation.status if operation is not None else None,
            },
        )

    @staticmethod
    def _unavailable(operation_id: str) -> OperationRecoveryObserveError:
        return OperationRecoveryObserveError(
            "OPERATION_RECOVERY_PERSISTENCE_UNAVAILABLE",
            "Recovery observation could not be persisted or completed",
            status_code=503,
            details={"operation_id": operation_id},
        )


def _compact_task(task: Mapping[str, Any], *, node_id: str, upid: str) -> dict[str, Any]:
    return compact_proxmox_task(
        {
            "status": task.get("status"),
            "exitstatus": task.get("exitstatus"),
        },
        node=node_id,
        upid=upid,
    )


def _compact_vm_status(observed: Mapping[str, Any], *, node_id: str, vmid: int) -> dict[str, Any]:
    return compact_proxmox_vm_status(
        {
            "name": observed.get("name"),
            "status": observed.get("status"),
        },
        node=node_id,
        vmid=vmid,
    )


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}
