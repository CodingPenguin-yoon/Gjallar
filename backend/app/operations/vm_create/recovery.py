"""Durable recovery coordination owned by the Create VM action.

This module records only local coordination and read-safe evidence. External
Proxmox mutation remains exclusively in ``app.vm_create.proxmox_runner``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.redaction import redact_secrets
from app.operations.core.domain import OperationActor, OperationSnapshot
from app.operations.core.evidence import compact_proxmox_task, compact_proxmox_vm_status
from app.operations.locks.domain import OPEN_TARGET_LOCK_STATUSES, locator_scope_key
from app.operations.core.ports import OperationStorePort
from app.operations.recovery.domain import (
    PRE_DISPATCH_RECOVERY_CONTRACT,
    RecoveryLease,
    RecoverySpec,
)
from app.operations.recovery.ports import RecoveryStorePort
from app.operations.vm_create.domain import compact_create_result
from app.vm_create.proxmox_runner import vm_config_fingerprint


VM_CREATE_RECOVERY_KIND = "vm_create_observation"
VM_CREATE_EXECUTION_MODE = "managed_api"
VM_CREATE_RECOVERY_ACTOR = OperationActor(
    user_id="system:operation-recovery",
    username="operation-recovery",
    role="system",
)


class VmCreateRecoveryError(RuntimeError):
    """Raised when durable Create coordination cannot be safely advanced."""

    def __init__(self, code: str, message: str) -> None:
        self.code = str(code)
        super().__init__(message)





class _CreateCompatibilityProjectionUnavailable(RuntimeError):
    pass


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sanitized(value: Mapping[str, Any] | None) -> dict[str, Any]:
    redacted = redact_secrets(dict(value or {}))
    return dict(redacted) if isinstance(redacted, dict) else {}


def _required_lock_binding(
    operation: OperationSnapshot,
    target_lock: Mapping[str, Any],
) -> tuple[dict[str, Any], str, str]:
    lock = _mapping(target_lock)
    durable = _mapping(lock.get("durable"))
    lock_id = str(durable.get("operation_lock_id") or "").strip()
    cluster_id = str(durable.get("cluster_id") or "").strip()
    if not lock_id or not cluster_id:
        raise VmCreateRecoveryError(
            "PROXMOX_CREATE_RECOVERY_LOCK_BINDING_INVALID",
            "Create VM recovery requires an exact durable target lock",
        )
    try:
        vmid = int(operation.target_id.split(":", 1)[1])
        durable_vmid = int(durable.get("vmid") or 0)
    except (TypeError, ValueError, IndexError, OverflowError) as exc:
        raise VmCreateRecoveryError(
            "PROXMOX_CREATE_RECOVERY_LOCK_BINDING_INVALID",
            "Create VM recovery target lock has an invalid locator",
        ) from exc
    if (
        str(lock.get("target_type") or "") != operation.target_type
        or str(lock.get("target_id") or "") != operation.target_id
        or str(lock.get("owner_id") or "") != operation.operation_id
        or not str(lock.get("lock_id") or "").strip()
        or str(durable.get("operation_type") or "") != operation.operation_type
        or str(durable.get("owner_id") or "") != operation.operation_id
        or str(durable.get("scope_type") or "") != "proxmox_locator"
        or str(durable.get("scope_key") or "") != locator_scope_key(cluster_id, vmid)
        or str(durable.get("status") or "") != "active"
        or durable_vmid != vmid
    ):
        raise VmCreateRecoveryError(
            "PROXMOX_CREATE_RECOVERY_LOCK_BINDING_INVALID",
            "Create VM recovery target lock does not match the exact Operation",
        )
    return durable, lock_id, cluster_id


@dataclass
class VmCreateRecoverySession:
    """Foreground lease that durably fences every Create mutation checkpoint."""

    recovery: RecoveryStorePort
    operations: OperationStorePort
    lease: RecoveryLease
    operation: OperationSnapshot
    actor: OperationActor
    lease_seconds: float
    phase: str = "lock_acquired"
    completed: bool = False

    @classmethod
    def prepare(
        cls,
        *,
        recovery: RecoveryStorePort,
        operations: OperationStorePort,
        operation: OperationSnapshot,
        plan: Any,
        preview: Mapping[str, Any],
        target_lock: Mapping[str, Any],
        actor: OperationActor,
        lease_owner: str,
        lease_seconds: float,
    ) -> "VmCreateRecoverySession":
        if (
            operation.operation_type != "vm_create"
            or operation.execution_mode != VM_CREATE_EXECUTION_MODE
            or operation.target_type != "proxmox_vm"
            or operation.target_id != f"vmid:{int(plan.vmid)}"
            or operation.operation_id != str(plan.job_id)
        ):
            raise VmCreateRecoveryError(
                "PROXMOX_CREATE_RECOVERY_OPERATION_BINDING_INVALID",
                "Create VM recovery does not match the exact Operation and plan",
            )
        durable, target_lock_id, cluster_id = _required_lock_binding(operation, target_lock)
        review = _mapping(getattr(plan, "review_confirm", {}))
        preview_payload = _mapping(preview)
        post_check = _mapping(preview_payload.get("post_check"))
        details = {
            "operation_type": operation.operation_type,
            "execution_mode": operation.execution_mode,
            "target_type": operation.target_type,
            "target_id": operation.target_id,
            "node_id": str(plan.target_node_id),
            "vmid": int(plan.vmid),
            "vm_name": str(plan.vm_name),
            "profile_id": str(plan.profile_id),
            "plan_digest": operation.plan_digest,
            "plan_artifact_id": str(review.get("plan_artifact_id") or ""),
            "power_policy": str(getattr(plan, "power_policy", "") or "stopped"),
            "required_status": str(post_check.get("required_status") or ""),
            "expected_config": _mapping(preview_payload.get("config")),
            "target_lock_id": target_lock_id,
            "cluster_id": cluster_id,
            "target_lock": {
                "target_type": operation.target_type,
                "target_id": operation.target_id,
                "owner_id": operation.operation_id,
                "durable": durable,
            },
            "phase": "lock_acquired",
            "mutation_replay_allowed": False,
            "recovery_contract": PRE_DISPATCH_RECOVERY_CONTRACT,
        }
        lease = recovery.prepare_and_claim(
            RecoverySpec(
                operation_id=operation.operation_id,
                recovery_kind=VM_CREATE_RECOVERY_KIND,
                details=details,
            ),
            lease_owner=lease_owner,
            lease_seconds=lease_seconds,
            expected_operation_version=operation.version,
            expected_operation_checksum=operation.last_event_checksum,
        )
        return cls(
            recovery=recovery,
            operations=operations,
            lease=lease,
            operation=operation,
            actor=actor,
            lease_seconds=max(float(lease_seconds), 1.0),
        )

    def bind_operation(self, operation: OperationSnapshot) -> None:
        if operation.operation_id != self.operation.operation_id:
            raise VmCreateRecoveryError(
                "PROXMOX_CREATE_RECOVERY_OPERATION_BINDING_INVALID",
                "Create VM recovery cannot bind a different Operation",
            )
        self.operation = operation

    def heartbeat(self) -> None:
        self.lease = self.recovery.heartbeat(
            self.lease,
            lease_seconds=self.lease_seconds,
        )

    def checkpoint(
        self,
        phase: str,
        evidence: Mapping[str, Any] | None = None,
        *,
        stage: str = "create",
        event_type: str | None = None,
        next_status: str | None = None,
        recovery_status: str = "leased",
        error_code: str | None = None,
        release_target_lock: bool = False,
        details_patch: Mapping[str, Any] | None = None,
        recovery_details_patch: Mapping[str, Any] | None = None,
        projector: Callable[[Any], Mapping[str, Any] | None] | None = None,
    ) -> OperationSnapshot:
        normalized_phase = str(phase).strip()
        if not normalized_phase:
            raise ValueError("Create VM recovery phase is required")
        compact = _sanitized(evidence)
        safety_patch = (
            {"clear_rejection": True, "external_effect": False}
            if normalized_phase == "clone_rejected"
            else {}
        )
        operation, item = self.recovery.commit_observation(
            self.lease,
            event_type=event_type or f"vm_create_{normalized_phase}",
            stage=stage,
            payload={"phase": normalized_phase, **compact},
            details_patch={"recovery_phase": normalized_phase, **_sanitized(details_patch)},
            next_status=next_status,
            expected_statuses=[self.operation.status],
            actor=self.actor,
            recovery_status=recovery_status,
            error_code=error_code,
            recovery_details_patch={
                "phase": normalized_phase,
                **compact,
                **safety_patch,
                **_sanitized(recovery_details_patch),
            },
            release_target_lock=release_target_lock,
            expected_operation_version=self.operation.version,
            expected_operation_checksum=self.operation.last_event_checksum,
            projector=projector,
        )
        self.operation = operation
        self.lease = RecoveryLease(item=item, token=self.lease.token)
        self.phase = normalized_phase
        self.completed = recovery_status == "completed"
        return operation

    def record_success_observed(self, result: Mapping[str, Any]) -> OperationSnapshot:
        evidence = compact_create_result(result)
        self.checkpoint(
            "dispatch_result_observed",
            {"task": evidence["task"], "side_effects": evidence["side_effects"]},
            stage="task_poll",
            event_type="dispatch_result_observed",
            next_status="running",
        )
        return self.checkpoint(
            "task_and_state_observed",
            evidence,
            stage="post_check",
            event_type="task_and_state_observed",
            next_status="verifying",
            recovery_details_patch={
                "result_success": result.get("success") is True,
                "result_status": str(result.get("status") or ""),
                "observed_after": _sanitized(_mapping(result.get("observed_after"))),
                "observed_after_artifact": _sanitized(
                    _mapping(result.get("observed_after_artifact"))
                ),
            },
        )

    def defer_verified_projection(self, *, error_type: str) -> OperationSnapshot:
        return self.checkpoint(
            "verified_projection_pending",
            {
                "result_status": "completed",
                "error_type": str(error_type)[:200],
                "mutation_replayed": False,
            },
            stage="reconciliation",
            event_type="vm_create_verified_projection_deferred",
            recovery_status="retry_wait",
            error_code="PROXMOX_CREATE_RECOVERY_PROJECTION_FAILED",
            recovery_details_patch={"result_success": True},
        )

    def pause_for_reconciliation(
        self,
        *,
        code: str,
        message: str,
        evidence: Mapping[str, Any] | None = None,
    ) -> OperationSnapshot:
        payload = {"code": str(code), "message": str(message)[:1000], **_sanitized(evidence)}
        next_status = (
            "needs_reconciliation"
            if self.operation.status in {"dispatching", "running", "verifying"}
            else None
        )
        return self.checkpoint(
            "reconciliation_required",
            payload,
            stage="reconciliation",
            event_type="reconciliation_required",
            next_status=next_status,
            recovery_status="paused",
            error_code=code,
            details_patch={"result_status": "needs_reconciliation"},
        )





    def complete_pre_dispatch_failure(
        self,
        *,
        code: str,
        message: str,
        error_type: str = "",
        record_compatibility_failure: Callable[[], None],

    ) -> OperationSnapshot:
        try:
            record_compatibility_failure()
        except Exception as exc:
            self.checkpoint(
                "pre_dispatch_projection_pending",
                {
                    "code": code,
                    "message": str(message)[:1000],
                    "error_type": str(error_type)[:200],
                    "projection_error_type": type(exc).__name__,
                    "external_effect": False,
                },
                stage="reconciliation",
                event_type="vm_create_pre_dispatch_projection_deferred",
                recovery_status="retry_wait",
                error_code="PROXMOX_CREATE_PRE_DISPATCH_PROJECTION_FAILED",
            )
            raise VmCreateRecoveryError(
                "PROXMOX_CREATE_PRE_DISPATCH_PROJECTION_FAILED",
                "Create VM pre-dispatch compatibility projection could not be closed",
            ) from exc

        if self.operation.status == "approved":
            next_status = "blocked"
        elif self.operation.status == "dispatching":
            next_status = "failed"
        else:
            next_status = None
        return self.checkpoint(
            "pre_dispatch_failed",
            {
                "code": code,
                "message": str(message)[:1000],
                "error_type": str(error_type)[:200],
                "external_effect": False,
            },
            stage="create",
            event_type="dispatch_preparation_failed",
            next_status=next_status,
            recovery_status="completed",
            error_code=code,
            release_target_lock=True,
        )

    def complete_clear_failure(
        self,
        *,
        result: Mapping[str, Any],

    ) -> OperationSnapshot:

        return self.checkpoint(
            "dispatch_rejected",
            compact_create_result(result),
            stage="create",
            event_type="dispatch_rejected",
            next_status="failed",
            recovery_status="completed",
            error_code="PROXMOX_CREATE_FAILED",
            release_target_lock=True,
            details_patch={"result_status": "failed"},
        )

    def complete_success(
        self,
        *,
        result: Mapping[str, Any],
        project_compatibility: Callable[
            [Any],
            tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]],
        ],

    ) -> OperationSnapshot:
        evidence = compact_create_result(result)

        def projected_completion(transaction: Any) -> Mapping[str, Any]:


            request, workload, artifact = project_compatibility(transaction)
            bounded_artifact = _mapping(artifact)
            if (
                not str(bounded_artifact.get("artifact_id") or "").strip()
                or not str(bounded_artifact.get("checksum") or "").strip()
            ):
                raise ValueError("Create VM terminal artifact projection is incomplete")
            return {
                "event_payload": {
                    "vm_create_request": dict(request),
                    "workload": dict(workload),
                    "observed_after_artifact": bounded_artifact,
                },
                "operation_details_patch": {
                    "vm_create_request": dict(request),
                    "workload": dict(workload),
                },
                "recovery_details_patch": {
                    "observed_after_artifact": bounded_artifact,
                },
            }

        return self.checkpoint(
            "verification_succeeded",
            evidence,
            stage="post_check",
            event_type="verification_succeeded",
            next_status="succeeded",
            recovery_status="completed",
            release_target_lock=True,
            details_patch={"result_status": "completed"},
            projector=projected_completion,
        )


class VmCreateRecoveryObservationPort(Protocol):
    """GET-only Proxmox surface available to Create recovery."""

    def get_task_status(self, *, node: str, upid: str) -> dict[str, Any]: ...

    def get_vm_status(self, *, node: str, vmid: int) -> dict[str, Any]: ...

    def get_vm_config(self, *, node: str, vmid: int) -> dict[str, Any]: ...


class VmCreateRecoveryProjectionPort(Protocol):
    """Idempotent compatibility projection required before releasing a lock."""

    def record_pre_dispatch_failed(
        self,
        *,
        operation_id: str,
        target: Mapping[str, Any],
        code: str,
    ) -> None: ...

    def record_pre_dispatch_failed_in_transaction(
        self,
        transaction: Any,
        *,
        operation_id: str,
        target: Mapping[str, Any],
        code: str,
    ) -> None: ...

    def record_clear_rejection(
        self,
        *,
        operation_id: str,
        target: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> None: ...

    def record_clear_rejection_in_transaction(
        self,
        transaction: Any,
        *,
        operation_id: str,
        target: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> None: ...

    def record_verified_absent_failure(
        self,
        *,
        operation_id: str,
        target: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> None: ...

    def record_verified_absent_failure_in_transaction(
        self,
        transaction: Any,
        *,
        operation_id: str,
        target: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> None: ...

    def record_verified_success(
        self,
        *,
        operation_id: str,
        target: Mapping[str, Any],
        observed_after: Mapping[str, Any],
        observed_after_artifact: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]: ...

    def record_verified_success_in_transaction(
        self,
        transaction: Any,
        *,
        operation_id: str,
        target: Mapping[str, Any],
        observed_after: Mapping[str, Any],
        observed_after_artifact: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]: ...


@dataclass(frozen=True)
class VmCreateRecoveryRunResult:
    operation_id: str
    outcome: str


def _retry_state(lease: RecoveryLease, *, max_attempts: int) -> tuple[str, float]:
    if lease.item.attempt_count >= max(int(max_attempts), 1):
        return "paused", 0
    return "retry_wait", 5


class VmCreateRecoveryHandler:
    """Recover Create VM with observation only; never replay a mutation."""

    def __init__(
        self,
        *,
        recovery: RecoveryStorePort,
        operations: OperationStorePort,
        observation_factory: Callable[[], VmCreateRecoveryObservationPort],
        compatibility_projection: VmCreateRecoveryProjectionPort | None = None,

        target_lock_reader: Callable[[str, str], Mapping[str, Any] | None] | None = None,
        max_attempts: int = 5,
    ) -> None:
        self._recovery = recovery
        self._operations = operations
        self._observation_factory = observation_factory
        self._compatibility_projection = compatibility_projection

        self._target_lock_reader = target_lock_reader
        self._max_attempts = max(int(max_attempts), 1)

    def handle(self, lease: RecoveryLease) -> VmCreateRecoveryRunResult:
        operation = self._operations.get(lease.operation_id)
        if operation is None:
            raise RuntimeError(f"Operation is missing for recovery: {lease.operation_id}")
        details = dict(lease.item.details or {})
        binding_error = self._binding_error(lease, operation, details)
        if binding_error:
            return self._pause(
                lease,
                operation,
                code="PROXMOX_CREATE_RECOVERY_BINDING_MISMATCH",
                evidence={"reason": binding_error},
                require_exact_reconciliation_lock=False,
                recovery_details_patch=(
                    {"clone_upid": "", "start_upid": ""}
                    if binding_error in {
                        "recovery_clone_task_reference_invalid",
                        "recovery_start_task_reference_invalid",
                    }
                    else None
                ),
            )

        phase = str(details.get("phase") or "").strip()
        node_id = str(details.get("node_id") or "").strip()
        try:
            vmid = int(details.get("vmid") or 0)
        except (TypeError, ValueError):
            vmid = 0
        if not node_id or vmid <= 0:
            return self._pause(
                lease,
                operation,
                code="PROXMOX_CREATE_RECOVERY_TARGET_INVALID",
                evidence={"node_id": node_id, "vmid": vmid},
            )

        if phase in {
            "lock_acquired",
            "dispatch_prepared",
            "pre_dispatch_projection_pending",
        }:
            return self._complete_pre_dispatch(lease, operation, node_id=node_id, vmid=vmid)

        if phase == "clone_rejected" or details.get("clear_rejection") is True:
            return self._complete_clear_rejection(
                lease,
                operation,
                details=details,
                node_id=node_id,
                vmid=vmid,
            )

        if operation.status in {"succeeded", "failed", "blocked"}:
            return self._complete_existing_terminal(lease, operation, vmid=vmid)

        if details.get("result_success") is True and isinstance(details.get("observed_after"), Mapping):
            return self._recover_verified_success(
                lease,
                operation,
                details=details,
                node_id=node_id,
                vmid=vmid,
            )

        return self._observe_without_replay(
            lease,
            operation,
            details=details,
            node_id=node_id,
            vmid=vmid,
        )

    def _binding_error(
        self,
        lease: RecoveryLease,
        operation: OperationSnapshot,
        details: Mapping[str, Any],
    ) -> str:
        if lease.item.recovery_kind != VM_CREATE_RECOVERY_KIND:
            return "recovery_kind_mismatch"
        if (
            str(details.get("recovery_contract") or "") != PRE_DISPATCH_RECOVERY_CONTRACT
            or details.get("mutation_replay_allowed") is not False
        ):
            return "recovery_safety_contract_mismatch"
        if operation.operation_type != "vm_create" or operation.execution_mode != VM_CREATE_EXECUTION_MODE:
            return "operation_identity_mismatch"
        if operation.target_type != "proxmox_vm" or not operation.target_id.startswith("vmid:"):
            return "operation_target_invalid"
        if (
            str(details.get("operation_type") or "") != operation.operation_type
            or str(details.get("execution_mode") or "") != operation.execution_mode
            or str(details.get("target_type") or "") != operation.target_type
            or str(details.get("target_id") or "") != operation.target_id
            or str(details.get("plan_digest") or "") != operation.plan_digest
        ):
            return "recovery_operation_binding_mismatch"
        try:
            vmid = int(details.get("vmid") or 0)
        except (TypeError, ValueError):
            return "recovery_vmid_invalid"
        if operation.target_id != f"vmid:{vmid}":
            return "recovery_vmid_mismatch"
        operation_target = _mapping(operation.details.get("target"))
        operation_node_id = str(operation_target.get("node_id") or "").strip()
        declared_node_id = str(details.get("node_id") or "").strip()
        try:
            operation_vmid = int(operation_target.get("vmid") or 0)
        except (TypeError, ValueError, OverflowError):
            return "operation_target_invalid"
        if (
            not operation_node_id
            or declared_node_id != operation_node_id
            or operation_vmid != vmid
        ):
            return "recovery_node_mismatch"
        clone_upid = str(details.get("clone_upid") or "").strip()
        start_upid = str(details.get("start_upid") or "").strip()
        if clone_upid and not compact_proxmox_task({}, upid=clone_upid).get("upid"):
            return "recovery_clone_task_reference_invalid"
        if start_upid and not compact_proxmox_task({}, upid=start_upid).get("upid"):
            return "recovery_start_task_reference_invalid"
        if clone_upid:
            template_node = str(details.get("template_node") or operation_node_id).strip()
            clone_task_node_id = str(details.get("clone_task_node_id") or template_node).strip()
            if clone_task_node_id != template_node:
                return "recovery_clone_task_node_mismatch"
        if self._target_lock_reader is None:
            return "target_lock_reader_missing"
        lock = _mapping(self._target_lock_reader(operation.target_type, operation.target_id))
        durable = _mapping(lock.get("durable"))
        cluster_id = str(details.get("cluster_id") or "").strip()
        lock_id = str(details.get("target_lock_id") or "").strip()
        if str(lock.get("owner_id") or "") != operation.operation_id:
            return "target_lock_owner_mismatch"
        if (
            str(lock.get("target_type") or "") != operation.target_type
            or str(lock.get("target_id") or "") != operation.target_id
            or str(lock.get("lock_id") or "") != lock_id
        ):
            return "target_lock_identity_mismatch"
        if str(durable.get("operation_type") or "") != operation.operation_type:
            return "target_lock_operation_type_mismatch"
        try:
            durable_vmid = int(durable.get("vmid") or 0)
        except (TypeError, ValueError, OverflowError):
            return "target_lock_locator_mismatch"
        if (
            str(durable.get("owner_id") or "") != operation.operation_id
            or str(durable.get("scope_type") or "") != "proxmox_locator"
            or str(durable.get("scope_key") or "") != locator_scope_key(cluster_id, vmid)
            or str(durable.get("status") or "") not in OPEN_TARGET_LOCK_STATUSES
            or durable_vmid != vmid
        ):
            return "target_lock_locator_mismatch"
        if not lock_id or str(durable.get("operation_lock_id") or "") != lock_id:
            return "target_lock_id_mismatch"
        if not cluster_id or str(durable.get("cluster_id") or "") != cluster_id:
            return "target_lock_cluster_mismatch"
        return ""

    def _commit(
        self,
        lease: RecoveryLease,
        operation: OperationSnapshot,
        *,
        event_type: str,
        stage: str,
        payload: Mapping[str, Any],
        recovery_status: str,
        next_status: str | None = None,
        error_code: str | None = None,
        retry_delay_seconds: float = 0,
        recovery_details_patch: Mapping[str, Any] | None = None,
        details_patch: Mapping[str, Any] | None = None,
        release_target_lock: bool = False,
        require_exact_reconciliation_lock: bool = True,
        projector: Callable[[Any], Mapping[str, Any] | None] | None = None,
    ) -> tuple[RecoveryLease, OperationSnapshot]:
        updated_operation, item = self._recovery.commit_observation(
            lease,
            event_type=event_type,
            stage=stage,
            payload=_sanitized(payload),
            details_patch=_sanitized(details_patch),
            next_status=next_status,
            expected_statuses=[operation.status],
            actor=VM_CREATE_RECOVERY_ACTOR,
            recovery_status=recovery_status,
            retry_delay_seconds=retry_delay_seconds,
            error_code=error_code,
            recovery_details_patch=_sanitized(recovery_details_patch),
            release_target_lock=release_target_lock,
            require_exact_reconciliation_lock=require_exact_reconciliation_lock,
            expected_operation_version=operation.version,
            expected_operation_checksum=operation.last_event_checksum,
            projector=projector,
        )
        return RecoveryLease(item=item, token=lease.token), updated_operation

    def _pause(
        self,
        lease: RecoveryLease,
        operation: OperationSnapshot,
        *,
        code: str,
        evidence: Mapping[str, Any],
        require_exact_reconciliation_lock: bool = True,
        recovery_details_patch: Mapping[str, Any] | None = None,
    ) -> VmCreateRecoveryRunResult:
        next_status = (
            "needs_reconciliation"
            if operation.status in {"dispatching", "running", "verifying"}
            else None
        )
        self._commit(
            lease,
            operation,
            event_type="vm_create_recovery_paused",
            stage="reconciliation",
            payload={"code": code, **dict(evidence)},
            details_patch={"reconciliation_code": code},
            next_status=next_status,
            recovery_status="paused",
            error_code=code,
            recovery_details_patch={
                "last_observation": dict(evidence),
                **dict(recovery_details_patch or {}),
            },
            require_exact_reconciliation_lock=require_exact_reconciliation_lock,
        )
        return VmCreateRecoveryRunResult(lease.operation_id, "paused_manual_reconciliation")



    def _complete_existing_terminal(
        self,
        lease: RecoveryLease,
        operation: OperationSnapshot,
        *,
        vmid: int,
    ) -> VmCreateRecoveryRunResult:
        self._commit(
            lease,
            operation,
            event_type="vm_create_recovery_terminal_lock_released",
            stage="post_check",
            payload={"operation_status": operation.status},
            recovery_status="completed",
            release_target_lock=True,
        )
        return VmCreateRecoveryRunResult(lease.operation_id, operation.status)

    def _complete_pre_dispatch(
        self,
        lease: RecoveryLease,
        operation: OperationSnapshot,
        *,
        node_id: str,
        vmid: int,
    ) -> VmCreateRecoveryRunResult:
        if self._compatibility_projection is None:
            return self._pause(
                lease,
                operation,
                code="PROXMOX_CREATE_RECOVERY_PROJECTION_UNAVAILABLE",
                evidence={"phase": str(lease.item.details.get("phase") or "")},
            )
        if operation.status == "approved":
            next_status = "blocked"
        elif operation.status == "dispatching":
            next_status = "failed"
        elif operation.status in {"failed", "blocked"}:
            next_status = None
        else:
            return self._pause(
                lease,
                operation,
                code="PROXMOX_CREATE_RECOVERY_OPERATION_STATE_INVALID",
                evidence={"operation_status": operation.status, "phase": lease.item.details.get("phase")},
            )

        def project_pre_dispatch(transaction: Any) -> Mapping[str, Any]:
            try:
                self._compatibility_projection.record_pre_dispatch_failed_in_transaction(
                    transaction,
                    operation_id=operation.operation_id,
                    target={"node_id": node_id, "vmid": vmid},
                    code="PROXMOX_CREATE_RECOVERED_PRE_DISPATCH",
                )
            except Exception as exc:
                raise _CreateCompatibilityProjectionUnavailable() from exc
            return {}

        try:
            self._commit(
                lease,
                operation,
                event_type="vm_create_recovery_pre_dispatch_closed",
                stage="reconciliation",
                payload={"mutation_dispatched": False},
                details_patch={"result_status": "failed", "recovered_pre_dispatch": True},
                next_status=next_status,
                recovery_status="completed",
                release_target_lock=True,
                projector=project_pre_dispatch,
            )

        except _CreateCompatibilityProjectionUnavailable as exc:
            return self._retry_projection(
                lease,
                operation,
                exc=exc.__cause__ or exc,
            )
        return VmCreateRecoveryRunResult(lease.operation_id, "failed_pre_dispatch")

    def _recover_verified_success(
        self,
        lease: RecoveryLease,
        operation: OperationSnapshot,
        *,
        details: Mapping[str, Any],
        node_id: str,
        vmid: int,
    ) -> VmCreateRecoveryRunResult:
        persisted = _mapping(details.get("observed_after"))
        artifact = _mapping(details.get("observed_after_artifact"))
        phase = str(details.get("phase") or "")
        if phase == "observed_after_artifact_recorded" and (
            not str(artifact.get("artifact_id") or "").strip()
            or not str(artifact.get("checksum") or "").strip()
        ):
            return self._pause(
                lease,
                operation,
                code="PROXMOX_CREATE_RECOVERY_ARTIFACT_BINDING_INVALID",
                evidence={"phase": "observed_after_artifact_recorded"},
            )
        try:
            client = self._observation_factory()
            status = dict(client.get_vm_status(node=node_id, vmid=vmid) or {})
            config = dict(client.get_vm_config(node=node_id, vmid=vmid) or {})
        except Exception as exc:
            return self._retry_observation(lease, operation, exc=exc)
        compact_status = compact_proxmox_vm_status(status, node=node_id, vmid=vmid)
        observed = {
            "exists": True,
            "status": compact_status["status"],
            "name": str(details.get("vm_name") or "")[:255],
            "fingerprint": vm_config_fingerprint(config),
        }
        expected_status = str(details.get("required_status") or persisted.get("status") or "").lower()
        expected_hash = str(_mapping(persisted.get("fingerprint")).get("hash") or "")
        matches = (
            bool(expected_status)
            and observed["status"] == expected_status
            and bool(expected_hash)
            and str(observed["fingerprint"].get("hash") or "") == expected_hash
        )
        if not matches:
            return self._pause(
                lease,
                operation,
                code="PROXMOX_CREATE_RECOVERY_STATE_MISMATCH",
                evidence={
                    "expected_status": expected_status,
                    "expected_fingerprint_hash": expected_hash,
                    "observed": observed,
                },
            )
        if self._compatibility_projection is None:
            return self._pause(
                lease,
                operation,
                code="PROXMOX_CREATE_RECOVERY_PROJECTION_UNAVAILABLE",
                evidence={"observed": observed, "artifact_id": artifact.get("artifact_id")},
            )

        if operation.status == "dispatching":
            lease, operation = self._commit(
                lease,
                operation,
                event_type="vm_create_recovery_result_adopted",
                stage="task_poll",
                payload={"mutation_replayed": False},
                next_status="running",
                recovery_status="leased",
            )
        if operation.status in {"running", "needs_reconciliation"}:
            lease, operation = self._commit(
                lease,
                operation,
                event_type="vm_create_recovery_state_verified",
                stage="post_check",
                payload={"observed_after": observed},
                next_status="verifying",
                recovery_status="leased",
            )
        if operation.status != "verifying":
            return self._pause(
                lease,
                operation,
                code="PROXMOX_CREATE_RECOVERY_OPERATION_STATE_INVALID",
                evidence={"operation_status": operation.status},
            )

        def project_success(transaction: Any) -> Mapping[str, Any]:
            try:
                request, workload, projected_artifact = (
                    self._compatibility_projection.record_verified_success_in_transaction(
                        transaction,
                        operation_id=operation.operation_id,
                        target={"node_id": node_id, "vmid": vmid},
                        observed_after=persisted,
                        observed_after_artifact=artifact,
                    )
                )
                bounded_artifact = _mapping(projected_artifact)
                if (
                    not str(bounded_artifact.get("artifact_id") or "").strip()
                    or not str(bounded_artifact.get("checksum") or "").strip()
                ):
                    raise ValueError("Create recovery artifact projection is incomplete")

            except Exception as exc:
                raise _CreateCompatibilityProjectionUnavailable() from exc
            return {
                "event_payload": {
                    "observed_after_artifact": bounded_artifact,
                    "vm_create_request": dict(request),
                    "workload": dict(workload),
                },
                "operation_details_patch": {
                    "vm_create_request": dict(request),
                    "workload": dict(workload),
                },
                "recovery_details_patch": {
                    "observed_after_artifact": bounded_artifact,
                },
            }

        try:
            self._commit(
                lease,
                operation,
                event_type="vm_create_recovery_verification_succeeded",
                stage="post_check",
                payload={"observed_after": persisted},
                details_patch={
                    "result_status": "completed",
                    "recovered_after_restart": True,
                },
                next_status="succeeded",
                recovery_status="completed",
                release_target_lock=True,
                projector=project_success,
            )

        except _CreateCompatibilityProjectionUnavailable as exc:
            return self._retry_projection(
                lease,
                operation,
                exc=exc.__cause__ or exc,
                evidence={"observed": observed},
            )
        return VmCreateRecoveryRunResult(lease.operation_id, "succeeded")

    def _complete_clear_rejection(
        self,
        lease: RecoveryLease,
        operation: OperationSnapshot,
        *,
        details: Mapping[str, Any],
        node_id: str,
        vmid: int,
    ) -> VmCreateRecoveryRunResult:
        if self._compatibility_projection is None:
            return self._pause(
                lease,
                operation,
                code="PROXMOX_CREATE_RECOVERY_PROJECTION_UNAVAILABLE",
                evidence={"phase": "clone_rejected"},
            )
        if operation.status == "dispatching":
            next_status = "failed"
        elif operation.status == "failed":
            next_status = None
        else:
            return self._pause(
                lease,
                operation,
                code="PROXMOX_CREATE_RECOVERY_OPERATION_STATE_INVALID",
                evidence={"operation_status": operation.status, "phase": "clone_rejected"},
            )

        def project_clear_rejection(transaction: Any) -> Mapping[str, Any]:
            try:
                self._compatibility_projection.record_clear_rejection_in_transaction(
                    transaction,
                    operation_id=operation.operation_id,
                    target={"node_id": node_id, "vmid": vmid},
                    evidence={
                        "status": str(details.get("status") or "failed"),
                        "error_type": str(details.get("error_type") or ""),
                        "details": _mapping(details.get("details")),
                    },
                )
            except Exception as exc:
                raise _CreateCompatibilityProjectionUnavailable() from exc
            return {}

        try:
            self._commit(
                lease,
                operation,
                event_type="vm_create_recovery_clear_rejection_closed",
                stage="create",
                payload={"external_effect": False, "mutation_replayed": False},
                details_patch={"result_status": "failed", "recovered_clear_rejection": True},
                next_status=next_status,
                recovery_status="completed",
                error_code="PROXMOX_CREATE_FAILED",
                release_target_lock=True,
                projector=project_clear_rejection,
            )

        except _CreateCompatibilityProjectionUnavailable as exc:
            return self._retry_projection(
                lease,
                operation,
                exc=exc.__cause__ or exc,
                evidence={"phase": "clone_rejected"},
            )
        return VmCreateRecoveryRunResult(lease.operation_id, "failed")

    def _observe_without_replay(
        self,
        lease: RecoveryLease,
        operation: OperationSnapshot,
        *,
        details: Mapping[str, Any],
        node_id: str,
        vmid: int,
    ) -> VmCreateRecoveryRunResult:
        phase = str(details.get("phase") or "")
        start_upid = str(details.get("start_upid") or "").strip()
        clone_upid = str(details.get("clone_upid") or "").strip()
        upid = start_upid or clone_upid
        task_kind = "start" if start_upid else ("clone" if clone_upid else "")
        task_node_id = (
            node_id
            if start_upid
            else str(details.get("clone_task_node_id") or details.get("template_node") or node_id)
        )
        try:
            client = self._observation_factory()
            task = dict(client.get_task_status(node=task_node_id, upid=upid) or {}) if upid else {}
            status = dict(client.get_vm_status(node=node_id, vmid=vmid) or {})
            target_absent = status.get("exists") is False
            config = (
                {}
                if target_absent
                else dict(client.get_vm_config(node=node_id, vmid=vmid) or {})
            )
        except Exception as exc:
            return self._retry_observation(lease, operation, exc=exc)
        compact_task = compact_proxmox_task(task, node=task_node_id, upid=upid)
        task_status = str(compact_task.get("status") or "")
        raw_exitstatus = str(compact_task.get("exitstatus") or "")
        bounded_exitstatus = (
            "OK"
            if raw_exitstatus.upper() == "OK"
            else ("NON_OK" if raw_exitstatus else "")
        )
        compact_status = compact_proxmox_vm_status(status, node=node_id, vmid=vmid)
        observed = {"exists": not target_absent}
        if not target_absent:
            observed.update(
                {
                    "status": compact_status["status"],
                    "name": str(details.get("vm_name") or "")[:255],
                    "fingerprint": vm_config_fingerprint(config),
                }
            )
        observation = {
            "phase": phase,
            "task": {
                "kind": task_kind,
                "upid": upid,
                "status": compact_task["status"],
                "exitstatus": bounded_exitstatus,
            },
            "observed": observed,
        }
        if upid and task_status != "stopped":
            retry_status, retry_delay = _retry_state(lease, max_attempts=self._max_attempts)
            self._commit(
                lease,
                operation,
                event_type="vm_create_recovery_task_observed",
                stage="task_poll",
                payload=observation,
                recovery_status=retry_status,
                retry_delay_seconds=retry_delay,
                error_code=(
                    "PROXMOX_CREATE_RECOVERY_RETRY_EXHAUSTED"
                    if retry_status == "paused"
                    else None
                ),
                recovery_details_patch={"last_observation": observation},
            )
            outcome = "paused_retry_exhausted" if retry_status == "paused" else "retry_task_running"
            return VmCreateRecoveryRunResult(lease.operation_id, outcome)
        if (
            upid
            and task_status == "stopped"
            and bounded_exitstatus == "NON_OK"
            and target_absent
        ):
            return self._complete_verified_absent_failure(
                lease,
                operation,
                node_id=node_id,
                vmid=vmid,
                observation={**observation, "mutation_replayed": False},
            )
        return self._pause(
            lease,
            operation,
            code="PROXMOX_CREATE_RECOVERY_MANUAL_DECISION_REQUIRED",
            evidence=observation,
        )

    def _complete_verified_absent_failure(
        self,
        lease: RecoveryLease,
        operation: OperationSnapshot,
        *,
        node_id: str,
        vmid: int,
        observation: Mapping[str, Any],
    ) -> VmCreateRecoveryRunResult:
        if operation.status not in {
            "dispatching",
            "running",
            "verifying",
            "needs_reconciliation",
            "failed",
        }:
            return self._pause(
                lease,
                operation,
                code="PROXMOX_CREATE_RECOVERY_OPERATION_STATE_INVALID",
                evidence={
                    "operation_status": operation.status,
                    "phase": observation.get("phase"),
                },
            )
        if self._compatibility_projection is None:
            return self._pause(
                lease,
                operation,
                code="PROXMOX_CREATE_RECOVERY_PROJECTION_UNAVAILABLE",
                evidence=observation,
            )

        def project_absent_failure(transaction: Any) -> Mapping[str, Any]:
            try:
                self._compatibility_projection.record_verified_absent_failure_in_transaction(
                    transaction,
                    operation_id=operation.operation_id,
                    target={"node_id": node_id, "vmid": vmid},
                    evidence=observation,
                )
            except Exception as exc:
                raise _CreateCompatibilityProjectionUnavailable() from exc
            return {}

        try:
            self._commit(
                lease,
                operation,
                event_type="vm_create_recovery_task_failed_target_absent",
                stage="post_check",
                payload=observation,
                details_patch={
                    "result_status": "failed",
                    "recovered_after_restart": True,
                    "target_absence_verified": True,
                },
                next_status=(None if operation.status == "failed" else "failed"),
                recovery_status="completed",
                error_code="PROXMOX_CREATE_RECOVERY_TASK_FAILED_TARGET_ABSENT",
                recovery_details_patch={
                    "terminal_outcome": "failed",
                    "last_observation": dict(observation),
                },
                release_target_lock=True,
                projector=project_absent_failure,
            )

        except _CreateCompatibilityProjectionUnavailable as exc:
            return self._retry_projection(
                lease,
                operation,
                exc=exc.__cause__ or exc,
                evidence=observation,
            )
        return VmCreateRecoveryRunResult(lease.operation_id, "failed_target_absent")

    def _retry_observation(
        self,
        lease: RecoveryLease,
        operation: OperationSnapshot,
        *,
        exc: Exception,
    ) -> VmCreateRecoveryRunResult:
        retry_status, retry_delay = _retry_state(lease, max_attempts=self._max_attempts)
        self._commit(
            lease,
            operation,
            event_type="vm_create_recovery_observation_failed",
            stage="reconciliation",
            payload={"error_type": type(exc).__name__},
            recovery_status=retry_status,
            retry_delay_seconds=retry_delay,
            error_code=(
                "PROXMOX_CREATE_RECOVERY_RETRY_EXHAUSTED"
                if retry_status == "paused"
                else "PROXMOX_CREATE_RECOVERY_OBSERVATION_FAILED"
            ),
        )
        outcome = "paused_retry_exhausted" if retry_status == "paused" else "retry_observation"
        return VmCreateRecoveryRunResult(lease.operation_id, outcome)

    def _retry_projection(
        self,
        lease: RecoveryLease,
        operation: OperationSnapshot,
        *,
        exc: Exception,
        evidence: Mapping[str, Any] | None = None,
    ) -> VmCreateRecoveryRunResult:
        retry_status, retry_delay = _retry_state(lease, max_attempts=self._max_attempts)
        payload = {"error_type": type(exc).__name__, **dict(evidence or {})}
        self._commit(
            lease,
            operation,
            event_type="vm_create_recovery_projection_failed",
            stage="reconciliation",
            payload=payload,
            recovery_status=retry_status,
            retry_delay_seconds=retry_delay,
            error_code=(
                "PROXMOX_CREATE_RECOVERY_RETRY_EXHAUSTED"
                if retry_status == "paused"
                else "PROXMOX_CREATE_RECOVERY_PROJECTION_FAILED"
            ),
            recovery_details_patch={"last_projection_error": payload},
        )
        outcome = "paused_retry_exhausted" if retry_status == "paused" else "retry_projection"
        return VmCreateRecoveryRunResult(lease.operation_id, outcome)




__all__ = [
    "PRE_DISPATCH_RECOVERY_CONTRACT",
    "VM_CREATE_RECOVERY_KIND",
    "VmCreateRecoveryError",
    "VmCreateRecoveryHandler",
    "VmCreateRecoveryObservationPort",
    "VmCreateRecoveryProjectionPort",
    "VmCreateRecoveryRunResult",
    "VmCreateRecoverySession",
]
