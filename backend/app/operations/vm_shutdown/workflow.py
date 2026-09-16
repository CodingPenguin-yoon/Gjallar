"""Verified graceful VM Shutdown application workflow."""

from __future__ import annotations

from typing import Any, NoReturn

from app.operations.core.domain import OperationIntentConflict, OperationStateConflict
from app.operations.locks.domain import locator_scope_key
from app.operations.recovery.domain import (
    PRE_DISPATCH_RECOVERY_CONTRACT,
    RecoveryLease,
    RecoveryLeaseLost,
    RecoveryOperationConflict,
    RecoverySpec,
    is_pre_dispatch_terminal_no_effect,
)
from app.operations.vm_shutdown.domain import (
    VmShutdownCommand,
    build_vm_shutdown_job_id,
    vm_shutdown_target,
    vm_shutdown_target_lock_id,
)
from app.operations.vm_shutdown.errors import VmShutdownError
from app.operations.vm_shutdown.ports import (
    VmShutdownEvidencePort,
    VmShutdownExecutionPorts,
    VmShutdownJobPort,
    VmShutdownMutationFailure,
    VmShutdownMutationPort,
    VmShutdownTargetLockBusy,
    VmShutdownTargetLockHandle,
)
from app.operations.core.evidence import (
    compact_proxmox_connection_evidence,
    compact_proxmox_error_details,
    compact_proxmox_task,
    compact_proxmox_vm_status,
)
from app.operations.vm_shutdown.precheck import VmShutdownPrecheckBlocked, evaluate_vm_shutdown_precheck, normalize_vm_status
from app.operations.vm_shutdown.tracking import prepare_vm_shutdown_operation, transition_vm_shutdown_operation


def _target_id(node_id: str, vmid: int, name: str = "") -> str:
    suffix = f":{name}" if name else ""
    return f"{node_id}:{int(vmid)}{suffix}"


def _actor_fields(actor: dict[str, Any] | None) -> dict[str, Any]:
    if not actor:
        return {}
    evidence = {
        "user_id": str(actor.get("user_id") or ""),
        "username": str(actor.get("username") or ""),
        "role": str(actor.get("role") or ""),
    }
    return {
        "actor": evidence,
        "actor_user_id": evidence["user_id"],
        "actor_username": evidence["username"],
        "actor_role": evidence["role"],
    }


def _record_job(
    *,
    jobs: VmShutdownJobPort,
    job_id: str,
    status: str,
    stage: str,
    step_status: str,
    message: str,
    target: dict[str, Any],
    details: dict[str, Any] | None = None,
    artifacts: list[Any] | None = None,
    actor: dict[str, Any] | None = None,
    intent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {"target": target, **(details or {})}
    if intent is not None:
        payload["vm_shutdown_intent"] = dict(intent)
    payload.update(_actor_fields(actor))
    return jobs.record(
        job_id=job_id,
        job_type="vm_shutdown",
        status=status,
        target_id=_target_id(
            str(target.get("node_id") or ""),
            int(target.get("vmid") or 0),
            str(target.get("name") or ""),
        ),
        risk_level="high",
        stage=stage,
        step_status=step_status,
        message=message,
        artifacts=artifacts,
        risks=[],
        details=payload,
    )


def _stored_intent(job: dict[str, Any]) -> dict[str, Any]:
    details = job.get("details") if isinstance(job.get("details"), dict) else {}
    value = details.get("vm_shutdown_intent")
    return dict(value) if isinstance(value, dict) else {}


def _ensure_replay_matches(job: dict[str, Any], requested_intent: dict[str, Any]) -> None:
    stored = _stored_intent(job)
    if not stored or stored == requested_intent:
        return
    raise VmShutdownError(
        "VM_SHUTDOWN_IDEMPOTENCY_CONFLICT",
        "The idempotency key already belongs to a different VM shutdown intent",
        details={
            "job_id": job.get("job_id"),
            "existing_intent": stored,
            "requested_intent": requested_intent,
            "proxmox_mutation_enabled": False,
            "side_effects": [],
        },
    )


def _existing_result(job: dict[str, Any]) -> dict[str, Any]:
    details = job.get("details") if isinstance(job.get("details"), dict) else {}
    stored = details.get("vm_shutdown_result") if isinstance(details.get("vm_shutdown_result"), dict) else {}
    target = details.get("target") if isinstance(details.get("target"), dict) else stored.get("target", {})
    return {
        **stored,
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "target": target,
        "idempotent_replay": True,
        "proxmox_mutation_enabled": False,
        "proxmox_mutation_ran_previously": stored.get("proxmox_mutation_enabled") is True,
        "message": job.get("message") or stored.get("message") or "Existing VM shutdown job returned",
    }


def _is_recoverable_pre_dispatch_terminal_replay(
    job: dict[str, Any],
    operation: Any,
) -> bool:
    if operation is None or operation.status != "planned":
        return False
    if operation.details.get("recovery_contract") != PRE_DISPATCH_RECOVERY_CONTRACT:
        return False
    details = job.get("details") if isinstance(job.get("details"), dict) else {}
    result = details.get("vm_shutdown_result") if isinstance(details.get("vm_shutdown_result"), dict) else {}
    return bool(
        job.get("status") == "failed"
        and result.get("proxmox_shutdown_ran") is False
        and result.get("proxmox_mutation_enabled") is False
        and (
            result.get("pre_dispatch_no_effect_verified") is True
            or result.get("pre_dispatch_file_guard_cleaned") is True
        )
    )


def _terminal_pre_dispatch_replay_matches(
    ports: VmShutdownExecutionPorts,
    *,
    job_id: str,
    vmid: int,
    durable: dict[str, Any],
) -> bool:
    current = ports.operations.get(job_id)
    return bool(
        current is not None
        and current.operation_type == "vm_shutdown"
        and current.status == "failed"
        and current.target_type == "proxmox_vm"
        and current.target_id == vm_shutdown_target_lock_id(vmid)
        and current.details.get("target_lock_id") == durable.get("operation_lock_id")
        and current.details.get("cluster_id") == durable.get("cluster_id")
        and is_pre_dispatch_terminal_no_effect(
            operation_type=current.operation_type,
            status=current.status,
            details=current.details,
        )
    )


def _close_replayed_pre_dispatch_failure(
    *,
    ports: VmShutdownExecutionPorts,
    job_id: str,
    node_id: str,
    vmid: int,
    job: dict[str, Any],
    operation: Any,
    lock: dict[str, Any],
) -> dict[str, Any]:
    durable = (
        dict(lock.get("durable") or {})
        if isinstance(lock.get("durable"), dict)
        else dict(lock.get("existing") or {})
        if isinstance(lock.get("existing"), dict)
        else {}
    )
    if (
        ports.recovery is None
        or str(durable.get("owner_id") or "") != job_id
        or str(durable.get("operation_type") or "") != "vm_shutdown"
        or int(durable.get("vmid") or 0) != vmid
    ):
        raise VmShutdownError(
            "VM_SHUTDOWN_OPERATION_RECONCILIATION_REQUIRED",
            "The terminal VM shutdown job could not be fenced to its exact pre-dispatch target lock",
            status_code=503,
            details={
                "job_id": job_id,
                "target": vm_shutdown_target(node_id=node_id, vmid=vmid),
                "target_operation_lock": lock,
                "proxmox_mutation_enabled": False,
                "side_effects": [],
            },
        )
    try:
        terminal_status = operation.status in {"failed", "blocked"}
        terminal_outcome = operation.status if terminal_status else "failed"
        terminal_details = (
            {
                "pre_dispatch_terminal_no_effect": True,
                "mutation_dispatched": False,
                "pre_dispatch_terminal_reason": operation.details["pre_dispatch_terminal_reason"],
                "recovery_contract": PRE_DISPATCH_RECOVERY_CONTRACT,
            }
            if terminal_status
            else {}
        )
        lease = ports.recovery.prepare_and_claim(
            RecoverySpec(
                operation_id=job_id,
                recovery_kind="vm_shutdown_observation",
                details={
                    "node_id": node_id,
                    "vmid": vmid,
                    "target_type": "proxmox_vm",
                    "target_id": vm_shutdown_target_lock_id(vmid),
                    "operation_type": "vm_shutdown",
                    "execution_mode": "managed_api",
                    "phase": "pre_dispatch",
                    "target_lock_id": str(durable.get("operation_lock_id") or ""),
                    "cluster_id": str(durable.get("cluster_id") or ""),
                    "terminal_outcome": terminal_outcome,
                    **terminal_details,
                },
            ),
            lease_owner=f"replay:{job_id}",
            lease_seconds=ports.recovery_lease_seconds,
            expected_operation_version=operation.version,
            expected_operation_checksum=operation.last_event_checksum,
        )
        ports.recovery.commit_observation(
            lease,
            next_status=None if terminal_status else "failed",
            event_type="replayed_pre_dispatch_failure_closed",
            stage="reconciliation",
            payload={"mutation_dispatched": False, "compatibility_projection": terminal_outcome},
            details_patch={"result_status": terminal_outcome, "recovered_pre_dispatch": True},
            expected_statuses=[operation.status],
            recovery_status="completed",
            recovery_details_patch={"terminal_outcome": terminal_outcome},
            release_target_lock=True,
            expected_operation_version=operation.version,
            expected_operation_checksum=operation.last_event_checksum,
        )
    except Exception as exc:
        if isinstance(exc, (OperationStateConflict, RecoveryOperationConflict)) and _terminal_pre_dispatch_replay_matches(
            ports, job_id=job_id, vmid=vmid, durable=durable,
        ):
            return _existing_result(job)
        raise VmShutdownError(
            "VM_SHUTDOWN_OPERATION_RECONCILIATION_REQUIRED",
            "The terminal VM shutdown job could not close its canonical pre-dispatch recovery",
            status_code=503,
            details={
                "job_id": job_id,
                "target": vm_shutdown_target(node_id=node_id, vmid=vmid),
                "target_operation_lock": lock,
                "proxmox_mutation_enabled": False,
                "side_effects": [],
            },
        ) from exc
    return _existing_result(job)


def _validate_request(command: VmShutdownCommand) -> tuple[str, str]:
    idempotency_key = str(command.payload.get("idempotency_key") or "").strip()
    if command.payload.get("vm_shutdown_acknowledged") is not True:
        raise VmShutdownError(
            "VM_SHUTDOWN_ACK_REQUIRED",
            "vm_shutdown_acknowledged=true is required before shutting down a VM",
            details={
                "target": vm_shutdown_target(node_id=command.node_id, vmid=command.vmid),
                "proxmox_mutation_enabled": False,
                "side_effects": [],
            },
        )
    if not idempotency_key:
        raise VmShutdownError(
            "VM_SHUTDOWN_IDEMPOTENCY_KEY_REQUIRED",
            "A non-empty idempotency_key is required before shutting down a VM",
            details={
                "target": vm_shutdown_target(node_id=command.node_id, vmid=command.vmid),
                "proxmox_mutation_enabled": False,
                "side_effects": [],
            },
        )
    return idempotency_key, build_vm_shutdown_job_id(
        node_id=command.node_id,
        vmid=command.vmid,
        idempotency_key=idempotency_key,
    )


def _lock_evidence(handle: VmShutdownTargetLockHandle | None, *, retained: bool = False) -> dict[str, Any]:
    if handle is None:
        return {}
    result = dict(handle.evidence)
    result["status"] = "reconciliation_required" if retained else "active"
    return result


def _required_target_lock_binding(
    handle: VmShutdownTargetLockHandle | None,
    *,
    operation_id: str,
    vmid: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    lock = _lock_evidence(handle)
    durable = dict(lock.get("durable") or {}) if isinstance(lock.get("durable"), dict) else {}
    cluster_id = str(durable.get("cluster_id") or "").strip()
    try:
        durable_vmid = int(durable.get("vmid") or 0)
    except (TypeError, ValueError, OverflowError):
        durable_vmid = 0
    if (
        str(lock.get("target_type") or "") != "proxmox_vm"
        or str(lock.get("target_id") or "") != vm_shutdown_target_lock_id(vmid)
        or str(lock.get("owner_id") or "") != operation_id
        or not str(lock.get("lock_id") or "").strip()
        or not str(durable.get("operation_lock_id") or "").strip()
        or str(durable.get("operation_type") or "") != "vm_shutdown"
        or str(durable.get("owner_id") or "") != operation_id
        or str(durable.get("scope_type") or "") != "proxmox_locator"
        or str(durable.get("scope_key") or "") != locator_scope_key(cluster_id, vmid)
        or str(durable.get("status") or "") != "active"
        or not cluster_id
        or durable_vmid != vmid
    ):
        raise ValueError("VM shutdown target lock binding is not exact")
    return lock, durable


def _pre_dispatch_terminal_no_effect_marker(
    handle: VmShutdownTargetLockHandle | None,
    *,
    reason: str,
) -> dict[str, Any]:
    lock = _lock_evidence(handle)
    durable = dict(lock.get("durable") or {}) if isinstance(lock.get("durable"), dict) else {}
    return {
        "pre_dispatch_terminal_no_effect": True,
        "mutation_dispatched": False,
        "pre_dispatch_terminal_reason": reason,
        "target_lock_id": str(durable.get("operation_lock_id") or ""),
        "cluster_id": str(durable.get("cluster_id") or ""),
    }








def _conflicting_operation_id(lock: dict[str, Any]) -> str | None:
    existing = lock.get("existing") if isinstance(lock.get("existing"), dict) else {}
    operation_id = str(existing.get("owner_id") or existing.get("operation_id") or "").strip()
    return operation_id or None


def _compact_task(task: dict[str, Any], *, node_id: str, upid: str) -> dict[str, Any]:
    return compact_proxmox_task(task, node=node_id, upid=upid)


def _compact_status(observed: dict[str, Any], *, node_id: str, vmid: int) -> dict[str, Any]:
    result = compact_proxmox_vm_status(observed, node=node_id, vmid=vmid)
    result["error"] = (
        "proxmox_vm_status_observation_unavailable"
        if observed.get("error")
        else ""
    )
    return result


def _status_payload(payload: Any, *, error: str | None = None) -> dict[str, Any]:
    result = dict(payload) if isinstance(payload, dict) else {}
    if error:
        result["error"] = error
    return result


def _write_artifact(
    *,
    evidence: VmShutdownEvidencePort,
    job_id: str,
    target: dict[str, Any],
    idempotency_key: str,
    expected: dict[str, Any],
    observed_before: dict[str, Any],
    task: dict[str, Any],
    observed_after: dict[str, Any],
    client: VmShutdownMutationPort,
    actor: dict[str, Any] | None,
) -> dict[str, Any]:
    node_id = str(target.get("node_id") or "")
    vmid = int(target.get("vmid") or 0)
    payload = {
        "job_id": job_id,
        "operation": "vm_shutdown",
        "target": target,
        "idempotency_key": idempotency_key,
        "expected": expected,
        "observed_before": observed_before,
        "task": _compact_task(task, node_id=node_id, upid=str(task.get("upid") or "")),
        "observed_after": _compact_status(observed_after, node_id=node_id, vmid=vmid),
        "evidence": {
            "connection": compact_proxmox_connection_evidence(
                client.redacted_connection_context()
            ),
            "observation_kinds": ["vm_shutdown", "task_status", "vm_status"],
            "forced_stop_enabled": False,
        },
    }
    payload.update(_actor_fields(actor))
    return evidence.write_json(
        job_id=job_id,
        artifact_type="vm_shutdown_observed_after",
        filename="vm_shutdown_observed_after.json",
        payload=payload,
    )


def _persistence_failure_handoff(
    *,
    ports: VmShutdownExecutionPorts,
    recovery_lease: RecoveryLease | None,
    job_id: str,
    code: str,
    message: str,
    event_type: str,
    stage: str,
    target: dict[str, Any],
    operation_status: str,
    side_effects: list[str],
    evidence_status: str,
    evidence_recorded: bool,
    target_lock: VmShutdownTargetLockHandle | None,
    task: dict[str, Any] | None = None,
    observed_after: dict[str, Any] | None = None,
    artifact: dict[str, Any] | None = None,
    next_status: str | None = None,
    recovery_error_code: str | None = None,
    recovery_status: str = "retry_wait",
) -> NoReturn:
    """Return a stable recovery handoff without replaying VM shutdown."""

    node_id = str(target.get("node_id") or "")
    vmid = int(target.get("vmid") or 0)
    task_payload = _compact_task(task or {}, node_id=node_id, upid=str((task or {}).get("upid") or ""))
    observed_payload = _compact_status(observed_after or {}, node_id=node_id, vmid=vmid)
    committed_operation: Any = None
    committed_recovery: Any = None
    effective_operation_status = operation_status
    effective_recovery_status = "unavailable"
    stored_recovery_error = recovery_error_code or code
    if ports.recovery is not None and recovery_lease is not None:
        try:
            committed_operation, committed_recovery = ports.recovery.commit_observation(
                recovery_lease,
                next_status=next_status,
                event_type=event_type,
                stage=stage,
                payload={
                    "code": code,
                    "evidence_status": evidence_status,
                    "side_effects": side_effects,
                },
                details_patch={
                    "reconciliation_code": code,
                    "evidence_status": evidence_status,
                },
                expected_statuses=[operation_status],
                recovery_status=recovery_status,
                retry_delay_seconds=0,
                error_code=stored_recovery_error,
                recovery_details_patch={
                    "phase": stage,
                    "evidence_status": evidence_status,
                    "evidence_error_code": code,
                    "task": task_payload,
                    "observed_after": observed_payload,
                },
            )
            effective_operation_status = committed_operation.status
            effective_recovery_status = committed_recovery.status
        except Exception:
            try:
                current_recovery = ports.recovery.get(job_id)
            except Exception:
                current_recovery = None
            if current_recovery is not None:
                effective_recovery_status = current_recovery.status
    elif next_status is not None:
        try:
            committed_operation = transition_vm_shutdown_operation(
                ports.operations,
                job_id,
                next_status=next_status,
                event_type=event_type,
                stage=stage,
                payload={
                    "code": code,
                    "evidence_status": evidence_status,
                    "side_effects": side_effects,
                },
                details_patch={
                    "reconciliation_code": code,
                    "evidence_status": evidence_status,
                },
                expected_statuses=[operation_status],
            )
            effective_operation_status = committed_operation.status
        except Exception:
            pass

    if committed_operation is None:
        try:
            committed_operation = ports.operations.get(job_id)
        except Exception:
            committed_operation = None
    try:
        compatibility_job = ports.jobs.get(job_id)
    except Exception:
        compatibility_job = None
    details = {
        "operation_id": job_id,
        "job_id": job_id,
        "status": effective_operation_status,
        "operation_status": effective_operation_status,
        "operation_version": getattr(committed_operation, "version", None),
        "operation_checksum": getattr(committed_operation, "last_event_checksum", None),
        "recovery_status": effective_recovery_status,
        "recovery_error_code": stored_recovery_error,
        "compatibility_job_status": (
            str(compatibility_job.get("status") or "")
            if isinstance(compatibility_job, dict)
            else "unavailable"
        ),
        "target": target,
        "target_operation_lock": _lock_evidence(target_lock, retained=True),
        "task": task_payload,
        "observed_after": observed_payload,
        "evidence_status": evidence_status,
        "evidence_recorded": evidence_recorded,
        "observed_after_artifact": artifact or {},
        "reconciliation_required": True,
        "proxmox_shutdown_ran": True,
        "proxmox_mutation_enabled": False,
        "forced_stop_enabled": False,
        "side_effects": side_effects,
    }
    raise VmShutdownError(code, message, status_code=503, details=details) from None


def _write_artifact_or_handoff(
    *,
    ports: VmShutdownExecutionPorts,
    recovery_lease: RecoveryLease | None,
    job_id: str,
    target: dict[str, Any],
    idempotency_key: str,
    expected: dict[str, Any],
    observed_before: dict[str, Any],
    task: dict[str, Any],
    observed_after: dict[str, Any],
    client: VmShutdownMutationPort,
    actor: dict[str, Any] | None,
    operation_status: str,
    stage: str,
    side_effects: list[str],
    target_lock: VmShutdownTargetLockHandle | None,
) -> dict[str, Any]:
    try:
        return _write_artifact(
            evidence=ports.evidence,
            job_id=job_id,
            target=target,
            idempotency_key=idempotency_key,
            expected=expected,
            observed_before=observed_before,
            task=task,
            observed_after=observed_after,
            client=client,
            actor=actor,
        )
    except Exception:
        upid = str(task.get("upid") or "").strip()
        _persistence_failure_handoff(
            ports=ports,
            recovery_lease=recovery_lease,
            job_id=job_id,
            code="VM_SHUTDOWN_OBSERVED_EVIDENCE_PERSISTENCE_UNAVAILABLE",
            message=(
                "VM shutdown external observations were recorded canonically, but the observed-after "
                "artifact could not be persisted"
            ),
            event_type="observed_evidence_persistence_failed",
            stage=stage,
            target=target,
            operation_status=operation_status,
            next_status="needs_reconciliation",
            recovery_status="retry_wait" if upid else "paused",
            recovery_error_code=(
                "VM_SHUTDOWN_OBSERVED_EVIDENCE_PERSISTENCE_UNAVAILABLE"
                if upid
                else "VM_SHUTDOWN_RECOVERY_TASK_REFERENCE_MISSING"
            ),
            side_effects=side_effects,
            evidence_status="persistence_failed",
            evidence_recorded=False,
            target_lock=target_lock,
            task=task,
            observed_after=observed_after,
        )


def _raise_precheck(
    *,
    ports: VmShutdownExecutionPorts,
    job_id: str,
    blocked: VmShutdownPrecheckBlocked,
    actor: dict[str, Any],
    intent: dict[str, Any],
    lock_handle: VmShutdownTargetLockHandle | None,
) -> NoReturn:
    no_effect = _pre_dispatch_terminal_no_effect_marker(
        lock_handle,
        reason="precheck_blocked",
    )
    transition_vm_shutdown_operation(
        ports.operations,
        job_id,
        next_status="blocked",
        event_type="precheck_blocked",
        stage="precheck",
        payload={
            "code": blocked.code,
            "expected": blocked.expected,
            "observed_before": blocked.observed_before,
            **no_effect,
        },
        details_patch=no_effect,
        expected_statuses=["planned"],
    )
    _record_job(
        jobs=ports.jobs,
        job_id=job_id,
        status="blocked",
        stage="precheck",
        step_status="blocked",
        message=blocked.message,
        target=blocked.target,
        actor=actor,
        intent=intent,
        details={
            "vm_shutdown": {
                "code": blocked.code,
                "expected": blocked.expected,
                "observed_before": blocked.observed_before,
                "proxmox_mutation_enabled": False,
            }
        },
    )
    raise VmShutdownError(
        blocked.code,
        blocked.message,
        details={
            "job_id": job_id,
            "target": blocked.target,
            "observed_before": blocked.observed_before,
            "proxmox_mutation_enabled": False,
            "side_effects": [],
        },
    ) from blocked


def _is_clear_4xx_rejection(exc: VmShutdownMutationFailure) -> bool:
    try:
        status_code = int(exc.details.get("status_code"))
    except (TypeError, ValueError):
        return False
    return 400 <= status_code < 500 and status_code not in {408, 425, 429}


def _raise_recovery_lease_lost(
    exc: RecoveryLeaseLost,
    *,
    job_id: str,
    target: dict[str, Any],
    message: str,
    side_effects: list[str],
) -> NoReturn:
    raise VmShutdownError(
        "VM_SHUTDOWN_RECOVERY_LEASE_LOST",
        message,
        status_code=503,
        details={
            "job_id": job_id,
            "target": target,
            "reconciliation_required": True,
            "side_effects": side_effects,
        },
    ) from exc


def _record_reconciliation(
    *,
    ports: VmShutdownExecutionPorts,
    lease: RecoveryLease | None,
    job_id: str,
    code: str,
    message: str,
    stage: str,
    target: dict[str, Any],
    intent: dict[str, Any],
    idempotency_key: str,
    expected: dict[str, Any],
    observed_before: dict[str, Any],
    task: dict[str, Any],
    observed_after: dict[str, Any],
    artifact: dict[str, Any] | None,
    upid: str,
    side_effects: list[str],
    lock_handle: VmShutdownTargetLockHandle | None,
    actor: dict[str, Any],
) -> NoReturn:
    lock = _lock_evidence(lock_handle, retained=True)
    transition_payload = {
        "code": code,
        "message": message,
        "task": _compact_task(task, node_id=str(target.get("node_id") or ""), upid=upid),
        "observed_after": _compact_status(
            observed_after,
            node_id=str(target.get("node_id") or ""),
            vmid=int(target.get("vmid") or 0),
        ),
        "side_effects": side_effects,
    }
    if ports.recovery is not None and lease is not None:
        try:
            ports.recovery.commit_observation(
                lease,
                next_status="needs_reconciliation",
                event_type="reconciliation_required",
                stage=stage,
                payload=transition_payload,
                details_patch={"reconciliation_code": code},
                expected_statuses=["dispatching", "running", "verifying"],
                recovery_status="paused" if not upid else "retry_wait",
                retry_delay_seconds=30 if upid else 0,
                error_code=code,
                recovery_details_patch={
                    "upid": upid,
                    "node_id": target.get("node_id"),
                    "vmid": target.get("vmid"),
                    "task": transition_payload["task"],
                    "observed_after": transition_payload["observed_after"],
                },
            )
        except RecoveryLeaseLost as exc:
            raise VmShutdownError(
                "VM_SHUTDOWN_RECOVERY_LEASE_LOST",
                "VM shutdown recovery ownership changed; the result was not committed",
                status_code=503,
                details={"job_id": job_id, "target": target, "side_effects": side_effects},
            ) from exc
    else:
        transition_vm_shutdown_operation(
            ports.operations,
            job_id,
            next_status="needs_reconciliation",
            event_type="reconciliation_required",
            stage=stage,
            payload=transition_payload,
            details_patch={"reconciliation_code": code},
            expected_statuses=["dispatching", "running", "verifying"],
        )
    result = {
        "job_id": job_id,
        "status": "needs_reconciliation",
        "code": code,
        "message": message,
        "target": target,
        "task": transition_payload["task"],
        "upid": upid,
        "observed_before": observed_before,
        "observed_after": transition_payload["observed_after"],
        "observed_after_artifact": artifact or {},
        "artifacts": [artifact] if artifact else [],
        "idempotency_key": idempotency_key,
        "reconciliation_required": True,
        "target_operation_lock": lock,
        "proxmox_mutation_enabled": True,
        "side_effects": side_effects,
    }
    _record_job(
        jobs=ports.jobs,
        job_id=job_id,
        status="needs_reconciliation",
        stage=stage,
        step_status="needs_reconciliation",
        message=message,
        target=target,
        artifacts=[artifact] if artifact else [],
        actor=actor,
        intent=intent,
        details={
            "vm_shutdown_result": result,
            "target_operation_lock": lock,
        },
    )
    raise VmShutdownError(code, message, details={**result, "proxmox_shutdown_ran": True})


def _execute(command: VmShutdownCommand, ports: VmShutdownExecutionPorts) -> dict[str, Any]:
    node_id = command.node_id
    vmid = command.vmid
    actor = dict(command.actor)
    idempotency_key, job_id = _validate_request(command)
    intent = command.stable_intent
    existing = ports.jobs.get(job_id)
    if existing:
        _ensure_replay_matches(existing, intent)
        existing_operation = ports.operations.get(job_id)
        if not _is_recoverable_pre_dispatch_terminal_replay(existing, existing_operation):
            return _existing_result(existing)

    try:
        prepared = prepare_vm_shutdown_operation(
            ports.operations,
            command=command,
            operation_id=job_id,
            idempotency_key=idempotency_key,
        )
    except OperationIntentConflict as exc:
        raise VmShutdownError(
            "VM_SHUTDOWN_IDEMPOTENCY_CONFLICT",
            "The idempotency key already belongs to a different VM shutdown intent",
            details={
                "job_id": exc.operation_id,
                "target": intent.get("target", {}),
                "requested_intent": intent,
                "proxmox_mutation_enabled": False,
                "side_effects": [],
            },
        ) from exc
    if not prepared.created and prepared.operation.status != "planned":
        existing = ports.jobs.get(job_id)
        if existing:
            _ensure_replay_matches(existing, intent)
            return _existing_result(existing)
        raise VmShutdownError(
            "VM_SHUTDOWN_OPERATION_RECONCILIATION_REQUIRED",
            "The VM shutdown operation exists without a compatible job projection and requires reconciliation",
            details={
                "job_id": job_id,
                "operation_status": prepared.operation.status,
                "target": intent.get("target", {}),
                "proxmox_mutation_enabled": False,
                "side_effects": [],
            },
        )

    target_lock: VmShutdownTargetLockHandle | None = None
    recovery_lease: RecoveryLease | None = None
    retain_target_lock = False
    try:
        try:
            target_lock = ports.locks.acquire_target("proxmox_vm", vm_shutdown_target_lock_id(vmid), job_id)
        except VmShutdownTargetLockBusy as exc:
            existing = ports.jobs.get(job_id)
            current_operation = ports.operations.get(job_id)
            if existing:
                _ensure_replay_matches(existing, intent)
                if not _is_recoverable_pre_dispatch_terminal_replay(existing, current_operation):
                    return _existing_result(existing)
            terminal_replay_job = existing
            terminal_replay_operation = current_operation if terminal_replay_job is not None else None
            lock = dict(exc.evidence)
            conflict_evidence: dict[str, Any] = {"target_operation_lock": lock}
            conflicting_operation_id = _conflicting_operation_id(lock)
            if conflicting_operation_id == job_id:
                if terminal_replay_job is not None:
                    return _close_replayed_pre_dispatch_failure(
                        ports=ports,
                        job_id=job_id,
                        node_id=node_id,
                        vmid=vmid,
                        job=terminal_replay_job,
                        operation=terminal_replay_operation,
                        lock=lock,
                    )
                raise VmShutdownError(
                    "VM_SHUTDOWN_IN_PROGRESS",
                    "A VM shutdown operation with this idempotency key is already in progress",
                    details={
                        "job_id": job_id,
                        "operation_id": prepared.operation.operation_id,
                        "target": vm_shutdown_target(node_id=node_id, vmid=vmid),
                        "target_operation_lock": lock,
                        "proxmox_mutation_enabled": False,
                        "side_effects": [],
                    },
                ) from exc
            if conflicting_operation_id is not None:
                conflict_evidence["conflicting_operation_id"] = conflicting_operation_id
            foreign_lock = lock.get("existing") if isinstance(lock.get("existing"), dict) else {}
            ports.operations.transition_for_target_lock_conflict(
                job_id,
                conflicting_lock_id=str(foreign_lock.get("operation_lock_id") or ""),
                conflicting_owner_id=str(conflicting_operation_id or ""),
                next_status="failed" if terminal_replay_job is not None else "blocked",
                event_type=(
                    "replayed_pre_dispatch_failure_closed"
                    if terminal_replay_job is not None
                    else "target_lock_blocked"
                ),
                stage="reconciliation" if terminal_replay_job is not None else "precheck",
                payload=(
                    {"mutation_dispatched": False, "target_lock_owned_by_replay": False}
                    if terminal_replay_job is not None
                    else conflict_evidence
                ),
                details_patch=(
                    {"result_status": "failed", "recovered_pre_dispatch": True}
                    if terminal_replay_job is not None
                    else conflict_evidence
                ),
            )
            if terminal_replay_job is not None:
                return _existing_result(terminal_replay_job)
            details = {
                "operation_id": prepared.operation.operation_id,
                "target": vm_shutdown_target(node_id=node_id, vmid=vmid),
                "target_operation_lock": lock,
                "proxmox_mutation_enabled": False,
                "side_effects": [],
            }
            if conflicting_operation_id is not None:
                details["conflicting_operation_id"] = conflicting_operation_id
            raise VmShutdownError(
                "VM_SHUTDOWN_TARGET_LOCK_BUSY",
                "Another VM mutation for this target is already in progress or awaiting reconciliation",
                details=details,
            ) from exc

        # The previous owner may finish between the first lookup and acquiring
        # this locator lock. Only this fresh state may authorize new work.
        existing = ports.jobs.get(job_id)
        current_operation = ports.operations.get(job_id)
        if existing:
            _ensure_replay_matches(existing, intent)
            if not _is_recoverable_pre_dispatch_terminal_replay(existing, current_operation):
                return _existing_result(existing)
        terminal_replay_job = existing
        terminal_replay_operation = current_operation if terminal_replay_job is not None else None
        if terminal_replay_job is not None:
            retain_target_lock = True
            result = _close_replayed_pre_dispatch_failure(
                ports=ports,
                job_id=job_id,
                node_id=node_id,
                vmid=vmid,
                job=terminal_replay_job,
                operation=terminal_replay_operation,
                lock=_lock_evidence(target_lock),
            )
            retain_target_lock = False
            return result

        if current_operation is None or current_operation.status != "planned":
            raise VmShutdownError(
                "VM_SHUTDOWN_OPERATION_RECONCILIATION_REQUIRED",
                "The VM shutdown operation exists without a compatible job projection and requires reconciliation",
                details={
                    "job_id": job_id,
                    "operation_status": current_operation.status if current_operation is not None else None,
                    "target": intent.get("target", {}),
                    "proxmox_mutation_enabled": False,
                    "side_effects": [],
                },
            )

        target = vm_shutdown_target(
            node_id=node_id,
            vmid=vmid,
            name=str(command.payload.get("expected_name") or ""),
        )
        _record_job(
            jobs=ports.jobs,
            job_id=job_id,
            status="running",
            stage="precheck",
            step_status="running",
            message="VM shutdown precheck is running.",
            target=target,
            actor=actor,
            intent=intent,
            details={"target_operation_lock": _lock_evidence(target_lock)},
        )
        try:
            precheck = evaluate_vm_shutdown_precheck(
                ports.workloads,
                node_id=node_id,
                vmid=vmid,
                payload=command.payload,
            )
        except VmShutdownPrecheckBlocked as blocked:
            retain_target_lock = True
            try:
                _raise_precheck(
                    ports=ports,
                    job_id=job_id,
                    blocked=blocked,
                    actor=actor,
                    intent=intent,
                    lock_handle=target_lock,
                )
            except VmShutdownError as exc:
                if exc.code == blocked.code:
                    retain_target_lock = False
                raise

        try:
            client = ports.mutation_factory()
        except VmShutdownMutationFailure as exc:
            retain_target_lock = True
            result = {
                "job_id": job_id,
                "status": "failed",
                "message": "Proxmox mutation client is unavailable for VM shutdown",
                "target": precheck.target,
                "pre_dispatch_no_effect_verified": False,
                "proxmox_shutdown_ran": False,
                "proxmox_mutation_enabled": False,
                "side_effects": [],
            }
            result["pre_dispatch_no_effect_verified"] = True
            _record_job(
                jobs=ports.jobs,
                job_id=job_id,
                status="failed",
                stage="shutdown",
                step_status="failed",
                message=result["message"],
                target=precheck.target,
                actor=actor,
                intent=intent,
                details={"vm_shutdown_result": result},
            )
            no_effect = _pre_dispatch_terminal_no_effect_marker(
                target_lock,
                reason="mutation_client_unavailable",
            )
            terminal_recorded = ports.operations.transition_pre_dispatch_failure(
                job_id,
                target_lock_id=str(no_effect["target_lock_id"]),
                event_type="mutation_client_unavailable",
                stage="shutdown",
                payload={"error_type": type(exc).__name__, **no_effect},
                details_patch=no_effect,
            )
            retain_target_lock = not terminal_recorded
            raise VmShutdownError("VM_SHUTDOWN_CLIENT_UNAVAILABLE", result["message"], details=result) from exc
        if client is None:
            retain_target_lock = True
            result = {
                "job_id": job_id,
                "status": "failed",
                "message": "Proxmox mutation client is unavailable for VM shutdown",
                "target": precheck.target,
                "pre_dispatch_no_effect_verified": False,
                "proxmox_shutdown_ran": False,
                "proxmox_mutation_enabled": False,
                "side_effects": [],
            }
            result["pre_dispatch_no_effect_verified"] = True
            _record_job(
                jobs=ports.jobs,
                job_id=job_id,
                status="failed",
                stage="shutdown",
                step_status="failed",
                message=result["message"],
                target=precheck.target,
                actor=actor,
                intent=intent,
                details={"vm_shutdown_result": result},
            )
            no_effect = _pre_dispatch_terminal_no_effect_marker(
                target_lock,
                reason="mutation_client_unavailable",
            )
            terminal_recorded = ports.operations.transition_pre_dispatch_failure(
                job_id,
                target_lock_id=str(no_effect["target_lock_id"]),
                event_type="mutation_client_unavailable",
                stage="shutdown",
                payload={"message": result["message"], **no_effect},
                details_patch=no_effect,
            )
            retain_target_lock = not terminal_recorded
            raise VmShutdownError(
                "VM_SHUTDOWN_CLIENT_UNAVAILABLE",
                result["message"],
                status_code=503,
                details=result,
            )

        target = precheck.target
        if ports.recovery is not None:
            try:
                lock_evidence, durable_lock = _required_target_lock_binding(
                    target_lock,
                    operation_id=job_id,
                    vmid=vmid,
                )
                recovery_lease = ports.recovery.prepare_and_claim(
                    RecoverySpec(
                        operation_id=job_id,
                        recovery_kind="vm_shutdown_observation",
                        details={
                            "node_id": node_id,
                            "vmid": vmid,
                            "target_type": "proxmox_vm",
                            "target_id": vm_shutdown_target_lock_id(vmid),
                            "operation_type": "vm_shutdown",
                            "execution_mode": "managed_api",
                            "phase": "pre_dispatch",
                            "target_lock_id": str(durable_lock.get("operation_lock_id") or ""),
                            "cluster_id": str(durable_lock.get("cluster_id") or ""),
                        },
                    ),
                    lease_owner=f"foreground:{job_id}",
                    lease_seconds=ports.recovery_lease_seconds,
                )
            except Exception as exc:

                retain_target_lock = True
                result = {
                    "job_id": job_id,
                    "status": "failed",
                    "message": "Durable recovery could not be registered before VM shutdown dispatch",
                    "target": target,
                    "target_operation_lock": _lock_evidence(target_lock, retained=False),
                    "pre_dispatch_no_effect_verified": True,
                    "reconciliation_required": False,
                    "proxmox_shutdown_ran": False,
                    "proxmox_mutation_enabled": False,
                    "side_effects": [],
                }
                _record_job(
                    jobs=ports.jobs,
                    job_id=job_id,
                    status="failed",
                    stage="shutdown",
                    step_status="failed",
                    message=result["message"],
                    target=target,
                    actor=actor,
                    intent=intent,
                    details={"vm_shutdown_result": result, "target_operation_lock": result["target_operation_lock"]},
                )
                no_effect = _pre_dispatch_terminal_no_effect_marker(
                    target_lock,
                    reason="recovery_registration_failed",
                )
                terminal_recorded = ports.operations.transition_pre_dispatch_failure(
                    job_id,
                    target_lock_id=str(no_effect["target_lock_id"]),
                    event_type="recovery_registration_failed",
                    stage="shutdown",
                    payload={"code": "VM_SHUTDOWN_RECOVERY_UNAVAILABLE", **no_effect},
                    details_patch=no_effect,
                )
                retain_target_lock = not terminal_recorded
                raise VmShutdownError(
                    "VM_SHUTDOWN_RECOVERY_UNAVAILABLE",
                    result["message"],
                    status_code=503,
                    details=result,
                ) from exc
            try:
                _, recovery_item = ports.recovery.commit_observation(
                    recovery_lease,
                    next_status="dispatching",
                    event_type="dispatch_prepared",
                    stage="shutdown",
                    payload={
                        "target": target,
                        "expected": precheck.expected,
                        "observed_before": precheck.observed_before,
                        "forced_stop_enabled": False,
                    },
                    details_patch={"target_operation_lock": lock_evidence},
                    expected_statuses=["planned"],
                    recovery_status="leased",
                    recovery_details_patch={
                        "phase": "dispatch_prepared",
                        "target_lock_id": str(durable_lock.get("operation_lock_id") or ""),
                        "cluster_id": str(durable_lock.get("cluster_id") or ""),
                    },
                    bind_target_lock=True,
                )
                recovery_lease = RecoveryLease(item=recovery_item, token=recovery_lease.token)
            except Exception as exc:
                retain_target_lock = True
                raise VmShutdownError(
                    "VM_SHUTDOWN_RECOVERY_UNAVAILABLE",
                    "Durable recovery could not checkpoint VM shutdown dispatch preparation",
                    status_code=503,
                    details={
                        "job_id": job_id,
                        "target": target,
                        "proxmox_shutdown_ran": False,
                        "proxmox_mutation_enabled": False,
                        "side_effects": [],
                    },
                ) from exc
        else:
            transition_vm_shutdown_operation(
                ports.operations,
                job_id,
                next_status="dispatching",
                event_type="dispatch_prepared",
                stage="shutdown",
                payload={
                    "target": target,
                    "expected": precheck.expected,
                    "observed_before": precheck.observed_before,
                    "forced_stop_enabled": False,
                },
                expected_statuses=["planned"],
            )

        retain_target_lock = True
        try:
            raw_upid = str(client.shutdown_vm(node=node_id, vmid=vmid) or "").strip()
            upid = compact_proxmox_task({}, node=node_id, upid=raw_upid)["upid"]
        except VmShutdownMutationFailure as exc:
            error_details = compact_proxmox_error_details(exc.details)
            if _is_clear_4xx_rejection(exc):
                result = {
                    "job_id": job_id,
                    "status": "failed",
                    "message": "Proxmox VM shutdown request was rejected by the API",
                    "target": target,
                    "task": {
                        "node": node_id,
                        "upid": "",
                        "status": "failed",
                        "exitstatus": "",
                        "error": "proxmox_shutdown_request_rejected",
                        "details": error_details,
                    },
                    "proxmox_mutation_enabled": False,
                    "side_effects": ["proxmox_shutdown_request_rejected"],
                }
                if ports.recovery is not None and recovery_lease is not None:
                    try:
                        _, item = ports.recovery.commit_observation(
                            recovery_lease,
                            next_status="failed",
                            event_type="dispatch_rejected",
                            stage="shutdown",
                            payload={"error_type": type(exc).__name__},
                            expected_statuses=["dispatching"],
                            recovery_status="leased",
                            error_code="VM_SHUTDOWN_REQUEST_FAILED",
                            recovery_details_patch={
                                "phase": "dispatch_rejected",
                                "terminal_outcome": "failed",
                                "task": {
                                    "node": node_id,
                                    "upid": "",
                                    "status": "failed",
                                    "exitstatus": "",
                                },
                                "observed_after": {},
                            },
                        )
                        recovery_lease = RecoveryLease(item=item, token=recovery_lease.token)
                    except RecoveryLeaseLost as lease_exc:
                        _raise_recovery_lease_lost(
                            lease_exc,
                            job_id=job_id,
                            target=target,
                            message="VM shutdown recovery ownership changed; the rejection was not committed",
                            side_effects=["proxmox_shutdown_request_rejected"],
                        )
                else:
                    transition_vm_shutdown_operation(
                        ports.operations,
                        job_id,
                        next_status="failed",
                        event_type="dispatch_rejected",
                        stage="shutdown",
                        expected_statuses=["dispatching"],
                    )
                try:
                    _record_job(
                        jobs=ports.jobs,
                        job_id=job_id,
                        status="failed",
                        stage="shutdown",
                        step_status="failed",
                        message=result["message"],
                        target=target,
                        actor=actor,
                        intent=intent,
                        details={"vm_shutdown_result": result},
                    )
                except Exception:
                    _persistence_failure_handoff(
                        ports=ports,
                        recovery_lease=recovery_lease,
                        job_id=job_id,
                        code="VM_SHUTDOWN_COMPATIBILITY_PROJECTION_PERSISTENCE_UNAVAILABLE",
                        message=(
                            "VM shutdown rejection was recorded in the canonical Operation, but the "
                            "compatibility Job projection could not be persisted"
                        ),
                        event_type="compatibility_projection_persistence_failed",
                        stage="reconciliation",
                        target=target,
                        operation_status="failed",
                        side_effects=["proxmox_shutdown_request_rejected"],
                        evidence_status="not_required",
                        evidence_recorded=False,
                        target_lock=target_lock,
                        task=result["task"],
                        observed_after={},
                    )
                if ports.recovery is not None and recovery_lease is not None:

                    try:
                        ports.recovery.commit_observation(
                            recovery_lease,
                            event_type=(
                                "recovery_compatibility_projection_recorded"
                            ),
                            stage="shutdown",
                            payload={"operation_status": "failed"},
                            expected_statuses=["failed"],
                            recovery_status="completed",
                            retry_delay_seconds=0,
                            error_code=(
                                None
                            ),
                            release_target_lock=True,
                        )
                    except RecoveryLeaseLost as lease_exc:
                        _raise_recovery_lease_lost(
                            lease_exc,
                            job_id=job_id,
                            target=target,
                            message=(
                                "VM shutdown recovery ownership changed before the rejected "
                                "job projection was finalized"
                            ),
                            side_effects=["proxmox_shutdown_request_rejected"],
                        )
                    retain_target_lock = False
                else:
                    retain_target_lock = False
                raise VmShutdownError(
                    "VM_SHUTDOWN_REQUEST_FAILED",
                    result["message"],
                    details={**result, "proxmox_shutdown_ran": False},
                ) from exc
            try:
                observed_after = _status_payload(client.get_vm_status(node=node_id, vmid=vmid))
            except VmShutdownMutationFailure:
                observed_after = _status_payload(
                    {},
                    error="proxmox_vm_status_observation_unavailable",
                )
            task = {
                "node": node_id,
                "upid": "",
                "status": "unknown",
                "exitstatus": "unknown",
                "error": "proxmox_shutdown_request_state_unknown",
                "details": error_details,
            }
            artifact = _write_artifact_or_handoff(
                ports=ports,
                recovery_lease=recovery_lease,
                job_id=job_id,
                target=target,
                idempotency_key=idempotency_key,
                expected=precheck.expected,
                observed_before=precheck.observed_before,
                task=task,
                observed_after=observed_after,
                client=client,
                actor=actor,
                operation_status="dispatching",
                stage="reconciliation",
                side_effects=["proxmox_shutdown_request_ambiguous", "proxmox_post_check_observed"],
                target_lock=target_lock,
            )
            _record_reconciliation(
                ports=ports,
                lease=recovery_lease,
                job_id=job_id,
                code="VM_SHUTDOWN_REQUEST_RECONCILIATION_REQUIRED",
                message="Proxmox VM shutdown request outcome is ambiguous and requires reconciliation",
                stage="shutdown",
                target=target,
                intent=intent,
                idempotency_key=idempotency_key,
                expected=precheck.expected,
                observed_before=precheck.observed_before,
                task=task,
                observed_after=observed_after,
                artifact=artifact,
                upid="",
                side_effects=["proxmox_shutdown_request_ambiguous", "proxmox_post_check_observed"],
                lock_handle=target_lock,
                actor=actor,
            )

        if not upid:
            try:
                observed_after = _status_payload(client.get_vm_status(node=node_id, vmid=vmid))
            except VmShutdownMutationFailure:
                observed_after = _status_payload(
                    {},
                    error="proxmox_vm_status_observation_unavailable",
                )
            task = {"node": node_id, "upid": "", "status": "unknown", "exitstatus": "unknown"}
            artifact = _write_artifact_or_handoff(
                ports=ports,
                recovery_lease=recovery_lease,
                job_id=job_id,
                target=target,
                idempotency_key=idempotency_key,
                expected=precheck.expected,
                observed_before=precheck.observed_before,
                task=task,
                observed_after=observed_after,
                client=client,
                actor=actor,
                operation_status="dispatching",
                stage="reconciliation",
                side_effects=["proxmox_shutdown_invoked", "proxmox_post_check_observed"],
                target_lock=target_lock,
            )
            _record_reconciliation(
                ports=ports,
                lease=recovery_lease,
                job_id=job_id,
                code="VM_SHUTDOWN_REQUEST_RECONCILIATION_REQUIRED",
                message="Proxmox VM shutdown request did not return a UPID and requires reconciliation",
                stage="shutdown",
                target=target,
                intent=intent,
                idempotency_key=idempotency_key,
                expected=precheck.expected,
                observed_before=precheck.observed_before,
                task=task,
                observed_after=observed_after,
                artifact=artifact,
                upid="",
                side_effects=["proxmox_shutdown_invoked", "proxmox_post_check_observed"],
                lock_handle=target_lock,
                actor=actor,
            )

        if ports.recovery is not None and recovery_lease is not None:
            try:
                _, item = ports.recovery.commit_observation(
                    recovery_lease,
                    next_status="running",
                    event_type="dispatch_accepted",
                    stage="task_poll",
                    payload={"upid": upid, "node_id": node_id},
                    details_patch={"proxmox_upid": upid},
                    expected_statuses=["dispatching"],
                    recovery_status="leased",
                    recovery_details_patch={"upid": upid, "node_id": node_id, "vmid": vmid},
                )
            except RecoveryLeaseLost as exc:
                _raise_recovery_lease_lost(
                    exc,
                    job_id=job_id,
                    target=target,
                    message="VM shutdown recovery ownership changed after dispatch; reconciliation is required",
                    side_effects=["proxmox_shutdown_invoked"],
                )
            recovery_lease = RecoveryLease(item=item, token=recovery_lease.token)
        else:
            transition_vm_shutdown_operation(
                ports.operations,
                job_id,
                next_status="running",
                event_type="dispatch_accepted",
                stage="task_poll",
                payload={"upid": upid, "node_id": node_id},
                details_patch={"proxmox_upid": upid},
                expected_statuses=["dispatching"],
            )
        _record_job(
            jobs=ports.jobs,
            job_id=job_id,
            status="running",
            stage="task_poll",
            step_status="running",
            message="Proxmox VM shutdown task is being polled.",
            target=target,
            actor=actor,
            intent=intent,
            details={"target_operation_lock": _lock_evidence(target_lock)},
        )

        task_ambiguous = False
        try:
            heartbeat = None
            if ports.recovery is not None and recovery_lease is not None:
                heartbeat = lambda: ports.recovery.heartbeat(
                    recovery_lease,
                    lease_seconds=ports.recovery_lease_seconds,
                )
            task = client.wait_for_task(node=node_id, upid=upid, heartbeat=heartbeat)
        except RecoveryLeaseLost as exc:
            raise VmShutdownError(
                "VM_SHUTDOWN_RECOVERY_LEASE_LOST",
                "VM shutdown recovery ownership changed during task polling; reconciliation is required",
                status_code=503,
                details={"job_id": job_id, "target": target, "upid": upid, "side_effects": ["proxmox_shutdown_invoked"]},
            ) from exc
        except VmShutdownMutationFailure as exc:
            task_ambiguous = True
            task = {
                "node": node_id,
                "upid": upid,
                "status": "unknown",
                "exitstatus": "unknown",
                "error": "proxmox_shutdown_task_observation_unavailable",
                "details": compact_proxmox_error_details(exc.details),
            }
        try:
            observed_after = _status_payload(client.get_vm_status(node=node_id, vmid=vmid))
        except VmShutdownMutationFailure:
            observed_after = _status_payload(
                {},
                error="proxmox_vm_status_observation_unavailable",
            )

        compact_task = _compact_task(task, node_id=node_id, upid=upid)
        compact_status = _compact_status(observed_after, node_id=node_id, vmid=vmid)
        if ports.recovery is not None and recovery_lease is not None:
            try:
                _, item = ports.recovery.commit_observation(
                    recovery_lease,
                    next_status="verifying",
                    event_type="task_and_state_observed",
                    stage="post_check",
                    payload={"task": compact_task, "observed_after": compact_status},
                    expected_statuses=["running"],
                    recovery_status="leased",
                    recovery_details_patch={"task": compact_task, "observed_after": compact_status},
                )
            except RecoveryLeaseLost as exc:
                _raise_recovery_lease_lost(
                    exc,
                    job_id=job_id,
                    target=target,
                    message="VM shutdown recovery ownership changed while recording observations",
                    side_effects=["proxmox_shutdown_invoked", "proxmox_task_polled", "proxmox_post_check_observed"],
                )
            recovery_lease = RecoveryLease(item=item, token=recovery_lease.token)
        else:
            transition_vm_shutdown_operation(
                ports.operations,
                job_id,
                next_status="verifying",
                event_type="task_and_state_observed",
                stage="post_check",
                payload={"task": compact_task, "observed_after": compact_status},
                expected_statuses=["running"],
            )
        artifact = _write_artifact_or_handoff(
            ports=ports,
            recovery_lease=recovery_lease,
            job_id=job_id,
            target=target,
            idempotency_key=idempotency_key,
            expected=precheck.expected,
            observed_before=precheck.observed_before,
            task=task,
            observed_after=observed_after,
            client=client,
            actor=actor,
            operation_status="verifying",
            stage="post_check",
            side_effects=["proxmox_shutdown_invoked", "proxmox_task_polled", "proxmox_post_check_observed"],
            target_lock=target_lock,
        )
        exitstatus = str(compact_task.get("exitstatus") or "").strip().upper()
        task_status = normalize_vm_status(compact_task.get("status"))
        observed_status = normalize_vm_status(compact_status.get("status"))
        side_effects = ["proxmox_shutdown_invoked", "proxmox_task_polled", "proxmox_post_check_observed"]
        if task_ambiguous or task_status != "stopped" or exitstatus != "OK" or observed_status != "stopped":
            _record_reconciliation(
                ports=ports,
                lease=recovery_lease,
                job_id=job_id,
                code="VM_SHUTDOWN_RESULT_RECONCILIATION_REQUIRED",
                message=(
                    "VM shutdown task and direct VM state do not establish a verified stopped result; "
                    "reconciliation is required"
                ),
                stage="post_check",
                target=target,
                intent=intent,
                idempotency_key=idempotency_key,
                expected=precheck.expected,
                observed_before=precheck.observed_before,
                task=task,
                observed_after=observed_after,
                artifact=artifact,
                upid=upid,
                side_effects=side_effects,
                lock_handle=target_lock,
                actor=actor,
            )

        result = {
            "job_id": job_id,
            "status": "completed",
            "message": "VM shutdown completed and the VM is stopped.",
            "target": target,
            "task": compact_task,
            "upid": upid,
            "observed_before": precheck.observed_before,
            "observed_after": compact_status,
            "observed_after_artifact": artifact,
            "artifacts": [artifact],
            "idempotent_replay": False,
            "idempotency_key": idempotency_key,
            "target_operation_lock": _lock_evidence(target_lock),
            "proxmox_mutation_enabled": True,
            "forced_stop_enabled": False,
            "side_effects": side_effects,
        }
        if ports.recovery is not None and recovery_lease is not None:
            try:
                _, item = ports.recovery.commit_observation(
                    recovery_lease,
                    next_status="succeeded",
                    event_type="verification_succeeded",
                    stage="post_check",
                    payload={"task": compact_task, "observed_after": compact_status, "artifact": artifact},
                    details_patch={"result_status": "completed"},
                    expected_statuses=["verifying"],
                    recovery_status="leased",
                    recovery_details_patch={
                        "terminal_outcome": "succeeded",
                        "task": compact_task,
                        "observed_after": compact_status,
                    },
                )
            except RecoveryLeaseLost as exc:
                _raise_recovery_lease_lost(
                    exc,
                    job_id=job_id,
                    target=target,
                    message="VM shutdown recovery ownership changed before success could be committed",
                    side_effects=side_effects,
                )
            recovery_lease = RecoveryLease(item=item, token=recovery_lease.token)
        else:
            transition_vm_shutdown_operation(
                ports.operations,
                job_id,
                next_status="succeeded",
                event_type="verification_succeeded",
                stage="post_check",
                payload={"task": compact_task, "observed_after": compact_status, "artifact": artifact},
                details_patch={"result_status": "completed"},
                expected_statuses=["verifying"],
            )
        try:
            _record_job(
                jobs=ports.jobs,
                job_id=job_id,
                status="completed",
                stage="post_check",
                step_status="completed",
                message=result["message"],
                target=target,
                artifacts=[artifact],
                actor=actor,
                intent=intent,
                details={"vm_shutdown_result": result, "target_operation_lock": _lock_evidence(target_lock)},
            )
        except Exception:
            _persistence_failure_handoff(
                ports=ports,
                recovery_lease=recovery_lease,
                job_id=job_id,
                code="VM_SHUTDOWN_COMPATIBILITY_PROJECTION_PERSISTENCE_UNAVAILABLE",
                message=(
                    "VM shutdown success was recorded in the canonical Operation, but the compatibility "
                    "Job projection could not be persisted"
                ),
                event_type="compatibility_projection_persistence_failed",
                stage="reconciliation",
                target=target,
                operation_status="succeeded",
                side_effects=side_effects,
                evidence_status="recorded",
                evidence_recorded=True,
                target_lock=target_lock,
                task=task,
                observed_after=observed_after,
                artifact=artifact,
            )
        if ports.recovery is not None and recovery_lease is not None:

            try:
                ports.recovery.commit_observation(
                    recovery_lease,
                    event_type="recovery_compatibility_projection_recorded",
                    stage="post_check",
                    payload={"operation_status": "succeeded"},
                    expected_statuses=["succeeded"],
                    recovery_status="completed",
                    retry_delay_seconds=0,
                    error_code=(None),
                    release_target_lock=True,
                )
            except RecoveryLeaseLost as exc:
                _raise_recovery_lease_lost(
                    exc,
                    job_id=job_id,
                    target=target,
                    message="VM shutdown recovery ownership changed before compatibility projection was finalized",
                    side_effects=side_effects,
                )
        retain_target_lock = False
        return result
    finally:
        if target_lock is not None and not retain_target_lock:
            ports.locks.release_target(target_lock)


class VerifiedVmShutdownWorkflow:
    def execute(self, command: VmShutdownCommand, ports: VmShutdownExecutionPorts) -> dict[str, Any]:
        return _execute(command, ports)


__all__ = ["VerifiedVmShutdownWorkflow"]
