"""Guided `qm unlock` planning, operator handoff, and API verification."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence

from app.operations.core.domain import (
    OperationActor,
    OperationEvent,
    OperationIntentConflict,
    OperationSnapshot,
    OperationSpec,
    OperationStateConflict,
    TERMINAL_OPERATION_STATUSES,
    operation_digest,
)
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
    GuidedQmTargetLockHandle,
)


Clock = Callable[[], datetime]
_ACTIVE_TASK_FIELDS = ("upid", "id", "node", "type", "status", "pid", "starttime")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _operation_payload(operation: OperationSnapshot) -> dict[str, Any]:
    return {
        "operation_id": operation.operation_id,
        "operation_type": operation.operation_type,
        "execution_mode": operation.execution_mode,
        "status": operation.status,
        "target_type": operation.target_type,
        "target_id": operation.target_id,
        "idempotency_key": operation.idempotency_key,
        "intent_digest": operation.intent_digest,
        "plan_digest": operation.plan_digest,
        "current_stage": operation.current_stage,
        "actor": operation.actor.to_dict(),
        "details": dict(operation.details),
        "expires_at": operation.expires_at.isoformat() if operation.expires_at else None,
        "version": operation.version,
        "last_event_checksum": operation.last_event_checksum,
        "created_at": operation.created_at.isoformat(),
        "updated_at": operation.updated_at.isoformat(),
    }


def _event_payload(event: OperationEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "operation_id": event.operation_id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "from_status": event.from_status,
        "to_status": event.to_status,
        "stage": event.stage,
        "actor": event.actor.to_dict(),
        "payload": dict(event.payload),
        "previous_checksum": event.previous_checksum,
        "checksum": event.checksum,
        "created_at": event.created_at.isoformat(),
    }


def _compact_tasks(tasks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    seen: set[str] = set()
    for task in tasks:
        entry = {key: task[key] for key in _ACTIVE_TASK_FIELDS if key in task}
        identity = str(entry.get("upid") or entry)
        if identity in seen:
            continue
        seen.add(identity)
        compact.append(entry)
        if len(compact) >= 10:
            break
    return compact


def _config_lock(config: Mapping[str, Any]) -> str:
    value = config.get("lock")
    return str(value).strip() if value is not None else ""


class GuidedQmUnlockUseCase:
    """Coordinate a manual `qm unlock` without executing a shell command."""

    def __init__(
        self,
        *,
        ports: GuidedQmExecutionPorts,
        clock: Clock = _utc_now,
        ttl_seconds: int = GUIDED_QM_UNLOCK_TTL_SECONDS,
    ) -> None:
        self._ports = ports
        self._clock = clock
        self._ttl_seconds = max(int(ttl_seconds), 1)

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
            existing = self._expire_waiting_operation(existing)
            if existing.status == "awaiting_operator":
                self._assert_target_lock_owned(existing)
            return self._result(existing, idempotent_replay=True)

        self._release_releasable_target_lock(command.target_id)
        lock_handle = self._acquire_target_lock(command.target_id, command.operation_id)
        try:
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
                initial_status="awaiting_operator",
                initial_stage="operator_handoff",
                expires_at=expires_at,
                details={
                    "target": command.intent["target"],
                    "instruction_bundle": bundle,
                    "observed_before": observed,
                    "target_operation_lock": lock_handle.evidence,
                },
            )
            try:
                created = self._ports.operations.create(
                    spec,
                    event_payload={
                        "template_id": bundle["template_id"],
                        "target": bundle["target"],
                        "instruction_bundle": bundle,
                        "observed_before": observed,
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
        except Exception:
            self._ports.locks.release(lock_handle)
            raise
        return self._result(created.operation, idempotent_replay=not created.created)

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
        self._assert_target_lock_owned(operation, transition_on_loss=True)

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
        self._assert_target_lock_owned(operation, transition_on_loss=True)

        if operation.status != "verifying":
            operation = self._transition(
                operation.operation_id,
                next_status="verifying",
                event_type="verification_started",
                stage="verification",
                payload={"plan_digest": operation.plan_digest, "authority": "proxmox_api"},
                actor=actor,
                expected_statuses=["awaiting_verification", "needs_reconciliation"],
            )
        target = operation.details.get("target") if isinstance(operation.details.get("target"), dict) else {}
        node_id = str(target.get("node_id") or "")
        vmid = int(target.get("vmid") or 0)
        try:
            observed = self._observe(node_id=node_id, vmid=vmid)
        except GuidedQmError as exc:
            self._transition(
                operation.operation_id,
                next_status="needs_reconciliation",
                event_type="verification_unavailable",
                stage="verification",
                payload={"code": exc.code, "message": exc.message},
                details_patch={"verification": {"verified": False, "reason": "observation_unavailable"}},
                actor=actor,
                expected_statuses=["verifying"],
            )
            raise GuidedQmError(
                "GUIDED_QM_VERIFICATION_UNAVAILABLE",
                "Proxmox API verification is unavailable; the operation requires reconciliation",
                status_code=503,
                details={"operation_id": operation.operation_id},
            ) from exc

        verified = not observed["config_lock"] and not observed["active_tasks"]
        if not verified:
            operation = self._transition(
                operation.operation_id,
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
            )
            return self._result(operation)

        now = _as_utc(self._clock())
        operation = self._transition(
            operation.operation_id,
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
        )
        released = self._ports.locks.release_owned(
            operation.target_type,
            operation.target_id,
            operation.operation_id,
        )
        return self._result(operation, target_lock_released=released)

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
        except GuidedQmObservationFailure as exc:
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
            "operation": _operation_payload(operation),
            "events": [_event_payload(event) for event in events],
            "instruction_bundle": operation.details.get("instruction_bundle"),
            "idempotent_replay": idempotent_replay,
            "backend_command_execution": False,
            "proxmox_mutation_enabled": False,
        }
        if target_lock_released is not None:
            result["target_lock_released"] = target_lock_released
        return result

    def _expire_waiting_operation(self, operation: OperationSnapshot) -> OperationSnapshot:
        if operation.status != "awaiting_operator" or operation.expires_at is None:
            return operation
        if _as_utc(self._clock()) < _as_utc(operation.expires_at):
            return operation

        current_lock = self._ports.locks.current(operation.target_type, operation.target_id)
        if not current_lock or current_lock.get("owner_id") != operation.operation_id:
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

        target = operation.details.get("target") if isinstance(operation.details.get("target"), dict) else {}
        try:
            observed = self._observe(
                node_id=str(target.get("node_id") or ""),
                vmid=int(target.get("vmid") or 0),
            )
        except GuidedQmError as exc:
            return self._transition(
                operation.operation_id,
                next_status="needs_reconciliation",
                event_type="expiry_observation_unavailable",
                stage="operator_handoff",
                payload={"expires_at": operation.expires_at.isoformat(), "code": exc.code},
                details_patch={"reconciliation_reason": "state_unknown_at_instruction_expiry"},
                expected_statuses=["awaiting_operator"],
            )

        if not observed["config_lock"] or observed["active_tasks"]:
            return self._transition(
                operation.operation_id,
                next_status="needs_reconciliation",
                event_type="expiry_state_requires_reconciliation",
                stage="operator_handoff",
                payload={"expires_at": operation.expires_at.isoformat(), "observed": observed},
                details_patch={
                    "reconciliation_reason": "possible_external_effect_at_instruction_expiry",
                    "expiry_observation": observed,
                },
                expected_statuses=["awaiting_operator"],
            )

        expired = self._transition(
            operation.operation_id,
            next_status="expired",
            event_type="instruction_expired",
            stage="operator_handoff",
            payload={"expires_at": operation.expires_at.isoformat()},
            expected_statuses=["awaiting_operator"],
        )
        self._ports.locks.release_owned(expired.target_type, expired.target_id, expired.operation_id)
        return expired

    def _release_releasable_target_lock(self, target_id: str) -> None:
        current = self._ports.locks.current("proxmox_vm", target_id)
        if not current:
            return
        owner_id = str(current.get("owner_id") or "")
        owner = self._get_operation(owner_id) if owner_id else None
        if owner is None:
            return
        owner = self._expire_waiting_operation(owner)
        if owner.status in TERMINAL_OPERATION_STATUSES:
            self._ports.locks.release_owned("proxmox_vm", target_id, owner_id)

    def _acquire_target_lock(self, target_id: str, operation_id: str) -> GuidedQmTargetLockHandle:
        try:
            return self._ports.locks.acquire("proxmox_vm", target_id, operation_id)
        except GuidedQmTargetLockBusy as exc:
            raise GuidedQmError(
                "GUIDED_QM_TARGET_LOCK_BUSY",
                "Another operation already owns the VM target lock",
                details={"operation_id": operation_id, "target_lock": exc.evidence},
            ) from exc

    def _assert_target_lock_owned(self, operation: OperationSnapshot, *, transition_on_loss: bool = False) -> None:
        current = self._ports.locks.current(operation.target_type, operation.target_id)
        if current and current.get("owner_id") == operation.operation_id:
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
