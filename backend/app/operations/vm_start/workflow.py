"""Verified VM Start application workflow."""

from __future__ import annotations

from typing import Any, NoReturn

from app.operations.core.domain import OperationIntentConflict
from app.operations.locks.domain import locator_scope_key
from app.operations.recovery.domain import (
    PRE_DISPATCH_RECOVERY_CONTRACT,
    RecoveryLease,
    RecoveryLeaseLost,
    RecoveryOperationConflict,
    RecoverySpec,
    is_pre_dispatch_terminal_no_effect,
)
from app.operations.vm_start.domain import (
    VmStartCommand,
    build_vm_start_job_id as build_operation_job_id,
    vm_start_expected_context,
    vm_start_target,
    vm_start_target_lock_id,
)
from app.operations.vm_start.errors import VmStartError
from app.operations.vm_start.ports import (
    VmStartEvidencePort,
    VmStartExecutionPorts,
    VmStartJobPort,
    VmStartMutationFailure,
    VmStartMutationPort,
    VmStartTargetLockBusy,
    VmStartTargetLockHandle,
)
from app.operations.core.evidence import (
    compact_proxmox_connection_evidence,
    compact_proxmox_error_details,
    compact_proxmox_task,
    compact_proxmox_vm_status,
)
from app.operations.vm_start.precheck import (
    VmStartPrecheck,
    VmStartPrecheckBlocked,
    evaluate_vm_start_precheck,
    normalize_vm_status,
)
from app.operations.vm_start.tracking import prepare_vm_start_operation, transition_vm_start_operation


def _target_id(node_id: str, vmid: int, name: str = "") -> str:
    suffix = f":{name}" if name else ""
    return f"{node_id}:{int(vmid)}{suffix}"


def _target_lock_id(vmid: int) -> str:
    # One configured Proxmox cluster owns a cluster-wide VMID namespace. The
    # node is an observed locator and may change during migration.
    return vm_start_target_lock_id(vmid)


def _target_payload(node_id: str, vmid: int, name: str = "") -> dict[str, Any]:
    return vm_start_target(node_id=node_id, vmid=vmid, name=name)


def _actor_detail_fields(actor: dict[str, Any] | None) -> dict[str, Any]:
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


def _expected_context(payload: dict[str, Any]) -> dict[str, Any]:
    return vm_start_expected_context(payload)


def _stored_vm_start_intent(job: dict[str, Any]) -> dict[str, Any]:
    details = job.get("details") if isinstance(job.get("details"), dict) else {}
    intent = details.get("vm_start_intent")
    return dict(intent) if isinstance(intent, dict) else {}


def _ensure_idempotent_replay_matches_intent(job: dict[str, Any], requested_intent: dict[str, Any]) -> None:
    stored_intent = _stored_vm_start_intent(job)
    if not stored_intent:
        return
    if stored_intent == requested_intent:
        return
    raise VmStartError(
        "VM_START_IDEMPOTENCY_CONFLICT",
        "The idempotency key already belongs to a different VM start intent",
        details={
            "job_id": job.get("job_id"),
            "target": requested_intent.get("target", {}),
            "existing_intent": stored_intent,
            "requested_intent": requested_intent,
            "proxmox_mutation_enabled": False,
            "side_effects": [],
        },
    )


def _record_vm_start_job(
    *,
    jobs: VmStartJobPort,
    job_id: str,
    status: str,
    stage: str,
    step_status: str,
    message: str,
    target: dict[str, Any],
    artifacts: list[Any] | None = None,
    details: dict[str, Any] | None = None,
    actor: dict[str, Any] | None = None,
    intent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    details_payload = {"target": target, **(details or {})}
    if intent is not None:
        details_payload["vm_start_intent"] = dict(intent)
    details_payload.update(_actor_detail_fields(actor))
    return jobs.record(
        job_id=job_id,
        job_type="vm_start",
        status=status,
        target_id=_target_id(str(target.get("node_id") or ""), int(target.get("vmid") or 0), str(target.get("name") or "")),
        risk_level="unknown",
        stage=stage,
        step_status=step_status,
        message=message,
        artifacts=artifacts,
        risks=[],
        details=details_payload,
    )


def _raise_precheck_block(
    *,
    ports: VmStartExecutionPorts,
    job_id: str,
    blocked: VmStartPrecheckBlocked,
    actor: dict[str, Any] | None,
    intent: dict[str, Any],
    lock_handle: VmStartTargetLockHandle | None,
) -> NoReturn:
    no_effect = _pre_dispatch_terminal_no_effect_marker(
        lock_handle,
        reason="precheck_blocked",
    )
    transition_vm_start_operation(
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
    _record_vm_start_job(
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
            "vm_start": {
                "code": blocked.code,
                "expected": blocked.expected,
                "observed_before": blocked.observed_before,
                "proxmox_mutation_enabled": False,
            }
        },
    )
    raise VmStartError(
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


def _status_payload(payload: Any, *, error: str | None = None) -> dict[str, Any]:
    status = dict(payload) if isinstance(payload, dict) else {}
    if error:
        status["error"] = error
    return status


def _recovery_task_payload(task: dict[str, Any]) -> dict[str, Any]:
    """Bound durable recovery details independently of raw poll history."""

    return compact_proxmox_task(task)


def _recovery_observed_payload(observed: dict[str, Any], *, node_id: str, vmid: int) -> dict[str, Any]:
    result = compact_proxmox_vm_status(observed, node=node_id, vmid=vmid)
    result["error"] = (
        "proxmox_vm_status_observation_unavailable"
        if observed.get("error")
        else ""
    )
    return result


def _write_observed_artifact(
    *,
    evidence: VmStartEvidencePort,
    job_id: str,
    target: dict[str, Any],
    idempotency_key: str,
    expected: dict[str, Any],
    observed_before: dict[str, Any],
    task: dict[str, Any],
    observed_after: dict[str, Any],
    client: VmStartMutationPort,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    node_id = str(target.get("node_id") or "")
    vmid = int(target.get("vmid") or 0)
    payload = {
        "job_id": job_id,
        "operation": "vm_start",
        "target": target,
        "idempotency_key": idempotency_key,
        "expected": expected,
        "observed_before": observed_before,
        "task": _recovery_task_payload(task),
        "observed_after": _recovery_observed_payload(observed_after, node_id=node_id, vmid=vmid),
        "evidence": {
            "connection": compact_proxmox_connection_evidence(
                client.redacted_connection_context()
            ),
            "observation_kinds": ["vm_start", "task_status", "vm_status"],
        },
    }
    payload.update(_actor_detail_fields(actor))
    return evidence.write_json(
        job_id=job_id,
        artifact_type="vm_start_observed_after",
        filename="vm_start_observed_after.json",
        payload=payload,
    )


def _persistence_failure_handoff(
    *,
    ports: VmStartExecutionPorts,
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
    target_lock: VmStartTargetLockHandle | None,
    task: dict[str, Any] | None = None,
    observed_after: dict[str, Any] | None = None,
    artifact: dict[str, Any] | None = None,
    next_status: str | None = None,
    recovery_error_code: str | None = None,
    recovery_status: str = "retry_wait",
) -> NoReturn:
    """Expose a stable handoff after Proxmox was already contacted.

    The handoff never retries the mutation.  When the owned recovery lease is
    still valid it makes the GET-only recovery item immediately claimable;
    otherwise it reports the last durable state and leaves the exact target
    lock in place for lease-expiry recovery.
    """

    task_payload = _recovery_task_payload(task or {})
    observed_payload = _recovery_observed_payload(
        observed_after or {},
        node_id=str(target.get("node_id") or ""),
        vmid=int(target.get("vmid") or 0),
    )
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
            # The API contract remains stable even if the recovery handoff
            # write is the failing persistence boundary.  The current lease
            # and exact target lock remain durable and fenced.
            try:
                current_recovery = ports.recovery.get(job_id)
            except Exception:
                current_recovery = None
            if current_recovery is not None:
                effective_recovery_status = current_recovery.status
    elif next_status is not None:
        try:
            committed_operation = transition_vm_start_operation(
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
    operation_version = getattr(committed_operation, "version", None)
    operation_checksum = getattr(committed_operation, "last_event_checksum", None)
    lock = _lock_evidence(target_lock, retained=True)
    details = {
        "operation_id": job_id,
        "job_id": job_id,
        "status": effective_operation_status,
        "operation_status": effective_operation_status,
        "operation_version": operation_version,
        "operation_checksum": operation_checksum,
        "recovery_status": effective_recovery_status,
        "recovery_error_code": stored_recovery_error,
        "compatibility_job_status": (
            str(compatibility_job.get("status") or "")
            if isinstance(compatibility_job, dict)
            else "unavailable"
        ),
        "target": target,
        "target_operation_lock": lock,
        "task": task_payload,
        "observed_after": observed_payload,
        "evidence_status": evidence_status,
        "evidence_recorded": evidence_recorded,
        "observed_after_artifact": artifact or {},
        "reconciliation_required": True,
        "proxmox_start_ran": True,
        "proxmox_mutation_enabled": False,
        "side_effects": side_effects,
    }
    raise VmStartError(code, message, status_code=503, details=details) from None


def _write_observed_artifact_or_handoff(
    *,
    ports: VmStartExecutionPorts,
    recovery_lease: RecoveryLease | None,
    job_id: str,
    target: dict[str, Any],
    idempotency_key: str,
    expected: dict[str, Any],
    observed_before: dict[str, Any],
    task: dict[str, Any],
    observed_after: dict[str, Any],
    client: VmStartMutationPort,
    actor: dict[str, Any] | None,
    operation_status: str,
    stage: str,
    side_effects: list[str],
    target_lock: VmStartTargetLockHandle | None,
) -> dict[str, Any]:
    try:
        return _write_observed_artifact(
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
            code="VM_START_OBSERVED_EVIDENCE_PERSISTENCE_UNAVAILABLE",
            message=(
                "VM start external observations were recorded canonically, but the observed-after "
                "artifact could not be persisted"
            ),
            event_type="observed_evidence_persistence_failed",
            stage=stage,
            target=target,
            operation_status=operation_status,
            next_status="needs_reconciliation",
            recovery_status="retry_wait" if upid else "paused",
            recovery_error_code=(
                "VM_START_OBSERVED_EVIDENCE_PERSISTENCE_UNAVAILABLE"
                if upid
                else "VM_START_RECOVERY_TASK_REFERENCE_MISSING"
            ),
            side_effects=side_effects,
            evidence_status="persistence_failed",
            evidence_recorded=False,
            target_lock=target_lock,
            task=task,
            observed_after=observed_after,
        )


def _lock_evidence(handle: VmStartTargetLockHandle | None, *, retained: bool = False) -> dict[str, Any]:
    if handle is None:
        return {}
    payload = dict(handle.evidence)
    payload["status"] = "reconciliation_required" if retained else "active"
    return payload


def _required_target_lock_binding(
    handle: VmStartTargetLockHandle | None,
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
        or str(lock.get("target_id") or "") != _target_lock_id(vmid)
        or str(lock.get("owner_id") or "") != operation_id
        or not str(lock.get("lock_id") or "").strip()
        or not str(durable.get("operation_lock_id") or "").strip()
        or str(durable.get("operation_type") or "") != "vm_start"
        or str(durable.get("owner_id") or "") != operation_id
        or str(durable.get("scope_type") or "") != "proxmox_locator"
        or str(durable.get("scope_key") or "") != locator_scope_key(cluster_id, vmid)
        or str(durable.get("status") or "") != "active"
        or not cluster_id
        or durable_vmid != vmid
    ):
        raise ValueError("VM start target lock binding is not exact")
    return lock, durable


def _pre_dispatch_terminal_no_effect_marker(
    handle: VmStartTargetLockHandle | None,
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


def _raise_target_lock_busy(
    exc: VmStartTargetLockBusy,
    *,
    operation_id: str,
    node_id: str,
    vmid: int,
) -> None:
    lock = dict(exc.evidence)
    details = {
        "operation_id": operation_id,
        "target": _target_payload(node_id, vmid),
        "target_operation_lock": lock,
        "proxmox_mutation_enabled": False,
        "side_effects": [],
    }
    conflicting_operation_id = _conflicting_operation_id(lock)
    if conflicting_operation_id is not None:
        details["conflicting_operation_id"] = conflicting_operation_id
    raise VmStartError(
        "VM_START_TARGET_LOCK_BUSY",
        "Another VM mutation for this target is already in progress or awaiting reconciliation",
        details=details,
    ) from exc


def _is_http_4xx_rejection(exc: VmStartMutationFailure) -> bool:
    try:
        status_code = int(exc.details.get("status_code"))
    except (TypeError, ValueError):
        return False
    ambiguous_statuses = {408, 425, 429}
    return 400 <= status_code < 500 and status_code not in ambiguous_statuses


def _record_reconciliation_required(
    *,
    ports: VmStartExecutionPorts,
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
    lock_handle: VmStartTargetLockHandle | None,
    recovery_lease: RecoveryLease | None = None,
    actor: dict[str, Any] | None = None,
) -> None:
    lock = _lock_evidence(lock_handle, retained=True)
    compact_task = _recovery_task_payload(task)
    compact_observed = _recovery_observed_payload(
        observed_after,
        node_id=str(target.get("node_id") or ""),
        vmid=int(target.get("vmid") or 0),
    )
    result = {
        "job_id": job_id,
        "status": "needs_reconciliation",
        "code": code,
        "message": message,
        "target": target,
        "task": compact_task,
        "upid": upid,
        "observed_before": observed_before,
        "observed_after": compact_observed,
        "observed_after_artifact": artifact or {},
        "artifacts": [artifact] if artifact else [],
        "idempotency_key": idempotency_key,
        "reconciliation_required": True,
        "target_operation_lock": lock,
        "proxmox_mutation_enabled": True,
        "side_effects": side_effects,
    }
    transition_payload = {
        "code": code,
        "message": message,
        "task": compact_task,
        "observed_after": compact_observed,
        "side_effects": side_effects,
    }
    if ports.recovery is not None and recovery_lease is not None:
        try:
            ports.recovery.commit_observation(
                recovery_lease,
                next_status="needs_reconciliation",
                event_type="reconciliation_required",
                stage=stage,
                payload=transition_payload,
                details_patch={"reconciliation_code": code},
                expected_statuses=["dispatching", "running", "verifying"],
                recovery_status="paused" if not upid else "retry_wait",
                retry_delay_seconds=30 if upid else 0,
                error_code=code,
                recovery_details_patch={"upid": upid, "node_id": target.get("node_id"), "vmid": target.get("vmid")},
            )
        except RecoveryLeaseLost as exc:
            raise VmStartError(
                "VM_START_RECOVERY_LEASE_LOST",
                "VM start recovery ownership changed; the result was not committed",
                status_code=503,
                details={"job_id": job_id, "target": target, "side_effects": side_effects},
            ) from exc
    else:
        transition_vm_start_operation(
            ports.operations,
            job_id,
            next_status="needs_reconciliation",
            event_type="reconciliation_required",
            stage=stage,
            payload=transition_payload,
            details_patch={"reconciliation_code": code},
            expected_statuses=["dispatching", "running", "verifying"],
        )
    _record_vm_start_job(
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
            "vm_start": {
                "idempotency_key": idempotency_key,
                "expected": expected,
                "observed_before": observed_before,
                "task": compact_task,
                "observed_after": compact_observed,
                "proxmox_mutation_enabled": True,
                "reconciliation_required": True,
            },
            "vm_start_result": result,
            "target_operation_lock": lock,
        },
    )
    raise VmStartError(
        code,
        message,
        details={**result, "proxmox_start_ran": True},
    )


def _result_from_existing(job: dict[str, Any]) -> dict[str, Any]:
    details = job.get("details") if isinstance(job.get("details"), dict) else {}
    stored = details.get("vm_start_result") if isinstance(details.get("vm_start_result"), dict) else {}
    target = details.get("target") if isinstance(details.get("target"), dict) else stored.get("target", {})
    return {
        **stored,
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "target": target,
        "idempotent_replay": True,
        "proxmox_mutation_enabled": False,
        "proxmox_mutation_ran_previously": stored.get("proxmox_mutation_enabled") is True,
        "message": job.get("message") or stored.get("message") or "Existing VM start job returned for idempotency key",
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
    result = details.get("vm_start_result") if isinstance(details.get("vm_start_result"), dict) else {}
    return bool(
        job.get("status") == "failed"
        and result.get("proxmox_start_ran") is False
        and result.get("proxmox_mutation_enabled") is False
        and (
            result.get("pre_dispatch_no_effect_verified") is True
            or result.get("pre_dispatch_file_guard_cleaned") is True
        )
    )


def _close_replayed_pre_dispatch_failure(
    *,
    ports: VmStartExecutionPorts,
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
        or str(durable.get("operation_type") or "") != "vm_start"
        or int(durable.get("vmid") or 0) != vmid
    ):
        raise VmStartError(
            "VM_START_OPERATION_RECONCILIATION_REQUIRED",
            "The terminal VM start job could not be fenced to its exact pre-dispatch target lock",
            status_code=503,
            details={
                "job_id": job_id,
                "target": _target_payload(node_id, vmid),
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
                recovery_kind="vm_start_observation",
                details={
                    "node_id": node_id,
                    "vmid": vmid,
                    "target_type": "proxmox_vm",
                    "target_id": _target_lock_id(vmid),
                    "operation_type": "vm_start",
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
        if isinstance(exc, RecoveryOperationConflict):
            current_operation = ports.operations.get(job_id)
            if (
                current_operation is not None
                and current_operation.status == "failed"
                and is_pre_dispatch_terminal_no_effect(
                    operation_type=current_operation.operation_type,
                    status=current_operation.status,
                    details=current_operation.details,
                )
                and current_operation.details.get("target_lock_id") == durable.get("operation_lock_id")
                and current_operation.details.get("cluster_id") == durable.get("cluster_id")
            ):
                return _result_from_existing(job)
        raise VmStartError(
            "VM_START_OPERATION_RECONCILIATION_REQUIRED",
            "The terminal VM start job could not close its canonical pre-dispatch recovery",
            status_code=503,
            details={
                "job_id": job_id,
                "target": _target_payload(node_id, vmid),
                "target_operation_lock": lock,
                "proxmox_mutation_enabled": False,
                "side_effects": [],
            },
        ) from exc
    return _result_from_existing(job)


def _validated_request(node_id: str, vmid: int, payload: dict[str, Any]) -> tuple[str, str]:
    idempotency_key = str(payload.get("idempotency_key") or "").strip()
    if payload.get("vm_start_acknowledged") is not True:
        raise VmStartError(
            "VM_START_ACK_REQUIRED",
            "vm_start_acknowledged=true is required before starting a VM",
            details={"target": _target_payload(node_id, vmid), "proxmox_mutation_enabled": False, "side_effects": []},
        )
    if not idempotency_key:
        raise VmStartError(
            "VM_START_IDEMPOTENCY_KEY_REQUIRED",
            "A non-empty idempotency_key is required before starting a VM",
            details={"target": _target_payload(node_id, vmid), "proxmox_mutation_enabled": False, "side_effects": []},
        )
    return idempotency_key, build_operation_job_id(
        node_id=node_id,
        vmid=vmid,
        idempotency_key=idempotency_key,
    )


def _execute_vm_start_workflow(
    *,
    command: VmStartCommand,
    ports: VmStartExecutionPorts,
) -> dict[str, Any]:
    """Start a stopped VM after inventory precheck and persist Jobs/Runs evidence."""
    node_id = command.node_id
    vmid = command.vmid
    request_payload = dict(command.payload)
    actor_payload = dict(command.actor) if command.actor else {}
    idempotency_key, job_id = _validated_request(node_id, vmid, request_payload)
    stable_intent = command.stable_intent
    existing = ports.jobs.get(job_id)
    if existing:
        _ensure_idempotent_replay_matches_intent(existing, stable_intent)
        existing_operation = ports.operations.get(job_id)
        if not _is_recoverable_pre_dispatch_terminal_replay(existing, existing_operation):
            return _result_from_existing(existing)

    try:
        prepared_operation = prepare_vm_start_operation(
            ports.operations,
            command=command,
            operation_id=job_id,
            idempotency_key=idempotency_key,
        )
    except OperationIntentConflict as exc:
        raise VmStartError(
            "VM_START_IDEMPOTENCY_CONFLICT",
            "The idempotency key already belongs to a different VM start intent",
            details={
                "job_id": exc.operation_id,
                "target": stable_intent.get("target", {}),
                "requested_intent": stable_intent,
                "proxmox_mutation_enabled": False,
                "side_effects": [],
            },
        ) from exc
    if not prepared_operation.created and prepared_operation.operation.status != "planned":
        existing = ports.jobs.get(job_id)
        if existing:
            _ensure_idempotent_replay_matches_intent(existing, stable_intent)
            return _result_from_existing(existing)
        raise VmStartError(
            "VM_START_OPERATION_RECONCILIATION_REQUIRED",
            "The VM start operation exists without a compatible job projection and requires reconciliation",
            details={
                "job_id": job_id,
                "operation_id": prepared_operation.operation.operation_id,
                "operation_status": prepared_operation.operation.status,
                "target": stable_intent.get("target", {}),
                "proxmox_mutation_enabled": False,
                "side_effects": [],
            },
        )

    target_lock: VmStartTargetLockHandle | None = None
    recovery_lease: RecoveryLease | None = None
    retain_target_lock = False
    try:
        try:
            target_lock = ports.locks.acquire_target(
                "proxmox_vm",
                _target_lock_id(vmid),
                job_id,
            )
        except VmStartTargetLockBusy as exc:
            lock = dict(exc.evidence)
            existing = ports.jobs.get(job_id)
            current_operation = ports.operations.get(job_id)
            if existing:
                _ensure_idempotent_replay_matches_intent(existing, stable_intent)
                if not _is_recoverable_pre_dispatch_terminal_replay(existing, current_operation):
                    return _result_from_existing(existing)
            terminal_replay_job = existing
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
                        operation=current_operation,
                        lock=lock,
                    )
                raise VmStartError(
                    "VM_START_IN_PROGRESS",
                    "A VM start operation with this idempotency key is already in progress",
                    details={
                        "job_id": job_id,
                        "operation_id": prepared_operation.operation.operation_id,
                        "target": _target_payload(node_id, vmid),
                        "target_operation_lock": lock,
                        "proxmox_mutation_enabled": False,
                        "side_effects": [],
                    },
                ) from exc
            if terminal_replay_job is not None:
                ports.operations.transition_for_target_lock_conflict(
                    job_id,
                    conflicting_lock_id=str((lock.get("existing") or {}).get("operation_lock_id") or ""),
                    conflicting_owner_id=conflicting_operation_id or "",
                    next_status="failed",
                    event_type="replayed_pre_dispatch_failure_closed",
                    stage="reconciliation",
                    payload={"mutation_dispatched": False, "target_lock_owned_by_replay": False},
                    details_patch={"result_status": "failed", "recovered_pre_dispatch": True},
                )
                return _result_from_existing(terminal_replay_job)
            if conflicting_operation_id is not None:
                conflict_evidence["conflicting_operation_id"] = conflicting_operation_id
            ports.operations.transition_for_target_lock_conflict(
                job_id,
                conflicting_lock_id=str((lock.get("existing") or {}).get("operation_lock_id") or ""),
                conflicting_owner_id=conflicting_operation_id or "",
                next_status="blocked",
                event_type="target_lock_blocked",
                stage="precheck",
                payload=conflict_evidence,
                details_patch=conflict_evidence,
            )
            _raise_target_lock_busy(
                exc,
                operation_id=prepared_operation.operation.operation_id,
                node_id=node_id,
                vmid=vmid,
            )

        # A preceding request can finish between our initial lookup and target
        # lock acquisition. Only the state read while owning this lock can
        # authorize a new running projection and dispatch.
        existing = ports.jobs.get(job_id)
        current_operation = ports.operations.get(job_id)
        if existing:
            _ensure_idempotent_replay_matches_intent(existing, stable_intent)
            if not _is_recoverable_pre_dispatch_terminal_replay(existing, current_operation):
                return _result_from_existing(existing)
            retain_target_lock = True
            result = _close_replayed_pre_dispatch_failure(
                ports=ports,
                job_id=job_id,
                node_id=node_id,
                vmid=vmid,
                job=existing,
                operation=current_operation,
                lock=_lock_evidence(target_lock),
            )
            retain_target_lock = False
            return result

        if current_operation is None or current_operation.status != "planned":
            raise VmStartError(
                "VM_START_OPERATION_RECONCILIATION_REQUIRED",
                "The VM start operation exists without a compatible job projection and requires reconciliation",
                details={
                    "job_id": job_id,
                    "operation_id": job_id,
                    "operation_status": current_operation.status if current_operation is not None else None,
                    "target": stable_intent.get("target", {}),
                    "proxmox_mutation_enabled": False,
                    "side_effects": [],
                },
            )

        target = _target_payload(node_id, vmid, str(request_payload.get("expected_name") or ""))
        _record_vm_start_job(
            jobs=ports.jobs,
            job_id=job_id,
            status="running",
            stage="precheck",
            step_status="running",
            message="VM start precheck is running.",
            target=target,
            actor=actor_payload,
            intent=stable_intent,
            details={
                "vm_start": {
                    "idempotency_key": idempotency_key,
                    "expected": _expected_context(request_payload),
                    "proxmox_mutation_enabled": False,
                },
                "target_operation_lock": _lock_evidence(target_lock),
            },
        )
        try:
            precheck = evaluate_vm_start_precheck(
                ports.workloads,
                node_id=node_id,
                vmid=vmid,
                payload=request_payload,
            )
        except VmStartPrecheckBlocked as blocked:
            retain_target_lock = True
            try:
                _raise_precheck_block(
                    ports=ports,
                    job_id=job_id,
                    blocked=blocked,
                    actor=actor_payload,
                    intent=stable_intent,
                    lock_handle=target_lock,
                )
            except VmStartError as exc:
                if exc.code == blocked.code:
                    retain_target_lock = False
                raise
        try:
            proxmox_client = ports.mutation_factory()
        except VmStartMutationFailure as exc:
            retain_target_lock = True
            result = {
                "job_id": job_id,
                "status": "failed",
                "message": "Proxmox mutation client is unavailable for VM start",
                "target": precheck.target,
                "observed_before": precheck.observed_before,
                "observed_after": {},
                "artifacts": [],
                "idempotency_key": idempotency_key,
                "target_operation_lock": _lock_evidence(target_lock),
                "pre_dispatch_no_effect_verified": False,
                "proxmox_start_ran": False,
                "proxmox_mutation_enabled": False,
                "side_effects": [],
            }
            result["pre_dispatch_no_effect_verified"] = True
            _record_vm_start_job(
                jobs=ports.jobs,
                job_id=job_id,
                status="failed",
                stage="start",
                step_status="failed",
                message=result["message"],
                target=precheck.target,
                actor=actor_payload,
                intent=stable_intent,
                details={"vm_start_result": result, "target_operation_lock": _lock_evidence(target_lock)},
            )
            no_effect = _pre_dispatch_terminal_no_effect_marker(
                target_lock,
                reason="mutation_client_unavailable",
            )
            completed_without_recovery = ports.operations.transition_pre_dispatch_failure(
                job_id,
                target_lock_id=no_effect["target_lock_id"],
                event_type="mutation_client_unavailable",
                stage="start",
                payload={"message": result["message"], **no_effect},
                details_patch=no_effect,
            )
            retain_target_lock = not completed_without_recovery
            raise VmStartError(
                "VM_START_CLIENT_UNAVAILABLE",
                result["message"],
                details=result,
            ) from exc
        if proxmox_client is None:
            retain_target_lock = True
            result = {
                "job_id": job_id,
                "status": "failed",
                "message": "Proxmox mutation client is unavailable for VM start",
                "target": precheck.target,
                "observed_before": precheck.observed_before,
                "observed_after": {},
                "artifacts": [],
                "idempotency_key": idempotency_key,
                "target_operation_lock": _lock_evidence(target_lock),
                "pre_dispatch_no_effect_verified": False,
                "proxmox_start_ran": False,
                "proxmox_mutation_enabled": False,
                "side_effects": [],
            }
            result["pre_dispatch_no_effect_verified"] = True
            _record_vm_start_job(
                jobs=ports.jobs,
                job_id=job_id,
                status="failed",
                stage="start",
                step_status="failed",
                message=result["message"],
                target=precheck.target,
                actor=actor_payload,
                intent=stable_intent,
                details={"vm_start_result": result, "target_operation_lock": _lock_evidence(target_lock)},
            )
            no_effect = _pre_dispatch_terminal_no_effect_marker(
                target_lock,
                reason="mutation_client_unavailable",
            )
            completed_without_recovery = ports.operations.transition_pre_dispatch_failure(
                job_id,
                target_lock_id=no_effect["target_lock_id"],
                event_type="mutation_client_unavailable",
                stage="start",
                payload={"message": result["message"], **no_effect},
                details_patch=no_effect,
            )
            retain_target_lock = not completed_without_recovery
            raise VmStartError(
                "VM_START_CLIENT_UNAVAILABLE",
                result["message"],
                details=result,
            )
        target = precheck.target
        _record_vm_start_job(
            jobs=ports.jobs,
            job_id=job_id,
            status="running",
            stage="start",
            step_status="running",
            message="VM start request is being sent to Proxmox.",
            target=target,
            actor=actor_payload,
            intent=stable_intent,
            details={
                "vm_start": {
                    "idempotency_key": idempotency_key,
                    "expected": precheck.expected,
                    "observed_before": precheck.observed_before,
                    "proxmox_mutation_enabled": False,
                },
                "target_operation_lock": _lock_evidence(target_lock),
            },
        )

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
                        recovery_kind="vm_start_observation",
                        details={
                            "node_id": node_id,
                            "vmid": vmid,
                            "target_type": "proxmox_vm",
                            "target_id": _target_lock_id(vmid),
                            "operation_type": "vm_start",
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
                    "message": "Durable recovery could not be registered before VM start dispatch",
                    "target": target,
                    "target_operation_lock": _lock_evidence(target_lock, retained=False),
                    "pre_dispatch_no_effect_verified": True,
                    "reconciliation_required": False,
                    "proxmox_start_ran": False,
                    "proxmox_mutation_enabled": False,
                    "side_effects": [],
                }
                _record_vm_start_job(
                    jobs=ports.jobs,
                    job_id=job_id,
                    status="failed",
                    stage="start",
                    step_status="failed",
                    message=result["message"],
                    target=target,
                    actor=actor_payload,
                    intent=stable_intent,
                    details={"vm_start_result": result, "target_operation_lock": result["target_operation_lock"]},
                )
                no_effect = _pre_dispatch_terminal_no_effect_marker(
                    target_lock,
                    reason="recovery_registration_failed",
                )
                completed_without_recovery = ports.operations.transition_pre_dispatch_failure(
                    job_id,
                    target_lock_id=no_effect["target_lock_id"],
                    event_type="recovery_registration_failed",
                    stage="start",
                    payload={"code": "VM_START_RECOVERY_UNAVAILABLE", **no_effect},
                    details_patch=no_effect,
                )
                retain_target_lock = not completed_without_recovery
                raise VmStartError(
                    "VM_START_RECOVERY_UNAVAILABLE",
                    result["message"],
                    status_code=503,
                    details=result,
                ) from exc
            try:
                _, recovery_item = ports.recovery.commit_observation(
                    recovery_lease,
                    next_status="dispatching",
                    event_type="dispatch_prepared",
                    stage="start",
                    payload={
                        "target": target,
                        "expected": precheck.expected,
                        "observed_before": precheck.observed_before,
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
                raise VmStartError(
                    "VM_START_RECOVERY_UNAVAILABLE",
                    "Durable recovery could not checkpoint VM start dispatch preparation",
                    status_code=503,
                    details={
                        "job_id": job_id,
                        "target": target,
                        "proxmox_start_ran": False,
                        "proxmox_mutation_enabled": False,
                        "side_effects": [],
                    },
                ) from exc
        else:
            transition_vm_start_operation(
                ports.operations,
                job_id,
                next_status="dispatching",
                event_type="dispatch_prepared",
                stage="start",
                payload={
                    "target": target,
                    "expected": precheck.expected,
                    "observed_before": precheck.observed_before,
                },
                expected_statuses=["planned"],
            )

        retain_target_lock = True
        try:
            raw_upid = str(proxmox_client.start_vm(node=node_id, vmid=vmid) or "").strip()
            upid = compact_proxmox_task({}, node=node_id, upid=raw_upid)["upid"]
        except VmStartMutationFailure as exc:
            error_details = compact_proxmox_error_details(exc.details)
            if _is_http_4xx_rejection(exc):
                result = {
                    "job_id": job_id,
                    "status": "failed",
                    "message": "Proxmox VM start request was rejected by the API",
                    "target": target,
                    "task": {
                        "node": node_id,
                        "upid": "",
                        "status": "failed",
                        "error": "proxmox_start_request_rejected",
                        "details": error_details,
                    },
                    "observed_before": precheck.observed_before,
                    "observed_after": {},
                    "artifacts": [],
                    "idempotency_key": idempotency_key,
                    "target_operation_lock": _lock_evidence(target_lock),
                    "proxmox_mutation_enabled": False,
                    "side_effects": ["proxmox_start_request_rejected"],
                }
                if ports.recovery is not None and recovery_lease is not None:
                    try:
                        _, recovery_item = ports.recovery.commit_observation(
                            recovery_lease,
                            next_status="failed",
                            event_type="dispatch_rejected",
                            stage="start",
                            payload={
                                "message": result["message"],
                                "task": _recovery_task_payload(result["task"]),
                            },
                            expected_statuses=["dispatching"],
                            recovery_status="leased",
                            error_code="VM_START_REQUEST_FAILED",
                            recovery_details_patch={
                                "phase": "dispatch_rejected",
                                "terminal_outcome": "failed",
                                "task": _recovery_task_payload(result["task"]),
                                "observed_after": {},
                            },
                        )
                        recovery_lease = RecoveryLease(item=recovery_item, token=recovery_lease.token)
                    except RecoveryLeaseLost as lease_exc:
                        raise VmStartError(
                            "VM_START_RECOVERY_LEASE_LOST",
                            "VM start recovery ownership changed; the rejection was not committed",
                            status_code=503,
                            details={
                                "job_id": job_id,
                                "target": target,
                                "side_effects": ["proxmox_start_request_rejected"],
                            },
                        ) from lease_exc
                else:
                    transition_vm_start_operation(
                        ports.operations,
                        job_id,
                        next_status="failed",
                        event_type="dispatch_rejected",
                        stage="start",
                        payload={
                            "message": result["message"],
                            "task": _recovery_task_payload(result["task"]),
                        },
                        expected_statuses=["dispatching"],
                    )
                try:
                    _record_vm_start_job(
                        jobs=ports.jobs,
                        job_id=job_id,
                        status="failed",
                        stage="start",
                        step_status="failed",
                        message=result["message"],
                        target=target,
                        actor=actor_payload,
                        intent=stable_intent,
                        details={"vm_start_result": result, "target_operation_lock": _lock_evidence(target_lock)},
                    )
                except Exception:
                    _persistence_failure_handoff(
                        ports=ports,
                        recovery_lease=recovery_lease,
                        job_id=job_id,
                        code="VM_START_COMPATIBILITY_PROJECTION_PERSISTENCE_UNAVAILABLE",
                        message=(
                            "VM start rejection was recorded in the canonical Operation, but the "
                            "compatibility Job projection could not be persisted"
                        ),
                        event_type="compatibility_projection_persistence_failed",
                        stage="reconciliation",
                        target=target,
                        operation_status="failed",
                        side_effects=["proxmox_start_request_rejected"],
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
                            stage="start",
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
                        raise VmStartError(
                            "VM_START_RECOVERY_LEASE_LOST",
                            "VM start recovery ownership changed before the rejected job projection was finalized",
                            status_code=503,
                            details={
                                "job_id": job_id,
                                "target": target,
                                "side_effects": ["proxmox_start_request_rejected"],
                            },
                        ) from lease_exc
                    retain_target_lock = False
                else:
                    retain_target_lock = False
                raise VmStartError(
                    "VM_START_REQUEST_FAILED",
                    result["message"],
                    details={**result, "proxmox_start_ran": False},
                ) from exc

            task = {
                "node": node_id,
                "upid": "",
                "status": "unknown",
                "exitstatus": "unknown",
                "error": "proxmox_start_request_state_unknown",
                "details": error_details,
            }
            try:
                observed_after = _status_payload(proxmox_client.get_vm_status(node=node_id, vmid=vmid))
            except VmStartMutationFailure as status_exc:
                observed_after = _status_payload(
                    {},
                    error="proxmox_vm_status_observation_unavailable",
                )
            artifact = _write_observed_artifact_or_handoff(
                ports=ports,
                recovery_lease=recovery_lease,
                job_id=job_id,
                target=target,
                idempotency_key=idempotency_key,
                expected=precheck.expected,
                observed_before=precheck.observed_before,
                task=task,
                observed_after=observed_after,
                client=proxmox_client,
                actor=actor_payload,
                operation_status="dispatching",
                stage="reconciliation",
                side_effects=["proxmox_start_request_ambiguous", "proxmox_post_check_observed"],
                target_lock=target_lock,
            )
            retain_target_lock = True
            _record_reconciliation_required(
                ports=ports,
                job_id=job_id,
                code="VM_START_REQUEST_RECONCILIATION_REQUIRED",
                message="Proxmox VM start request outcome is ambiguous and requires reconciliation",
                stage="start",
                target=target,
                intent=stable_intent,
                idempotency_key=idempotency_key,
                expected=precheck.expected,
                observed_before=precheck.observed_before,
                task=task,
                observed_after=observed_after,
                artifact=artifact,
                upid="",
                side_effects=["proxmox_start_request_ambiguous", "proxmox_post_check_observed"],
                lock_handle=target_lock,
                recovery_lease=recovery_lease,
                actor=actor_payload,
            )

        if not upid:
            task = {
                "node": node_id,
                "upid": "",
                "status": "unknown",
                "exitstatus": "unknown",
                "error": "Proxmox start did not return a UPID",
            }
            try:
                observed_after = _status_payload(proxmox_client.get_vm_status(node=node_id, vmid=vmid))
            except VmStartMutationFailure:
                observed_after = _status_payload(
                    {},
                    error="proxmox_vm_status_observation_unavailable",
                )
            artifact = _write_observed_artifact_or_handoff(
                ports=ports,
                recovery_lease=recovery_lease,
                job_id=job_id,
                target=target,
                idempotency_key=idempotency_key,
                expected=precheck.expected,
                observed_before=precheck.observed_before,
                task=task,
                observed_after=observed_after,
                client=proxmox_client,
                actor=actor_payload,
                operation_status="dispatching",
                stage="reconciliation",
                side_effects=["proxmox_start_invoked", "proxmox_post_check_observed"],
                target_lock=target_lock,
            )
            retain_target_lock = True
            _record_reconciliation_required(
                ports=ports,
                job_id=job_id,
                code="VM_START_REQUEST_RECONCILIATION_REQUIRED",
                message="Proxmox VM start request did not return a UPID and requires reconciliation",
                stage="start",
                target=target,
                intent=stable_intent,
                idempotency_key=idempotency_key,
                expected=precheck.expected,
                observed_before=precheck.observed_before,
                task=task,
                observed_after=observed_after,
                artifact=artifact,
                upid="",
                side_effects=["proxmox_start_invoked", "proxmox_post_check_observed"],
                lock_handle=target_lock,
                recovery_lease=recovery_lease,
                actor=actor_payload,
            )
        if ports.recovery is not None and recovery_lease is not None:
            try:
                _, recovery_item = ports.recovery.commit_observation(
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
                recovery_lease = RecoveryLease(item=recovery_item, token=recovery_lease.token)
            except RecoveryLeaseLost as exc:
                retain_target_lock = True
                raise VmStartError(
                    "VM_START_RECOVERY_LEASE_LOST",
                    "VM start recovery ownership changed after dispatch; reconciliation is required",
                    status_code=503,
                    details={"job_id": job_id, "target": target, "upid": upid, "side_effects": ["proxmox_start_invoked"]},
                ) from exc
        else:
            transition_vm_start_operation(
                ports.operations,
                job_id,
                next_status="running",
                event_type="dispatch_accepted",
                stage="task_poll",
                payload={"upid": upid, "node_id": node_id},
                details_patch={"proxmox_upid": upid},
                expected_statuses=["dispatching"],
            )
        task: dict[str, Any] = {"node": node_id, "upid": upid}
        _record_vm_start_job(
            jobs=ports.jobs,
            job_id=job_id,
            status="running",
            stage="task_poll",
            step_status="running",
            message="Proxmox VM start task is being polled.",
            target=target,
            actor=actor_payload,
            intent=stable_intent,
            details={
                "vm_start": {
                    "idempotency_key": idempotency_key,
                    "expected": precheck.expected,
                    "observed_before": precheck.observed_before,
                    "task": task,
                    "proxmox_mutation_enabled": True,
                },
                "target_operation_lock": _lock_evidence(target_lock),
            },
        )

        observed_after: dict[str, Any]
        task_poll_ambiguous = False
        try:
            heartbeat = None
            if ports.recovery is not None and recovery_lease is not None:
                heartbeat = lambda: ports.recovery.heartbeat(
                    recovery_lease,
                    lease_seconds=ports.recovery_lease_seconds,
                )
            if heartbeat is None:
                task = proxmox_client.wait_for_task(node=node_id, upid=upid)
            else:
                task = proxmox_client.wait_for_task(node=node_id, upid=upid, heartbeat=heartbeat)
        except RecoveryLeaseLost as exc:
            retain_target_lock = True
            raise VmStartError(
                "VM_START_RECOVERY_LEASE_LOST",
                "VM start recovery ownership changed during task polling; reconciliation is required",
                status_code=503,
                details={"job_id": job_id, "target": target, "upid": upid, "side_effects": ["proxmox_start_invoked"]},
            ) from exc
        except VmStartMutationFailure as exc:
            task_poll_ambiguous = True
            task = {
                "node": node_id,
                "upid": upid,
                "status": "failed",
                "exitstatus": "unknown",
                "error": "proxmox_start_task_observation_unavailable",
                "details": compact_proxmox_error_details(exc.details),
            }
        try:
            observed_after = _status_payload(proxmox_client.get_vm_status(node=node_id, vmid=vmid))
        except VmStartMutationFailure as exc:
            observed_after = _status_payload(
                {},
                error="proxmox_vm_status_observation_unavailable",
            )

        if ports.recovery is not None and recovery_lease is not None:
            try:
                _, recovery_item = ports.recovery.commit_observation(
                    recovery_lease,
                    next_status="verifying",
                    event_type="task_and_state_observed",
                    stage="post_check",
                    payload={
                        "task": _recovery_task_payload(task),
                        "observed_after": _recovery_observed_payload(
                            observed_after,
                            node_id=node_id,
                            vmid=vmid,
                        ),
                    },
                    expected_statuses=["running"],
                    recovery_status="leased",
                    recovery_details_patch={
                        "task": _recovery_task_payload(task),
                        "observed_after": _recovery_observed_payload(
                            observed_after,
                            node_id=node_id,
                            vmid=vmid,
                        ),
                    },
                )
                recovery_lease = RecoveryLease(item=recovery_item, token=recovery_lease.token)
            except RecoveryLeaseLost as exc:
                retain_target_lock = True
                raise VmStartError(
                    "VM_START_RECOVERY_LEASE_LOST",
                    "VM start recovery ownership changed during verification; reconciliation is required",
                    status_code=503,
                    details={"job_id": job_id, "target": target, "upid": upid, "side_effects": ["proxmox_start_invoked"]},
                ) from exc
        else:
            transition_vm_start_operation(
                ports.operations,
                job_id,
                next_status="verifying",
                event_type="task_and_state_observed",
                stage="post_check",
                payload={
                    "task": _recovery_task_payload(task),
                    "observed_after": _recovery_observed_payload(
                        observed_after,
                        node_id=node_id,
                        vmid=vmid,
                    ),
                },
                expected_statuses=["running"],
            )
        artifact = _write_observed_artifact_or_handoff(
            ports=ports,
            recovery_lease=recovery_lease,
            job_id=job_id,
            target=target,
            idempotency_key=idempotency_key,
            expected=precheck.expected,
            observed_before=precheck.observed_before,
            task=task,
            observed_after=observed_after,
            client=proxmox_client,
            actor=actor_payload,
            operation_status="verifying",
            stage="post_check",
            side_effects=["proxmox_start_invoked", "proxmox_task_polled", "proxmox_post_check_observed"],
            target_lock=target_lock,
        )

        compact_task = _recovery_task_payload(task)
        compact_observed = _recovery_observed_payload(
            observed_after,
            node_id=node_id,
            vmid=vmid,
        )
        exitstatus = str(compact_task.get("exitstatus") or "").upper()
        observed_status = str(compact_observed.get("status") or "")
        side_effects = ["proxmox_start_invoked", "proxmox_task_polled", "proxmox_post_check_observed"]
        if task_poll_ambiguous or not exitstatus or exitstatus == "UNKNOWN":
            retain_target_lock = True
            _record_reconciliation_required(
                ports=ports,
                job_id=job_id,
                code="VM_START_TASK_RECONCILIATION_REQUIRED",
                message="Proxmox VM start task status is unknown and requires reconciliation",
                stage="task_poll",
                target=target,
                intent=stable_intent,
                idempotency_key=idempotency_key,
                expected=precheck.expected,
                observed_before=precheck.observed_before,
                task=task,
                observed_after=observed_after,
                artifact=artifact,
                upid=upid,
                side_effects=side_effects,
                lock_handle=target_lock,
                recovery_lease=recovery_lease,
                actor=actor_payload,
            )

        if exitstatus != "OK":
            if compact_task.get("status") != "stopped" or observed_status != "stopped":
                retain_target_lock = True
                _record_reconciliation_required(
                    ports=ports,
                    job_id=job_id,
                    code="VM_START_TASK_RECONCILIATION_REQUIRED",
                    message=(
                        "Proxmox VM start task failed but observed VM state is not safely stopped; "
                        "reconciliation is required"
                    ),
                    stage="task_poll",
                    target=target,
                    intent=stable_intent,
                    idempotency_key=idempotency_key,
                    expected=precheck.expected,
                    observed_before=precheck.observed_before,
                    task=task,
                    observed_after=observed_after,
                    artifact=artifact,
                    upid=upid,
                    side_effects=side_effects,
                    lock_handle=target_lock,
                    recovery_lease=recovery_lease,
                    actor=actor_payload,
                )
            result = {
                "job_id": job_id,
                "status": "failed",
                "message": "Proxmox VM start task failed.",
                "target": target,
                "task": _recovery_task_payload(task),
                "upid": upid,
                "observed_before": precheck.observed_before,
                "observed_after": _recovery_observed_payload(
                    observed_after,
                    node_id=node_id,
                    vmid=vmid,
                ),
                "observed_after_artifact": artifact,
                "artifacts": [artifact],
                "idempotency_key": idempotency_key,
                "target_operation_lock": _lock_evidence(target_lock),
                "proxmox_mutation_enabled": True,
                "side_effects": side_effects,
            }
            if ports.recovery is not None and recovery_lease is not None:
                try:
                    _, recovery_item = ports.recovery.commit_observation(
                        recovery_lease,
                        next_status="failed",
                        event_type="task_failed",
                        stage="task_poll",
                        payload={
                            "task": _recovery_task_payload(task),
                            "observed_after": _recovery_observed_payload(
                                observed_after,
                                node_id=node_id,
                                vmid=vmid,
                            ),
                        },
                        expected_statuses=["verifying"],
                        recovery_status="leased",
                        error_code="VM_START_TASK_FAILED",
                        recovery_details_patch={
                            "terminal_outcome": "failed",
                            "task": _recovery_task_payload(task),
                            "observed_after": _recovery_observed_payload(
                                observed_after,
                                node_id=node_id,
                                vmid=vmid,
                            ),
                        },
                    )
                    recovery_lease = RecoveryLease(item=recovery_item, token=recovery_lease.token)
                except RecoveryLeaseLost as exc:
                    retain_target_lock = True
                    raise VmStartError(
                        "VM_START_RECOVERY_LEASE_LOST",
                        "VM start recovery ownership changed; task failure was not committed",
                        status_code=503,
                        details={"job_id": job_id, "target": target, "upid": upid, "side_effects": side_effects},
                    ) from exc
            else:
                transition_vm_start_operation(
                    ports.operations,
                    job_id,
                    next_status="failed",
                    event_type="task_failed",
                    stage="task_poll",
                    payload={
                        "task": _recovery_task_payload(task),
                        "observed_after": _recovery_observed_payload(
                            observed_after,
                            node_id=node_id,
                            vmid=vmid,
                        ),
                    },
                    expected_statuses=["verifying"],
                )
            try:
                _record_vm_start_job(
                    jobs=ports.jobs,
                    job_id=job_id,
                    status="failed",
                    stage="task_poll",
                    step_status="failed",
                    message=result["message"],
                    target=target,
                    artifacts=[artifact],
                    actor=actor_payload,
                    intent=stable_intent,
                    details={"vm_start_result": result, "target_operation_lock": _lock_evidence(target_lock)},
                )
            except Exception:
                _persistence_failure_handoff(
                    ports=ports,
                    recovery_lease=recovery_lease,
                    job_id=job_id,
                    code="VM_START_COMPATIBILITY_PROJECTION_PERSISTENCE_UNAVAILABLE",
                    message=(
                        "VM start failure was recorded in the canonical Operation, but the compatibility "
                        "Job projection could not be persisted"
                    ),
                    event_type="compatibility_projection_persistence_failed",
                    stage="reconciliation",
                    target=target,
                    operation_status="failed",
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
                        stage="task_poll",
                        payload={"operation_status": "failed"},
                        expected_statuses=["failed"],
                        recovery_status="completed",
                        retry_delay_seconds=0,
                        error_code=(None),
                        release_target_lock=True,
                    )
                except RecoveryLeaseLost as exc:
                    retain_target_lock = True
                    raise VmStartError(
                        "VM_START_RECOVERY_LEASE_LOST",
                        "VM start recovery ownership changed before the failed job projection was finalized",
                        status_code=503,
                        details={"job_id": job_id, "target": target, "upid": upid, "side_effects": side_effects},
                    ) from exc
            retain_target_lock = False if ports.recovery is not None and recovery_lease is not None else False
            raise VmStartError(
                "VM_START_TASK_FAILED",
                result["message"],
                details={**result, "proxmox_start_ran": True},
            )

        if observed_status != "running":
            retain_target_lock = True
            _record_reconciliation_required(
                ports=ports,
                job_id=job_id,
                code="VM_START_POST_CHECK_RECONCILIATION_REQUIRED",
                message="VM start post-check did not verify the expected running state; reconciliation is required",
                stage="post_check",
                target=target,
                intent=stable_intent,
                idempotency_key=idempotency_key,
                expected=precheck.expected,
                observed_before=precheck.observed_before,
                task=task,
                observed_after=observed_after,
                artifact=artifact,
                upid=upid,
                side_effects=side_effects,
                lock_handle=target_lock,
                recovery_lease=recovery_lease,
                actor=actor_payload,
            )

        result = {
            "job_id": job_id,
            "status": "completed",
            "message": "VM start completed and the VM is running.",
            "target": target,
            "task": _recovery_task_payload(task),
            "upid": upid,
            "observed_before": precheck.observed_before,
            "observed_after": _recovery_observed_payload(
                observed_after,
                node_id=node_id,
                vmid=vmid,
            ),
            "observed_after_artifact": artifact,
            "artifacts": [artifact],
            "idempotent_replay": False,
            "idempotency_key": idempotency_key,
            "target_operation_lock": _lock_evidence(target_lock),
            "proxmox_mutation_enabled": True,
            "side_effects": side_effects,
        }
        if ports.recovery is not None and recovery_lease is not None:
            try:
                _, recovery_item = ports.recovery.commit_observation(
                    recovery_lease,
                    next_status="succeeded",
                    event_type="verification_succeeded",
                    stage="post_check",
                    payload={
                        "task": _recovery_task_payload(task),
                        "observed_after": _recovery_observed_payload(
                            observed_after,
                            node_id=node_id,
                            vmid=vmid,
                        ),
                        "artifact": artifact,
                    },
                    details_patch={"result_status": "completed"},
                    expected_statuses=["verifying"],
                    recovery_status="leased",
                    recovery_details_patch={
                        "terminal_outcome": "succeeded",
                        "task": _recovery_task_payload(task),
                        "observed_after": _recovery_observed_payload(
                            observed_after,
                            node_id=node_id,
                            vmid=vmid,
                        ),
                    },
                )
                recovery_lease = RecoveryLease(item=recovery_item, token=recovery_lease.token)
            except RecoveryLeaseLost as exc:
                retain_target_lock = True
                raise VmStartError(
                    "VM_START_RECOVERY_LEASE_LOST",
                    "VM start recovery ownership changed; success was not committed",
                    status_code=503,
                    details={"job_id": job_id, "target": target, "upid": upid, "side_effects": side_effects},
                ) from exc
        else:
            transition_vm_start_operation(
                ports.operations,
                job_id,
                next_status="succeeded",
                event_type="verification_succeeded",
                stage="post_check",
                payload={
                    "task": _recovery_task_payload(task),
                    "observed_after": _recovery_observed_payload(
                        observed_after,
                        node_id=node_id,
                        vmid=vmid,
                    ),
                    "artifact": artifact,
                },
                details_patch={"result_status": "completed"},
                expected_statuses=["verifying"],
            )
        try:
            _record_vm_start_job(
                jobs=ports.jobs,
                job_id=job_id,
                status="completed",
                stage="post_check",
                step_status="completed",
                message=result["message"],
                target=target,
                artifacts=[artifact],
                actor=actor_payload,
                intent=stable_intent,
                details={"vm_start_result": result, "target_operation_lock": _lock_evidence(target_lock)},
            )
        except Exception:
            _persistence_failure_handoff(
                ports=ports,
                recovery_lease=recovery_lease,
                job_id=job_id,
                code="VM_START_COMPATIBILITY_PROJECTION_PERSISTENCE_UNAVAILABLE",
                message=(
                    "VM start success was recorded in the canonical Operation, but the compatibility "
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
                retain_target_lock = True
                raise VmStartError(
                    "VM_START_RECOVERY_LEASE_LOST",
                    "VM start recovery ownership changed before the completed job projection was finalized",
                    status_code=503,
                    details={"job_id": job_id, "target": target, "upid": upid, "side_effects": side_effects},
                ) from exc
        retain_target_lock = False
        return result
    finally:
        if target_lock is not None and not retain_target_lock:
            ports.locks.release_target(target_lock)


class VerifiedVmStartWorkflow:
    """Coordinate VM Start through abstract Operations execution ports."""

    def execute(self, command: VmStartCommand, ports: VmStartExecutionPorts) -> dict[str, Any]:
        return _execute_vm_start_workflow(command=command, ports=ports)


__all__ = ["VerifiedVmStartWorkflow"]
