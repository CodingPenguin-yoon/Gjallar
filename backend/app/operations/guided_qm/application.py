"""Guided `qm unlock` planning, operator handoff, and API verification."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence

from app.operations.core.domain import (
    OperationActor,
    OperationIntentConflict,
    OperationSnapshot,
    OperationSpec,
    OperationStateConflict,
    operation_digest,
)
from app.operations.core.read_models import operation_event_payload, operation_payload
from app.operations.guided_qm.domain import (
    GUIDED_QM_UNLOCK_OPERATION_TYPE,
    GUIDED_QM_UNLOCK_SUPPORTED_LOCKS,
    GUIDED_QM_UNLOCK_TTL_SECONDS,
    AttestGuidedQmCommand,
    PlanGuidedQmUnlockCommand,
    VerifyGuidedQmCommand,
    build_guided_qm_unlock_bundle,
)
from app.operations.guided_qm.errors import GuidedQmError
from app.operations.guided_qm.ports import (
    GuidedQmExecutionPorts,
    GuidedQmObservationFailure,
    GuidedQmTargetLockBusy,
)
from app.operations.recovery.domain import (
    PRE_DISPATCH_RECOVERY_CONTRACT,
    RecoveryLease,
    RecoveryLeaseBusy,
    RecoveryOperationConflict,
    RecoverySpec,
)


Clock = Callable[[], datetime]
_GUIDED_QM_RECOVERY_KIND = "guided_qm_unlock_observation"
_SYSTEM_RECOVERY_ACTOR = OperationActor(user_id="system", username="operation-recovery", role="system")
_SAFE_TASK_TOKEN = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_TASK_STATUSES = frozenset({"running", "stopped", "queued", "unknown"})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _compact_tasks(tasks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    seen: set[str] = set()
    for task in tasks:
        entry: dict[str, Any] = {}
        node = str(task.get("node") or "").strip()
        if _SAFE_TASK_TOKEN.fullmatch(node):
            entry["node"] = node
        task_type = str(task.get("type") or "").strip().lower()
        entry["type"] = task_type if _SAFE_TASK_TOKEN.fullmatch(task_type) else "unknown"
        status = str(task.get("status") or "").strip().lower()
        entry["status"] = status if status in _TASK_STATUSES else "unknown"
        for key in ("pid", "starttime"):
            try:
                numeric = int(task.get(key))
            except (TypeError, ValueError, OverflowError):
                continue
            if 0 <= numeric <= 2**63 - 1:
                entry[key] = numeric
        raw_identity = str(task.get("upid") or task.get("id") or "").strip()
        identity = operation_digest({"task_ref": raw_identity, "evidence": entry})
        entry["task_ref_digest"] = identity
        if identity in seen:
            continue
        seen.add(identity)
        compact.append(entry)
        if len(compact) >= 10:
            break
    return compact


def _config_lock(config: Mapping[str, Any]) -> str:
    value = config.get("lock")
    normalized = str(value).strip().lower() if value is not None else ""
    if not normalized:
        return ""
    if normalized in GUIDED_QM_UNLOCK_SUPPORTED_LOCKS:
        return normalized
    return "unsupported_present"


class GuidedQmUnlockUseCase:
    """Coordinate a manual `qm unlock` without executing a shell command."""

    def __init__(
        self,
        *,
        ports: GuidedQmExecutionPorts,
        clock: Clock = _utc_now,
        ttl_seconds: int = GUIDED_QM_UNLOCK_TTL_SECONDS,
        recovery_max_attempts: int = 5,
    ) -> None:
        self._ports = ports
        self._clock = clock
        self._ttl_seconds = max(int(ttl_seconds), 1)
        self._recovery_max_attempts = max(int(recovery_max_attempts), 1)

    def get(self, operation_id: str) -> dict[str, Any]:
        operation = self._get_operation(operation_id)
        if operation is None:
            raise GuidedQmError(
                "GUIDED_QM_OPERATION_NOT_FOUND",
                "Guided qm operation was not found",
                status_code=404,
                details={"operation_id": str(operation_id)},
            )
        return self._result(operation)

    def plan_unlock(self, command: PlanGuidedQmUnlockCommand) -> dict[str, Any]:
        actor = self._operator_actor(command.actor)
        existing = self._get_operation(command.operation_id)
        if existing is not None:
            self._assert_operation_identity(existing, command.intent, command.target_id)
            if existing.status == "planned":
                return self._finalize_planned_operation(existing, actor=actor, idempotent_replay=True)
            existing = self._expire_waiting_operation(existing)
            if existing.status == "awaiting_operator":
                self._assert_target_lock_owned(existing, exact=True)
            return self._result(existing, idempotent_replay=True)

        self._release_releasable_target_lock(command.target_id)
        current_lock = self._ports.locks.current("proxmox_vm", command.target_id)
        if current_lock:
            raise self._target_lock_busy_error(command.operation_id, current_lock)

        observed = self._observe(node_id=command.node_id, vmid=command.vmid)
        active_tasks = observed["active_tasks"]
        if active_tasks:
            raise GuidedQmError(
                "GUIDED_QM_UNLOCK_ACTIVE_TASKS_BLOCKED",
                "qm unlock is blocked while Proxmox reports active tasks for the VM",
                details={"target": command.intent["target"], "active_tasks": active_tasks},
            )
        observed_lock = str(observed.get("config_lock") or "")
        if not observed_lock:
            raise GuidedQmError(
                "GUIDED_QM_UNLOCK_NOT_LOCKED",
                "qm unlock is not applicable because the VM configuration has no lock",
                details={"target": command.intent["target"], "observed_before": observed},
            )
        if observed_lock not in GUIDED_QM_UNLOCK_SUPPORTED_LOCKS:
            raise GuidedQmError(
                "GUIDED_QM_UNLOCK_LOCK_TYPE_UNSUPPORTED",
                "The observed Proxmox lock type is not allowlisted for Guided qm unlock",
                details={
                    "target": command.intent["target"],
                    "observed_lock": observed_lock,
                    "supported_lock_types": sorted(GUIDED_QM_UNLOCK_SUPPORTED_LOCKS),
                },
            )

        now = _as_utc(self._clock())
        expires_at = now + timedelta(seconds=self._ttl_seconds)
        bundle = build_guided_qm_unlock_bundle(
            operation_id=command.operation_id,
            node_id=command.node_id,
            vmid=command.vmid,
            expires_at=expires_at,
            observed_lock=observed_lock,
        )
        spec = OperationSpec(
            operation_id=command.operation_id,
            operation_type=GUIDED_QM_UNLOCK_OPERATION_TYPE,
            execution_mode="guided_manual",
            target_type="proxmox_vm",
            target_id=command.target_id,
            idempotency_key=command.idempotency_key,
            intent_digest=operation_digest(command.intent),
            plan_digest=str(bundle["plan_digest"]),
            actor=actor,
            initial_status="planned",
            initial_stage="plan_preparation",
            expires_at=expires_at,
            details={
                "target": command.intent["target"],
                "observed_before": observed,
                "instruction_exposed": False,
                "recovery_contract": PRE_DISPATCH_RECOVERY_CONTRACT,
            },
        )
        try:
            created = self._ports.operations.create(
                spec,
                event_payload={
                    "template_id": bundle["template_id"],
                    "target": bundle["target"],
                    "observed_before": observed,
                    "instruction_exposed": False,
                },
            )
        except OperationIntentConflict as exc:
            raise GuidedQmError(
                "GUIDED_QM_IDEMPOTENCY_CONFLICT",
                "The idempotency identity belongs to a different Guided qm plan",
                details={"operation_id": exc.operation_id},
            ) from exc
        except GuidedQmError:
            raise
        except Exception as exc:
            raise self._persistence_error(command.operation_id) from exc
        if not created.created:
            self._assert_operation_identity(created.operation, command.intent, command.target_id)
        return self._finalize_planned_operation(
            created.operation,
            actor=actor,
            idempotent_replay=not created.created,
        )

    def attest(self, command: AttestGuidedQmCommand) -> dict[str, Any]:
        actor = self._operator_actor(command.actor)
        operation = self._require_guided_unlock(command.operation_id)
        self._assert_plan_digest(operation, command.plan_digest)
        if operation.status in {"awaiting_verification", "verifying", "succeeded"}:
            return self._result(operation, idempotent_replay=True)
        if operation.status == "needs_reconciliation":
            if self._execution_attested(operation):
                return self._result(operation, idempotent_replay=True)
            now = _as_utc(self._clock())
            operation = self._append_event(
                operation.operation_id,
                event_type="operator_execution_attested_for_reconciliation",
                stage="operator_attestation",
                payload={
                    "plan_digest": operation.plan_digest,
                    "command_executed": True,
                    "attested_at": now.isoformat(),
                },
                details_patch={
                    "operator_attestation": {
                        "actor": actor.to_dict(),
                        "plan_digest": operation.plan_digest,
                        "command_executed": True,
                        "attested_at": now.isoformat(),
                        "late": True,
                    }
                },
                actor=actor,
                expected_statuses=["needs_reconciliation"],
            )
            return self._result(operation)
        if operation.status == "expired":
            now = _as_utc(self._clock())
            operation = self._transition(
                operation.operation_id,
                next_status="needs_reconciliation",
                event_type="late_operator_execution_attested_after_expiry",
                stage="operator_attestation",
                payload={
                    "plan_digest": operation.plan_digest,
                    "command_executed": True,
                    "attested_at": now.isoformat(),
                    "expired_at": operation.expires_at.isoformat() if operation.expires_at else None,
                },
                details_patch={
                    "operator_attestation": {
                        "actor": actor.to_dict(),
                        "plan_digest": operation.plan_digest,
                        "command_executed": True,
                        "attested_at": now.isoformat(),
                        "late": True,
                    },
                    "reconciliation_reason": "execution_attested_after_operation_expired",
                },
                actor=actor,
                expected_statuses=["expired"],
            )
            return self._result(operation)
        if operation.status != "awaiting_operator":
            raise self._state_error(operation, expected=["awaiting_operator"])
        current_lock = self._ports.locks.current(operation.target_type, operation.target_id)
        if self._is_exact_owned_lock(operation, current_lock) and not self._is_active_instruction_lock(
            operation,
            current_lock,
        ):
            now = _as_utc(self._clock())
            operation = self._transition(
                operation.operation_id,
                next_status="needs_reconciliation",
                event_type="late_operator_execution_attested_after_lock_became_inactive",
                stage="operator_attestation",
                payload={
                    "plan_digest": operation.plan_digest,
                    "command_executed": True,
                    "attested_at": now.isoformat(),
                },
                details_patch={
                    "operator_attestation": {
                        "actor": actor.to_dict(),
                        "plan_digest": operation.plan_digest,
                        "command_executed": True,
                        "attested_at": now.isoformat(),
                        "late": True,
                    },
                    "reconciliation_reason": "execution_attested_after_target_lock_became_inactive",
                },
                actor=actor,
                expected_statuses=["awaiting_operator"],
            )
            return self._result(operation)
        self._assert_target_lock_owned(operation, transition_on_loss=True, exact=True, active=True)

        now = _as_utc(self._clock())
        if operation.expires_at is not None and now >= _as_utc(operation.expires_at):
            operation = self._transition(
                operation.operation_id,
                next_status="needs_reconciliation",
                event_type="late_operator_execution_attested",
                stage="operator_attestation",
                payload={
                    "plan_digest": operation.plan_digest,
                    "command_executed": True,
                    "attested_at": now.isoformat(),
                    "expired_at": operation.expires_at.isoformat(),
                },
                details_patch={
                    "operator_attestation": {
                        "actor": actor.to_dict(),
                        "plan_digest": operation.plan_digest,
                        "command_executed": True,
                        "attested_at": now.isoformat(),
                        "late": True,
                    },
                    "reconciliation_reason": "execution_attested_after_instruction_expiry",
                },
                actor=actor,
                expected_statuses=["awaiting_operator"],
            )
            return self._result(operation)

        operation = self._transition(
            operation.operation_id,
            next_status="awaiting_verification",
            event_type="operator_execution_attested",
            stage="operator_attestation",
            payload={
                "plan_digest": operation.plan_digest,
                "command_executed": True,
                "attested_at": now.isoformat(),
            },
            details_patch={
                "operator_attestation": {
                    "actor": actor.to_dict(),
                    "plan_digest": operation.plan_digest,
                    "command_executed": True,
                    "attested_at": now.isoformat(),
                }
            },
            actor=actor,
            expected_statuses=["awaiting_operator"],
        )
        return self._result(operation)

    def verify(self, command: VerifyGuidedQmCommand) -> dict[str, Any]:
        actor = self._operator_actor(command.actor)
        operation = self._require_guided_unlock(command.operation_id)
        self._assert_plan_digest(operation, command.plan_digest)
        if operation.status == "succeeded":
            return self._result(operation, idempotent_replay=True)
        if not self._execution_attested(operation):
            raise GuidedQmError(
                "GUIDED_QM_ATTESTATION_REQUIRED",
                "Operator execution attestation is required before verification",
                details={"operation_id": operation.operation_id},
            )
        if operation.status not in {"awaiting_verification", "verifying", "needs_reconciliation"}:
            raise self._state_error(
                operation,
                expected=["awaiting_verification", "verifying", "needs_reconciliation"],
            )
        self._assert_target_lock_owned(operation, transition_on_loss=True, exact=True, active=True)
        lease = self._claim_recovery(operation)
        return self._recover_verification(
            operation,
            lease,
            actor=actor,
            raise_on_unavailable=True,
        )

    def recover(self, lease: RecoveryLease) -> dict[str, Any]:
        """Run one GET-only recovery observation for an already claimed item."""

        operation = self._require_guided_unlock(lease.operation_id)
        self._validate_recovery_lease(operation, lease)
        if operation.status == "planned":
            current_lock = self._ports.locks.current(operation.target_type, operation.target_id)
            if not current_lock or str(current_lock.get("owner_id") or "") != operation.operation_id:
                operation, _ = self._close_unissued_without_owned_lock(
                    operation,
                    lease,
                    event_type="plan_preparation_lock_missing",
                    reason="provisional_plan_target_lock_missing",
                    observed_target_lock=current_lock,
                    actor=_SYSTEM_RECOVERY_ACTOR,
                )
                return self._result(operation)
            if not self._is_exact_owned_lock(operation, current_lock, allow_unrecorded=True):
                operation, _ = self._commit_recovery(
                    operation,
                    lease,
                    next_status="blocked",
                    event_type="plan_preparation_lock_missing",
                    stage="plan_preparation",
                    payload={"observed_target_lock": current_lock or {}},
                    details_patch={"reconciliation_reason": "provisional_plan_target_lock_missing"},
                    actor=_SYSTEM_RECOVERY_ACTOR,
                    expected_statuses=["planned"],
                    recovery_status="paused",
                    error_code="GUIDED_QM_PROVISIONAL_LOCK_MISSING",
                )
                return self._result(operation)
            operation, lease = self._bind_planned_target_lock(
                operation,
                lease,
                lock_evidence=dict(current_lock),
                actor=_SYSTEM_RECOVERY_ACTOR,
            )
            return self._finalize_planned_with_lease(
                operation,
                lease,
                lock_evidence=dict(current_lock or {}),
                actor=_SYSTEM_RECOVERY_ACTOR,
                idempotent_replay=True,
            )
        if operation.status == "awaiting_operator":
            if operation.expires_at is not None and _as_utc(self._clock()) < _as_utc(operation.expires_at):
                delay = max((_as_utc(operation.expires_at) - _as_utc(self._clock())).total_seconds(), 1.0)
                operation, _ = self._commit_recovery(
                    operation,
                    lease,
                    event_type="recovery_instruction_still_active",
                    stage="operator_handoff",
                    payload={"expires_at": operation.expires_at.isoformat()},
                    actor=_SYSTEM_RECOVERY_ACTOR,
                    expected_statuses=["awaiting_operator"],
                    recovery_status="retry_wait",
                    retry_delay_seconds=delay,
                )
                return self._result(operation)
            current_lock = self._ports.locks.current(operation.target_type, operation.target_id)
            if not self._is_exact_owned_lock(operation, current_lock):
                operation, _ = self._commit_recovery(
                    operation,
                    lease,
                    next_status="needs_reconciliation",
                    event_type="expiry_target_lock_mismatch",
                    stage="operator_handoff",
                    payload={"observed_target_lock": current_lock or {}},
                    details_patch={"reconciliation_reason": "target_lock_missing_at_instruction_expiry"},
                    actor=_SYSTEM_RECOVERY_ACTOR,
                    expected_statuses=["awaiting_operator"],
                    recovery_status="paused",
                    error_code="GUIDED_QM_TARGET_LOCK_LOST",
                )
                return self._result(operation)
            return self._recover_waiting_expiry(operation, lease, actor=_SYSTEM_RECOVERY_ACTOR)
        if operation.status in {"awaiting_verification", "verifying", "needs_reconciliation"}:
            if not self._execution_attested(operation):
                operation, _ = self._commit_recovery(
                    operation,
                    lease,
                    event_type="recovery_waiting_for_operator_attestation",
                    stage="reconciliation",
                    payload={"operation_status": operation.status},
                    actor=_SYSTEM_RECOVERY_ACTOR,
                    expected_statuses=[operation.status],
                    recovery_status="paused",
                    error_code="GUIDED_QM_ATTESTATION_REQUIRED",
                )
                return self._result(operation)
            if operation.status == "needs_reconciliation" and self._late_execution_attested(
                operation
            ):
                operation, _ = self._commit_recovery(
                    operation,
                    lease,
                    event_type="recovery_late_attestation_requires_manual_verification",
                    stage="reconciliation",
                    payload={"operation_status": operation.status},
                    actor=_SYSTEM_RECOVERY_ACTOR,
                    expected_statuses=["needs_reconciliation"],
                    recovery_status="paused",
                    error_code="GUIDED_QM_LATE_ATTESTATION_MANUAL_VERIFICATION_REQUIRED",
                )
                return self._result(operation)
            current_lock = self._ports.locks.current(operation.target_type, operation.target_id)
            if not self._is_active_instruction_lock(operation, current_lock):
                next_status = "needs_reconciliation" if operation.status != "needs_reconciliation" else None
                operation, _ = self._commit_recovery(
                    operation,
                    lease,
                    next_status=next_status,
                    event_type="recovery_target_lock_mismatch",
                    stage="reconciliation",
                    payload={"observed_target_lock": current_lock or {}},
                    details_patch={"reconciliation_reason": "target_lock_missing_during_verification"},
                    actor=_SYSTEM_RECOVERY_ACTOR,
                    expected_statuses=[operation.status],
                    recovery_status="paused",
                    error_code="GUIDED_QM_TARGET_LOCK_LOST",
                )
                return self._result(operation)
            return self._recover_verification(
                operation,
                lease,
                actor=_SYSTEM_RECOVERY_ACTOR,
                raise_on_unavailable=False,
            )
        operation, _ = self._commit_recovery(
            operation,
            lease,
            event_type="recovery_state_ineligible",
            stage="reconciliation",
            payload={"operation_status": operation.status},
            actor=_SYSTEM_RECOVERY_ACTOR,
            expected_statuses=[operation.status],
            recovery_status="paused",
            error_code="GUIDED_QM_RECOVERY_STATE_INELIGIBLE",
        )
        return self._result(operation)

    def _finalize_planned_operation(
        self,
        operation: OperationSnapshot,
        *,
        actor: OperationActor,
        idempotent_replay: bool,
    ) -> dict[str, Any]:
        if operation.status != "planned":
            return self._result(operation, idempotent_replay=idempotent_replay)

        lease = self._prepare_or_claim_recovery(operation, lock_evidence={})
        current_lock = self._ports.locks.current(operation.target_type, operation.target_id)
        if current_lock and not self._is_exact_owned_lock(operation, current_lock, allow_unrecorded=True):
            if str(current_lock.get("owner_id") or "") == operation.operation_id:
                raise GuidedQmError(
                    "GUIDED_QM_RECOVERY_BINDING_MISMATCH",
                    "The retained Guided qm target lock no longer matches its prepared binding",
                    details={"operation_id": operation.operation_id},
                )
            operation, _ = self._close_unissued_without_owned_lock(
                operation,
                lease,
                event_type="plan_target_lock_busy",
                reason="target_lock_busy",
                observed_target_lock=current_lock,
                actor=actor,
            )
            raise self._target_lock_busy_error(operation.operation_id, current_lock)

        if current_lock is None:
            try:
                lock_handle = self._ports.locks.acquire(
                    operation.target_type,
                    operation.target_id,
                    operation.operation_id,
                )
                current_lock = dict(lock_handle.evidence)
            except GuidedQmTargetLockBusy as exc:
                current_lock = self._ports.locks.current(
                    operation.target_type,
                    operation.target_id,
                ) or dict(exc.evidence)
                if not self._is_exact_owned_lock(
                    operation,
                    current_lock,
                    allow_unrecorded=True,
                ):
                    operation, _ = self._close_unissued_without_owned_lock(
                        operation,
                        lease,
                        event_type="plan_target_lock_busy",
                        reason="target_lock_busy",
                        observed_target_lock=current_lock,
                        actor=actor,
                    )
                    raise self._target_lock_busy_error(operation.operation_id, current_lock) from exc

        operation, lease = self._bind_planned_target_lock(
            operation,
            lease,
            lock_evidence=current_lock,
            actor=actor,
        )
        return self._finalize_planned_with_lease(
            operation,
            lease,
            lock_evidence=current_lock,
            actor=actor,
            idempotent_replay=idempotent_replay,
        )

    def _finalize_planned_with_lease(
        self,
        operation: OperationSnapshot,
        lease: RecoveryLease,
        *,
        lock_evidence: Mapping[str, Any],
        actor: OperationActor,
        idempotent_replay: bool,
    ) -> dict[str, Any]:
        prepared_lock_id = str(lease.item.details.get("target_lock_id") or "")
        prepared_cluster_id = str(lease.item.details.get("cluster_id") or "").strip()
        current_cluster_id = self._lock_cluster_id(lock_evidence)
        if (
            not prepared_lock_id
            or prepared_lock_id != self._lock_id(lock_evidence)
            or not prepared_cluster_id
            or not current_cluster_id
            or prepared_cluster_id != current_cluster_id
        ):
            raise GuidedQmError(
                "GUIDED_QM_RECOVERY_BINDING_MISMATCH",
                "The recovery lease no longer matches the exact provisional target lock",
                details={"operation_id": operation.operation_id},
            )
        target = operation.details.get("target") if isinstance(operation.details.get("target"), dict) else {}
        original_lock = self._original_config_lock(operation)
        try:
            observed = self._observe(
                node_id=str(target.get("node_id") or ""),
                vmid=int(target.get("vmid") or 0),
            )
        except GuidedQmError as exc:
            operation = self._close_unissued_plan(
                operation,
                lease,
                next_status="blocked",
                event_type="plan_final_observation_unavailable",
                payload={"code": exc.code},
                details_patch={"plan_finalization": {"ready": False, "reason": "observation_unavailable"}},
                actor=actor,
            )
            raise

        current_lock = self._ports.locks.current(operation.target_type, operation.target_id)
        prepared_lock_id = str(lease.item.details.get("target_lock_id") or "")
        if (
            not self._is_exact_owned_lock(operation, current_lock, allow_unrecorded=True)
            or self._lock_id(current_lock or {}) != prepared_lock_id
        ):
            operation, _ = self._commit_recovery(
                operation,
                lease,
                next_status="blocked",
                event_type="plan_target_lock_changed_before_handoff",
                stage="plan_preparation",
                payload={"observed_target_lock": current_lock or {}},
                details_patch={"reconciliation_reason": "provisional_target_lock_changed_before_handoff"},
                actor=actor,
                expected_statuses=["planned"],
                recovery_status="paused",
                error_code="GUIDED_QM_TARGET_LOCK_LOST",
            )
            raise GuidedQmError(
                "GUIDED_QM_TARGET_LOCK_LOST",
                "The exact provisional target lock changed before the Guided instruction handoff",
                details={"operation_id": operation.operation_id},
            )

        state_unchanged = (
            str(observed.get("config_lock") or "") == original_lock
            and not observed.get("active_tasks")
        )
        if not state_unchanged:
            operation = self._close_unissued_plan(
                operation,
                lease,
                next_status="blocked",
                event_type="plan_state_changed_before_handoff",
                payload={"observed": observed, "expected_config_lock": original_lock},
                details_patch={
                    "plan_finalization": {
                        "ready": False,
                        "reason": "authoritative_state_changed_before_handoff",
                        "observed": observed,
                    }
                },
                actor=actor,
            )
            raise GuidedQmError(
                "GUIDED_QM_PLAN_STATE_CHANGED",
                "Authoritative Proxmox state changed before the Guided instruction could be issued",
                details={"operation_id": operation.operation_id, "observed": observed},
            )

        if operation.expires_at is not None and _as_utc(self._clock()) >= _as_utc(operation.expires_at):
            operation = self._close_unissued_plan(
                operation,
                lease,
                next_status="expired",
                event_type="unissued_instruction_expired",
                payload={"expires_at": operation.expires_at.isoformat(), "observed": observed},
                details_patch={"plan_finalization": {"ready": False, "reason": "expired_before_handoff"}},
                actor=actor,
            )
            return self._result(
                operation,
                idempotent_replay=idempotent_replay,
                target_lock_released=True,
            )

        delay = self._seconds_until_expiry(operation)
        bundle = self._instruction_bundle(operation)
        operation, _ = self._commit_recovery(
            operation,
            lease,
            next_status="awaiting_operator",
            event_type="guided_instruction_issued",
            stage="operator_handoff",
            payload={
                "plan_digest": operation.plan_digest,
                "expires_at": operation.expires_at.isoformat() if operation.expires_at else None,
                "observed": observed,
                "instruction_exposed": True,
                "instruction_bundle": bundle,
            },
            details_patch={
                "instruction_bundle": bundle,
                "instruction_exposed": True,
                "target_operation_lock": dict(lock_evidence),
                "plan_finalization": {"ready": True, "observed": observed},
            },
            actor=actor,
            expected_statuses=["planned"],
            recovery_status="retry_wait",
            retry_delay_seconds=delay,
            recovery_details_patch={"phase": "awaiting_operator"},
        )
        return self._result(operation, idempotent_replay=idempotent_replay)

    def _bind_planned_target_lock(
        self,
        operation: OperationSnapshot,
        lease: RecoveryLease,
        *,
        lock_evidence: Mapping[str, Any],
        actor: OperationActor,
    ) -> tuple[OperationSnapshot, RecoveryLease]:
        if not self._is_exact_owned_lock(operation, lock_evidence, allow_unrecorded=True):
            raise GuidedQmError(
                "GUIDED_QM_RECOVERY_BINDING_MISMATCH",
                "The provisional target lock is not the exact Guided qm plan lock",
                details={"operation_id": operation.operation_id},
            )
        lock_id = self._lock_id(lock_evidence)
        cluster_id = self._lock_cluster_id(lock_evidence)
        prepared_lock_id = str(lease.item.details.get("target_lock_id") or "").strip()
        prepared_cluster_id = str(lease.item.details.get("cluster_id") or "").strip()
        recorded = operation.details.get("target_operation_lock")
        recorded_lock_id = self._lock_id(recorded) if isinstance(recorded, Mapping) else ""
        recorded_cluster_id = (
            self._lock_cluster_id(recorded) if isinstance(recorded, Mapping) else ""
        )
        if prepared_lock_id not in {"", lock_id} or prepared_cluster_id not in {"", cluster_id}:
            raise GuidedQmError(
                "GUIDED_QM_RECOVERY_BINDING_MISMATCH",
                "The prepared recovery item belongs to a different target lock",
                details={"operation_id": operation.operation_id},
            )
        if recorded_lock_id not in {"", lock_id} or recorded_cluster_id not in {"", cluster_id}:
            raise GuidedQmError(
                "GUIDED_QM_RECOVERY_BINDING_MISMATCH",
                "The Guided qm Operation records a different target lock",
                details={"operation_id": operation.operation_id},
            )
        if (
            prepared_lock_id == lock_id
            and prepared_cluster_id == cluster_id
            and recorded_lock_id == lock_id
            and recorded_cluster_id == cluster_id
        ):
            return operation, lease
        operation, item = self._commit_recovery(
            operation,
            lease,
            event_type="guided_plan_target_lock_bound",
            stage="plan_preparation",
            payload={"target_operation_lock": dict(lock_evidence)},
            details_patch={"target_operation_lock": dict(lock_evidence)},
            actor=actor,
            expected_statuses=["planned"],
            recovery_status="leased",
            recovery_details_patch={
                "phase": "lock_acquired",
                "target_lock_id": lock_id,
                "cluster_id": cluster_id,
            },
            bind_target_lock=True,
        )
        return operation, RecoveryLease(item=item, token=lease.token)

    def _close_unissued_without_owned_lock(
        self,
        operation: OperationSnapshot,
        lease: RecoveryLease,
        *,
        event_type: str,
        reason: str,
        observed_target_lock: Mapping[str, Any] | None,
        actor: OperationActor,
    ) -> tuple[OperationSnapshot, Any]:
        return self._commit_recovery(
            operation,
            lease,
            next_status="blocked",
            event_type=event_type,
            stage="plan_preparation",
            payload={
                "instruction_exposed": False,
                "observed_target_lock": dict(observed_target_lock or {}),
            },
            details_patch={
                "instruction_exposed": False,
                "plan_finalization": {"ready": False, "reason": reason},
            },
            actor=actor,
            expected_statuses=["planned"],
            recovery_status="completed",
            recovery_details_patch={"phase": "blocked", "terminal_outcome": "blocked"},
        )

    def _close_unissued_plan(
        self,
        operation: OperationSnapshot,
        lease: RecoveryLease,
        *,
        next_status: str,
        event_type: str,
        payload: Mapping[str, Any],
        details_patch: Mapping[str, Any],
        actor: OperationActor,
    ) -> OperationSnapshot:
        operation, _ = self._commit_recovery(
            operation,
            lease,
            next_status=next_status,
            event_type=event_type,
            stage="plan_preparation",
            payload=payload,
            details_patch=details_patch,
            actor=actor,
            expected_statuses=["planned"],
            recovery_status="completed",
            release_target_lock=True,
            recovery_details_patch={"phase": next_status},
        )
        return operation

    def _recover_waiting_expiry(
        self,
        operation: OperationSnapshot,
        lease: RecoveryLease,
        *,
        actor: OperationActor,
    ) -> dict[str, Any]:
        if self._execution_attested(operation):
            operation, _ = self._commit_recovery(
                operation,
                lease,
                next_status="needs_reconciliation",
                event_type="expiry_attestation_present",
                stage="operator_handoff",
                payload={"expires_at": operation.expires_at.isoformat() if operation.expires_at else None},
                details_patch={"reconciliation_reason": "attestation_present_at_instruction_expiry"},
                actor=actor,
                expected_statuses=["awaiting_operator"],
                recovery_status="paused",
                error_code="GUIDED_QM_ATTESTATION_PRESENT_AT_EXPIRY",
            )
            return self._result(operation)

        target = operation.details.get("target") if isinstance(operation.details.get("target"), dict) else {}
        try:
            observed = self._observe(
                node_id=str(target.get("node_id") or ""),
                vmid=int(target.get("vmid") or 0),
            )
        except GuidedQmError as exc:
            retry_status = self._retry_status(lease)
            exhausted = retry_status == "paused"
            operation, _ = self._commit_recovery(
                operation,
                lease,
                next_status="needs_reconciliation" if exhausted else None,
                event_type="expiry_observation_unavailable",
                stage="operator_handoff",
                payload={"expires_at": operation.expires_at.isoformat() if operation.expires_at else None, "code": exc.code},
                details_patch={
                    "expiry_observation": {
                        "authority": "proxmox_api",
                        "available": False,
                        "retry_exhausted": exhausted,
                    },
                    **(
                        {"reconciliation_reason": "state_unknown_at_instruction_expiry"}
                        if exhausted
                        else {}
                    ),
                },
                actor=actor,
                expected_statuses=["awaiting_operator"],
                recovery_status=retry_status,
                retry_delay_seconds=0 if exhausted else 30,
                error_code="GUIDED_QM_EXPIRY_OBSERVATION_UNAVAILABLE",
            )
            return self._result(operation)

        original_lock = self._original_config_lock(operation)
        observed_lock = str(observed.get("config_lock") or "")
        if observed.get("active_tasks"):
            reason = "active_tasks_at_instruction_expiry"
        elif not observed_lock:
            reason = "possible_external_effect_at_instruction_expiry"
        elif observed_lock != original_lock:
            reason = "config_lock_changed_at_instruction_expiry"
        else:
            reason = ""
        if reason:
            operation, _ = self._commit_recovery(
                operation,
                lease,
                next_status="needs_reconciliation",
                event_type="expiry_state_requires_reconciliation",
                stage="operator_handoff",
                payload={"expires_at": operation.expires_at.isoformat() if operation.expires_at else None, "observed": observed},
                details_patch={"reconciliation_reason": reason, "expiry_observation": observed},
                actor=actor,
                expected_statuses=["awaiting_operator"],
                recovery_status="paused",
                error_code="GUIDED_QM_EXPIRY_RECONCILIATION_REQUIRED",
            )
            return self._result(operation)

        current_lock = self._ports.locks.current(operation.target_type, operation.target_id)
        if not self._is_exact_owned_lock(operation, current_lock):
            operation, _ = self._commit_recovery(
                operation,
                lease,
                next_status="needs_reconciliation",
                event_type="expiry_target_lock_changed_after_observation",
                stage="operator_handoff",
                payload={"observed_target_lock": current_lock or {}},
                details_patch={"reconciliation_reason": "target_lock_changed_at_instruction_expiry"},
                actor=actor,
                expected_statuses=["awaiting_operator"],
                recovery_status="paused",
                error_code="GUIDED_QM_TARGET_LOCK_LOST",
            )
            return self._result(operation)

        operation, _ = self._commit_recovery(
            operation,
            lease,
            next_status="expired",
            event_type="instruction_expired",
            stage="operator_handoff",
            payload={"expires_at": operation.expires_at.isoformat() if operation.expires_at else None, "observed": observed},
            actor=actor,
            expected_statuses=["awaiting_operator"],
            recovery_status="completed",
            release_target_lock=True,
            recovery_details_patch={"phase": "expired", "expiry_observation": observed},
        )
        return self._result(operation, target_lock_released=True)

    def _recover_verification(
        self,
        operation: OperationSnapshot,
        lease: RecoveryLease,
        *,
        actor: OperationActor,
        raise_on_unavailable: bool,
    ) -> dict[str, Any]:
        if operation.status != "verifying":
            operation, item = self._commit_recovery(
                operation,
                lease,
                next_status="verifying",
                event_type="verification_started",
                stage="verification",
                payload={"plan_digest": operation.plan_digest, "authority": "proxmox_api"},
                actor=actor,
                expected_statuses=["awaiting_verification", "needs_reconciliation"],
                recovery_status="leased",
                recovery_details_patch={"phase": "verifying"},
            )
            lease = RecoveryLease(item=item, token=lease.token)

        target = operation.details.get("target") if isinstance(operation.details.get("target"), dict) else {}
        try:
            observed = self._observe(
                node_id=str(target.get("node_id") or ""),
                vmid=int(target.get("vmid") or 0),
            )
        except GuidedQmError as exc:
            operation, _ = self._commit_recovery(
                operation,
                lease,
                next_status="needs_reconciliation",
                event_type="verification_unavailable",
                stage="verification",
                payload={"code": exc.code, "message": exc.message},
                details_patch={"verification": {"verified": False, "reason": "observation_unavailable"}},
                actor=actor,
                expected_statuses=["verifying"],
                recovery_status=self._retry_status(lease),
                retry_delay_seconds=30,
                error_code="GUIDED_QM_VERIFICATION_UNAVAILABLE",
            )
            if raise_on_unavailable:
                raise GuidedQmError(
                    "GUIDED_QM_VERIFICATION_UNAVAILABLE",
                    "Proxmox API verification is unavailable; the operation requires reconciliation",
                    status_code=503,
                    details={"operation_id": operation.operation_id},
                ) from exc
            return self._result(operation)

        if observed["config_lock"] or observed["active_tasks"]:
            operation, _ = self._commit_recovery(
                operation,
                lease,
                next_status="needs_reconciliation",
                event_type="verification_mismatch",
                stage="verification",
                payload={"observed_after": observed, "expected": {"config_lock_absent": True, "active_tasks": []}},
                details_patch={
                    "verification": {
                        "verified": False,
                        "observed_after": observed,
                        "reason": "lock_or_active_task_present",
                    }
                },
                actor=actor,
                expected_statuses=["verifying"],
                recovery_status="paused",
                error_code="GUIDED_QM_VERIFICATION_MISMATCH",
            )
            return self._result(operation)

        current_lock = self._ports.locks.current(operation.target_type, operation.target_id)
        if not self._is_exact_owned_lock(operation, current_lock):
            operation, _ = self._commit_recovery(
                operation,
                lease,
                next_status="needs_reconciliation",
                event_type="verification_target_lock_changed_after_observation",
                stage="verification",
                payload={"observed_target_lock": current_lock or {}},
                details_patch={"reconciliation_reason": "target_lock_changed_during_verification"},
                actor=actor,
                expected_statuses=["verifying"],
                recovery_status="paused",
                error_code="GUIDED_QM_TARGET_LOCK_LOST",
            )
            return self._result(operation, target_lock_released=False)


        now = _as_utc(self._clock())
        operation, _ = self._commit_recovery(
            operation,
            lease,
            next_status="succeeded",
            event_type="verification_succeeded",
            stage="verification",
            payload={"observed_after": observed, "verified_at": now.isoformat()},
            details_patch={
                "verification": {
                    "verified": True,
                    "authority": "proxmox_api",
                    "observed_after": observed,
                    "verified_at": now.isoformat(),
                }
            },
            actor=actor,
            expected_statuses=["verifying"],
            recovery_status="completed",
            release_target_lock=True,
            recovery_details_patch={"phase": "succeeded", "observed_after": observed},
        )
        return self._result(operation, target_lock_released=True)

    def _observe(self, *, node_id: str, vmid: int) -> dict[str, Any]:
        try:
            complete_task_audit = self._ports.observation.has_node_task_audit(node=node_id)
            if not complete_task_audit:
                raise GuidedQmError(
                    "GUIDED_QM_TASK_AUDIT_INCOMPLETE",
                    "The Proxmox API token needs Sys.Audit on the node to prove that no VM tasks are active",
                    details={
                        "target": {"node_id": node_id, "vmid": vmid},
                        "required_proxmox_privilege": "Sys.Audit",
                        "required_proxmox_path": f"/nodes/{node_id}",
                    },
                )
            before = self._ports.observation.list_active_vm_tasks(node=node_id, vmid=vmid)
            config = self._ports.observation.get_vm_config(node=node_id, vmid=vmid)
            after = self._ports.observation.list_active_vm_tasks(node=node_id, vmid=vmid)
        except GuidedQmError:
            raise
        except GuidedQmObservationFailure as exc:
            raise GuidedQmError(
                "GUIDED_QM_OBSERVATION_UNAVAILABLE",
                "Authoritative Proxmox state could not be observed",
                status_code=503,
                details={"target": {"node_id": node_id, "vmid": vmid}},
            ) from exc
        except Exception as exc:
            raise GuidedQmError(
                "GUIDED_QM_OBSERVATION_UNAVAILABLE",
                "Authoritative Proxmox state could not be observed",
                status_code=503,
                details={"target": {"node_id": node_id, "vmid": vmid}},
            ) from exc
        return {
            "config_lock": _config_lock(config),
            "active_tasks": _compact_tasks([*before, *after]),
            "observed_at": _as_utc(self._clock()).isoformat(),
            "authority": "proxmox_api",
        }

    def _get_operation(self, operation_id: str) -> OperationSnapshot | None:
        try:
            return self._ports.operations.get(str(operation_id))
        except Exception as exc:
            raise self._persistence_error(str(operation_id)) from exc

    def _require_guided_unlock(self, operation_id: str) -> OperationSnapshot:
        operation = self._get_operation(operation_id)
        if operation is None:
            raise GuidedQmError(
                "GUIDED_QM_OPERATION_NOT_FOUND",
                "Guided qm operation was not found",
                status_code=404,
                details={"operation_id": str(operation_id)},
            )
        if operation.operation_type != GUIDED_QM_UNLOCK_OPERATION_TYPE or operation.execution_mode != "guided_manual":
            raise GuidedQmError(
                "GUIDED_QM_OPERATION_TYPE_MISMATCH",
                "The operation is not a Guided qm VM unlock",
                details={"operation_id": operation.operation_id, "operation_type": operation.operation_type},
            )
        return operation

    def _transition(self, operation_id: str, **kwargs: Any) -> OperationSnapshot:
        try:
            return self._ports.operations.transition(operation_id, **kwargs)
        except OperationStateConflict as exc:
            raise GuidedQmError(
                "GUIDED_QM_STATE_CONFLICT",
                "The Guided qm operation state changed concurrently",
                details={"operation_id": exc.operation_id, "current_status": exc.current_status},
            ) from exc
        except GuidedQmError:
            raise
        except Exception as exc:
            raise self._persistence_error(operation_id) from exc

    def _append_event(self, operation_id: str, **kwargs: Any) -> OperationSnapshot:
        try:
            return self._ports.operations.append_event(operation_id, **kwargs)
        except OperationStateConflict as exc:
            raise GuidedQmError(
                "GUIDED_QM_STATE_CONFLICT",
                "The Guided qm operation state changed concurrently",
                details={"operation_id": exc.operation_id, "current_status": exc.current_status},
            ) from exc
        except GuidedQmError:
            raise
        except Exception as exc:
            raise self._persistence_error(operation_id) from exc

    def _result(
        self,
        operation: OperationSnapshot,
        *,
        idempotent_replay: bool = False,
        target_lock_released: bool | None = None,
    ) -> dict[str, Any]:
        try:
            events = self._ports.operations.list_events(operation.operation_id)
        except Exception as exc:
            raise self._persistence_error(operation.operation_id) from exc
        result = {
            "operation": operation_payload(operation),
            "events": [operation_event_payload(event) for event in events],
            "instruction_bundle": operation.details.get("instruction_bundle"),
            "instruction_state": self._instruction_state(operation),
            "idempotent_replay": idempotent_replay,
            "backend_command_execution": False,
            "proxmox_mutation_enabled": False,
        }
        if target_lock_released is not None:
            result["target_lock_released"] = target_lock_released
        return result

    @staticmethod
    def _late_execution_attested(operation: OperationSnapshot) -> bool:
        attestation = operation.details.get("operator_attestation")
        return bool(
            isinstance(attestation, Mapping)
            and attestation.get("command_executed") is True
            and attestation.get("late") is True
        )

    def _expire_waiting_operation(self, operation: OperationSnapshot) -> OperationSnapshot:
        if operation.status != "awaiting_operator" or operation.expires_at is None:
            return operation
        if _as_utc(self._clock()) < _as_utc(operation.expires_at):
            return operation

        current_lock = self._ports.locks.current(operation.target_type, operation.target_id)
        if not self._is_exact_owned_lock(operation, current_lock):
            return self._transition(
                operation.operation_id,
                next_status="needs_reconciliation",
                event_type="expiry_target_lock_mismatch",
                stage="operator_handoff",
                payload={
                    "expires_at": operation.expires_at.isoformat(),
                    "observed_target_lock": current_lock or {},
                },
                details_patch={"reconciliation_reason": "target_lock_missing_at_instruction_expiry"},
                expected_statuses=["awaiting_operator"],
            )
        lease = self._claim_recovery(operation)
        self._recover_waiting_expiry(operation, lease, actor=_SYSTEM_RECOVERY_ACTOR)
        return self._require_guided_unlock(operation.operation_id)

    def _release_releasable_target_lock(self, target_id: str) -> None:
        current = self._ports.locks.current("proxmox_vm", target_id)
        if not current:
            return
        owner_id = str(current.get("owner_id") or "")
        owner = self._get_operation(owner_id) if owner_id else None
        if owner is None:
            return
        self._expire_waiting_operation(owner)

    def _assert_target_lock_owned(
        self,
        operation: OperationSnapshot,
        *,
        transition_on_loss: bool = False,
        exact: bool = False,
        active: bool = False,
    ) -> None:
        current = self._ports.locks.current(operation.target_type, operation.target_id)
        if active:
            owned = self._is_active_instruction_lock(operation, current)
        elif exact:
            owned = self._is_exact_owned_lock(operation, current)
        else:
            owned = bool(current) and current.get("owner_id") == operation.operation_id
        if owned:
            return
        if transition_on_loss and operation.status in {"awaiting_operator", "awaiting_verification", "verifying"}:
            self._transition(
                operation.operation_id,
                next_status="needs_reconciliation",
                event_type="target_lock_lost",
                stage=operation.current_stage,
                payload={"observed_target_lock": current or {}},
                expected_statuses=[operation.status],
            )
        raise GuidedQmError(
            "GUIDED_QM_TARGET_LOCK_LOST",
            "The retained VM target lock is missing or belongs to another operation",
            details={"operation_id": operation.operation_id, "observed_target_lock": current or {}},
        )

    def _prepare_or_claim_recovery(
        self,
        operation: OperationSnapshot,
        *,
        lock_evidence: Mapping[str, Any],
    ) -> RecoveryLease:
        recovery = self._require_recovery(operation.operation_id)
        details = self._recovery_details(operation, lock_evidence)
        try:
            item = recovery.get(operation.operation_id)
            if item is None:
                return recovery.prepare_and_claim(
                    RecoverySpec(
                        operation_id=operation.operation_id,
                        recovery_kind=_GUIDED_QM_RECOVERY_KIND,
                        details=details,
                    ),
                    lease_owner=f"guided-foreground:{operation.operation_id}",
                    lease_seconds=self._ports.recovery_lease_seconds,
                    expected_operation_version=operation.version,
                    expected_operation_checksum=operation.last_event_checksum,
                )
            return recovery.claim_operation(
                operation.operation_id,
                lease_owner=f"guided-foreground:{operation.operation_id}",
                lease_seconds=self._ports.recovery_lease_seconds,
                expected_operation_version=operation.version,
                expected_operation_checksum=operation.last_event_checksum,
            )
        except RecoveryLeaseBusy as exc:
            raise GuidedQmError(
                "GUIDED_QM_RECOVERY_BUSY",
                "Another observer currently owns the Guided qm recovery lease",
                details={"operation_id": operation.operation_id},
            ) from exc
        except RecoveryOperationConflict as exc:
            raise GuidedQmError(
                "GUIDED_QM_STATE_CONFLICT",
                "The Guided qm operation changed while recovery coordination was being claimed",
                details={"operation_id": operation.operation_id},
            ) from exc
        except GuidedQmError:
            raise
        except Exception as exc:
            raise self._recovery_error(operation.operation_id) from exc

    def _claim_recovery(self, operation: OperationSnapshot) -> RecoveryLease:
        lock_evidence = self._ports.locks.current(operation.target_type, operation.target_id) or {}
        return self._prepare_or_claim_recovery(operation, lock_evidence=lock_evidence)

    def _commit_recovery(
        self,
        operation: OperationSnapshot,
        lease: RecoveryLease,
        **kwargs: Any,
    ) -> tuple[OperationSnapshot, Any]:
        recovery = self._require_recovery(operation.operation_id)
        self._validate_recovery_lease(operation, lease)
        try:
            return recovery.commit_observation(
                lease,
                expected_operation_version=operation.version,
                expected_operation_checksum=operation.last_event_checksum,
                **kwargs,
            )
        except RecoveryOperationConflict as exc:
            raise GuidedQmError(
                "GUIDED_QM_STATE_CONFLICT",
                "The Guided qm operation changed before the recovery observation could be committed",
                details={"operation_id": operation.operation_id},
            ) from exc
        except GuidedQmError:
            raise
        except Exception as exc:
            raise self._recovery_error(operation.operation_id) from exc

    def _validate_recovery_lease(self, operation: OperationSnapshot, lease: RecoveryLease) -> None:
        details = dict(lease.item.details or {})
        expected = {
            "target_type": operation.target_type,
            "target_id": operation.target_id,
            "operation_type": operation.operation_type,
            "execution_mode": operation.execution_mode,
            "original_config_lock": self._original_config_lock(operation),
        }
        valid = lease.item.recovery_kind == _GUIDED_QM_RECOVERY_KIND and all(
            str(details.get(key) or "") == str(value) for key, value in expected.items()
        )
        if self._original_config_lock(operation) not in GUIDED_QM_UNLOCK_SUPPORTED_LOCKS:
            valid = False
        target = operation.details.get("target") if isinstance(operation.details.get("target"), Mapping) else {}
        try:
            vmid = int(target.get("vmid") or 0)
            valid = valid and operation.target_id == f"vmid:{vmid}"
            valid = valid and int(details.get("vmid") or 0) == vmid
            valid = valid and str(details.get("node_id") or "") == str(target.get("node_id") or "")
        except (TypeError, ValueError):
            valid = False
        recorded_lock = operation.details.get("target_operation_lock")
        recorded_lock_id = self._lock_id(recorded_lock) if isinstance(recorded_lock, Mapping) else ""
        lease_cluster_id = str(details.get("cluster_id") or "").strip()
        recorded_cluster_id = (
            self._lock_cluster_id(recorded_lock)
            if isinstance(recorded_lock, Mapping)
            else ""
        )
        if recorded_lock_id:
            if str(details.get("target_lock_id") or "") != recorded_lock_id:
                valid = False
            if (
                not lease_cluster_id
                or not recorded_cluster_id
                or lease_cluster_id != recorded_cluster_id
            ):
                valid = False
            current_lock = self._ports.locks.current(operation.target_type, operation.target_id)
            if current_lock is not None:
                current_cluster_id = self._lock_cluster_id(current_lock)
                if (
                    not current_cluster_id
                    or current_cluster_id != recorded_cluster_id
                    or current_cluster_id != lease_cluster_id
                ):
                    valid = False
        if not valid:
            raise GuidedQmError(
                "GUIDED_QM_RECOVERY_BINDING_MISMATCH",
                "The recovery item is not bound to the exact Guided qm operation",
                details={"operation_id": operation.operation_id},
            )

    def _recovery_details(
        self,
        operation: OperationSnapshot,
        lock_evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        target = operation.details.get("target") if isinstance(operation.details.get("target"), dict) else {}
        durable = lock_evidence.get("durable") if isinstance(lock_evidence.get("durable"), Mapping) else {}
        return {
            "target_type": operation.target_type,
            "target_id": operation.target_id,
            "operation_type": operation.operation_type,
            "execution_mode": operation.execution_mode,
            "node_id": str(target.get("node_id") or ""),
            "vmid": int(target.get("vmid") or 0),
            "target_lock_id": self._lock_id(lock_evidence),
            "cluster_id": str(durable.get("cluster_id") or ""),
            "original_config_lock": self._original_config_lock(operation),
            "phase": "lock_acquired" if self._lock_id(lock_evidence) else "plan_prepared",
            "mutation_replay_allowed": False,
            "recovery_contract": PRE_DISPATCH_RECOVERY_CONTRACT,
        }

    def _is_exact_owned_lock(
        self,
        operation: OperationSnapshot,
        current: Mapping[str, Any] | None,
        *,
        allow_unrecorded: bool = False,
    ) -> bool:
        if not current or str(current.get("owner_id") or "") != operation.operation_id:
            return False
        if current.get("target_type") not in {None, operation.target_type}:
            return False
        if current.get("target_id") not in {None, operation.target_id}:
            return False
        durable = current.get("durable") if isinstance(current.get("durable"), Mapping) else {}
        if durable and str(durable.get("operation_type") or "") != operation.operation_type:
            return False
        current_cluster_id = self._lock_cluster_id(current)
        if not current_cluster_id:
            return False
        recorded = operation.details.get("target_operation_lock")
        expected_id = self._lock_id(recorded) if isinstance(recorded, Mapping) else ""
        if not expected_id:
            return allow_unrecorded
        recorded_cluster_id = (
            self._lock_cluster_id(recorded)
            if isinstance(recorded, Mapping)
            else ""
        )
        return (
            bool(recorded_cluster_id)
            and current_cluster_id == recorded_cluster_id
            and self._lock_id(current) == expected_id
        )

    def _is_active_instruction_lock(
        self,
        operation: OperationSnapshot,
        current: Mapping[str, Any] | None,
    ) -> bool:
        """Apply stricter display authority without weakening recovery ownership."""

        if not self._is_exact_owned_lock(operation, current):
            return False
        durable = current.get("durable") if isinstance(current, Mapping) else None
        durable = durable if isinstance(durable, Mapping) else {}
        target = operation.details.get("target")
        target = target if isinstance(target, Mapping) else {}
        try:
            vmid = int(target.get("vmid") or 0)
            durable_vmid = int(durable.get("vmid") or 0)
        except (TypeError, ValueError):
            return False
        return bool(
            operation.target_type == "proxmox_vm"
            and operation.target_id == f"vmid:{vmid}"
            and vmid > 0
            and durable_vmid == vmid
            and str(durable.get("owner_id") or "") == operation.operation_id
            and str(durable.get("operation_type") or "") == operation.operation_type
            and str(durable.get("scope_type") or "") == "proxmox_locator"
            and str(durable.get("status") or "") == "active"
        )



    def _instruction_state(self, operation: OperationSnapshot) -> dict[str, Any]:
        now = _as_utc(self._clock())
        has_valid_expiry = operation.expires_at is not None
        unexpired = has_valid_expiry and now < _as_utc(operation.expires_at)
        current_lock = (
            self._ports.locks.current(operation.target_type, operation.target_id)
            if operation.status == "awaiting_operator" and unexpired
            else None
        )
        lock_matches = self._is_active_instruction_lock(operation, current_lock)
        active = (
            operation.status == "awaiting_operator"
            and unexpired
            and lock_matches
        )
        if active:
            reason = "instruction_active"
        elif operation.status == "planned":
            reason = "instruction_handoff_incomplete"
        elif operation.status == "awaiting_operator":
            if not has_valid_expiry:
                reason = "instruction_expiry_invalid"
            elif not unexpired:
                reason = "instruction_ttl_elapsed"
            elif current_lock is None:
                reason = "target_lock_lost"
            else:
                reason = "target_lock_mismatch"
        elif operation.status in {"awaiting_verification", "verifying", "succeeded"}:
            reason = "instruction_already_attested"
        elif operation.status == "needs_reconciliation":
            reason = "instruction_requires_reconciliation"
        else:
            reason = f"instruction_{operation.status}"
        return {
            "active": active,
            "historical": not active,
            "do_not_execute": not active,
            "reason": reason,
            "expires_at": operation.expires_at.isoformat() if operation.expires_at else None,
        }

    def _instruction_bundle(self, operation: OperationSnapshot) -> dict[str, Any]:
        target = operation.details.get("target") if isinstance(operation.details.get("target"), Mapping) else {}
        if operation.expires_at is None:
            raise GuidedQmError(
                "GUIDED_QM_RECOVERY_BINDING_MISMATCH",
                "The provisional Guided qm operation has no instruction expiry",
                details={"operation_id": operation.operation_id},
            )
        bundle = build_guided_qm_unlock_bundle(
            operation_id=operation.operation_id,
            node_id=str(target.get("node_id") or ""),
            vmid=int(target.get("vmid") or 0),
            expires_at=operation.expires_at,
            observed_lock=self._original_config_lock(operation),
        )
        if bundle["plan_digest"] != operation.plan_digest:
            raise GuidedQmError(
                "GUIDED_QM_RECOVERY_BINDING_MISMATCH",
                "The provisional Guided qm instruction no longer matches its durable plan digest",
                details={"operation_id": operation.operation_id},
            )
        return bundle

    def _seconds_until_expiry(self, operation: OperationSnapshot) -> float:
        if operation.expires_at is None:
            return float(self._ttl_seconds)
        return max((_as_utc(operation.expires_at) - _as_utc(self._clock())).total_seconds(), 1.0)

    @staticmethod
    def _lock_id(evidence: Mapping[str, Any]) -> str:
        durable = evidence.get("durable") if isinstance(evidence.get("durable"), Mapping) else {}
        return str(durable.get("operation_lock_id") or evidence.get("lock_id") or "").strip()

    @staticmethod
    def _lock_cluster_id(evidence: Mapping[str, Any]) -> str:
        durable = evidence.get("durable") if isinstance(evidence.get("durable"), Mapping) else {}
        return str(durable.get("cluster_id") or "").strip()

    @staticmethod
    def _original_config_lock(operation: OperationSnapshot) -> str:
        observed = operation.details.get("observed_before")
        return str(observed.get("config_lock") or "") if isinstance(observed, Mapping) else ""

    def _retry_status(self, lease: RecoveryLease) -> str:
        return "paused" if lease.item.attempt_count >= self._recovery_max_attempts else "retry_wait"

    @staticmethod
    def _target_lock_busy_error(operation_id: str, evidence: Mapping[str, Any]) -> GuidedQmError:
        return GuidedQmError(
            "GUIDED_QM_TARGET_LOCK_BUSY",
            "Another operation already owns the VM target lock",
            details={"operation_id": operation_id, "target_lock": dict(evidence)},
        )



    def _require_recovery(self, operation_id: str) -> Any:
        if self._ports.recovery is None:
            raise self._recovery_error(operation_id)
        return self._ports.recovery

    @staticmethod
    def _recovery_error(operation_id: str) -> GuidedQmError:
        return GuidedQmError(
            "GUIDED_QM_RECOVERY_UNAVAILABLE",
            "Durable Guided qm recovery coordination is unavailable",
            status_code=503,
            details={"operation_id": operation_id},
        )

    @staticmethod
    def _operator_actor(actor: Mapping[str, Any]) -> OperationActor:
        operation_actor = OperationActor.from_mapping(actor)
        if operation_actor.role not in {"operator", "admin"}:
            raise GuidedQmError(
                "GUIDED_QM_OPERATOR_REQUIRED",
                "A trusted operator or admin actor is required",
                status_code=403,
            )
        return operation_actor

    @staticmethod
    def _assert_plan_digest(operation: OperationSnapshot, plan_digest: str) -> None:
        if operation.plan_digest != plan_digest:
            raise GuidedQmError(
                "GUIDED_QM_PLAN_DIGEST_MISMATCH",
                "The submitted plan_digest does not match the issued instruction bundle",
                details={"operation_id": operation.operation_id},
            )

    @staticmethod
    def _execution_attested(operation: OperationSnapshot) -> bool:
        attestation = operation.details.get("operator_attestation")
        return isinstance(attestation, Mapping) and attestation.get("command_executed") is True

    @staticmethod
    def _assert_operation_identity(
        operation: OperationSnapshot,
        intent: Mapping[str, Any],
        target_id: str,
    ) -> None:
        if (
            operation.operation_type != GUIDED_QM_UNLOCK_OPERATION_TYPE
            or operation.execution_mode != "guided_manual"
            or operation.target_id != target_id
            or operation.intent_digest != operation_digest(intent)
        ):
            raise GuidedQmError(
                "GUIDED_QM_IDEMPOTENCY_CONFLICT",
                "The existing operation does not match the requested Guided qm intent",
                details={"operation_id": operation.operation_id},
            )

    @staticmethod
    def _state_error(operation: OperationSnapshot, *, expected: list[str]) -> GuidedQmError:
        return GuidedQmError(
            "GUIDED_QM_STATE_CONFLICT",
            "The Guided qm operation is not in an allowed state for this action",
            details={
                "operation_id": operation.operation_id,
                "current_status": operation.status,
                "expected_statuses": expected,
            },
        )

    @staticmethod
    def _persistence_error(operation_id: str) -> GuidedQmError:
        return GuidedQmError(
            "GUIDED_QM_PERSISTENCE_UNAVAILABLE",
            "Guided qm operation state could not be persisted or read",
            status_code=503,
            details={"operation_id": operation_id},
        )
