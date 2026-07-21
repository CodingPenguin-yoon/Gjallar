"""Verified VM Start application workflow."""

from __future__ import annotations

from typing import Any, NoReturn

from app.operations.core.domain import OperationIntentConflict
from app.operations.recovery.domain import RecoveryLease, RecoveryLeaseLost, RecoverySpec
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
) -> NoReturn:
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
        },
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

    return {
        "node": str(task.get("node") or ""),
        "upid": str(task.get("upid") or ""),
        "status": str(task.get("status") or ""),
        "exitstatus": str(task.get("exitstatus") or ""),
    }


def _recovery_observed_payload(observed: dict[str, Any], *, node_id: str, vmid: int) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "vmid": vmid,
        "name": str(observed.get("name") or ""),
        "status": str(observed.get("status") or ""),
        "error": str(observed.get("error") or ""),
    }


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
        "task": task,
        "observed_after": observed_after,
        "evidence": {
            "connection": client.redacted_connection_context(),
            "start_endpoint": f"/nodes/{node_id}/qemu/{vmid}/status/start",
            "task_status_endpoint": f"/nodes/{node_id}/tasks/{task.get('upid', '')}/status" if task.get("upid") else "",
            "post_check_endpoint": f"/nodes/{node_id}/qemu/{vmid}/status/current",
        },
    }
    payload.update(_actor_detail_fields(actor))
    return evidence.write_json(
        job_id=job_id,
        artifact_type="vm_start_observed_after",
        filename="vm_start_observed_after.json",
        payload=payload,
    )


def _lock_evidence(handle: VmStartTargetLockHandle | None, *, retained: bool = False) -> dict[str, Any]:
    if handle is None:
        return {}
    payload = dict(handle.evidence)
    payload["status"] = "reconciliation_required" if retained else "active"
    return payload


def _raise_target_lock_busy(exc: VmStartTargetLockBusy, *, node_id: str, vmid: int) -> None:
    lock = dict(exc.evidence)
    raise VmStartError(
        "VM_START_TARGET_LOCK_BUSY",
        "Another VM mutation for this target is already in progress or awaiting reconciliation",
        details={
            "target": _target_payload(node_id, vmid),
            "target_operation_lock": lock,
            "proxmox_mutation_enabled": False,
            "side_effects": [],
        },
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
    result = {
        "job_id": job_id,
        "status": "needs_reconciliation",
        "code": code,
        "message": message,
        "target": target,
        "task": task,
        "upid": upid,
        "observed_before": observed_before,
        "observed_after": observed_after,
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
        "task": task,
        "observed_after": observed_after,
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
                "task": task,
                "observed_after": observed_after,
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

    lock_fd: int | None = None
    target_lock: VmStartTargetLockHandle | None = None
    recovery_lease: RecoveryLease | None = None
    retain_target_lock = False
    try:
        lock_fd = ports.locks.acquire_request(job_id)
        existing = ports.jobs.get(job_id)
        if existing:
            _ensure_idempotent_replay_matches_intent(existing, stable_intent)
            return _result_from_existing(existing)

        try:
            target_lock = ports.locks.acquire_target(
                "proxmox_vm",
                _target_lock_id(vmid),
                job_id,
            )
        except VmStartTargetLockBusy as exc:
            ports.operations.append_event(
                job_id,
                event_type="target_lock_blocked",
                stage="precheck",
                payload={"target_operation_lock": exc.evidence},
                expected_statuses=["planned"],
            )
            _raise_target_lock_busy(exc, node_id=node_id, vmid=vmid)

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
            _raise_precheck_block(
                ports=ports,
                job_id=job_id,
                blocked=blocked,
                actor=actor_payload,
                intent=stable_intent,
            )
        try:
            proxmox_client = ports.mutation_factory()
        except VmStartMutationFailure as exc:
            result = {
                "job_id": job_id,
                "status": "failed",
                "message": f"Proxmox mutation client is unavailable for VM start: {exc}",
                "target": precheck.target,
                "observed_before": precheck.observed_before,
                "observed_after": {},
                "artifacts": [],
                "idempotency_key": idempotency_key,
                "target_operation_lock": _lock_evidence(target_lock),
                "proxmox_mutation_enabled": False,
                "side_effects": [],
            }
            transition_vm_start_operation(
                ports.operations,
                job_id,
                next_status="failed",
                event_type="mutation_client_unavailable",
                stage="start",
                payload={"message": result["message"]},
                expected_statuses=["planned"],
            )
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
            raise VmStartError(
                "VM_START_CLIENT_UNAVAILABLE",
                result["message"],
                details=result,
            ) from exc
        if proxmox_client is None:
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
                "proxmox_mutation_enabled": False,
                "side_effects": [],
            }
            transition_vm_start_operation(
                ports.operations,
                job_id,
                next_status="failed",
                event_type="mutation_client_unavailable",
                stage="start",
                payload={"message": result["message"]},
                expected_statuses=["planned"],
            )
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

        if ports.recovery is not None:
            try:
                recovery_lease = ports.recovery.prepare_and_claim(
                    RecoverySpec(
                        operation_id=job_id,
                        recovery_kind="vm_start_observation",
                        details={
                            "node_id": node_id,
                            "vmid": vmid,
                            "target_type": "proxmox_vm",
                            "target_id": _target_lock_id(vmid),
                        },
                    ),
                    lease_owner=f"foreground:{job_id}",
                    lease_seconds=ports.recovery_lease_seconds,
                )
            except Exception as exc:
                transition_vm_start_operation(
                    ports.operations,
                    job_id,
                    next_status="failed",
                    event_type="recovery_registration_failed",
                    stage="start",
                    payload={"code": "VM_START_RECOVERY_UNAVAILABLE"},
                    expected_statuses=["dispatching"],
                )
                retain_target_lock = False
                raise VmStartError(
                    "VM_START_RECOVERY_UNAVAILABLE",
                    "Durable recovery could not be registered before VM start dispatch",
                    status_code=503,
                    details={
                        "job_id": job_id,
                        "target": target,
                        "proxmox_start_ran": False,
                        "proxmox_mutation_enabled": False,
                        "side_effects": [],
                    },
                ) from exc

        retain_target_lock = True
        try:
            upid = str(proxmox_client.start_vm(node=node_id, vmid=vmid) or "").strip()
        except VmStartMutationFailure as exc:
            if _is_http_4xx_rejection(exc):
                result = {
                    "job_id": job_id,
                    "status": "failed",
                    "message": f"Proxmox VM start request failed: {exc}",
                    "target": target,
                    "task": {
                        "node": node_id,
                        "upid": "",
                        "status": "failed",
                        "error": str(exc),
                        "details": exc.details,
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
                        ports.recovery.commit_observation(
                            recovery_lease,
                            next_status="failed",
                            event_type="dispatch_rejected",
                            stage="start",
                            payload={"message": result["message"], "task": result["task"]},
                            expected_statuses=["dispatching"],
                            recovery_status="completed",
                            error_code="VM_START_REQUEST_FAILED",
                            release_target_lock=True,
                        )
                    except RecoveryLeaseLost as lease_exc:
                        raise VmStartError(
                            "VM_START_RECOVERY_LEASE_LOST",
                            "VM start recovery ownership changed; the rejection was not committed",
                            status_code=503,
                            details={"job_id": job_id, "target": target, "side_effects": []},
                        ) from lease_exc
                else:
                    transition_vm_start_operation(
                        ports.operations,
                        job_id,
                        next_status="failed",
                        event_type="dispatch_rejected",
                        stage="start",
                        payload={"message": result["message"], "task": result["task"]},
                        expected_statuses=["dispatching"],
                    )
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
                "error": str(exc),
                "details": exc.details,
            }
            try:
                observed_after = _status_payload(proxmox_client.get_vm_status(node=node_id, vmid=vmid))
            except VmStartMutationFailure as status_exc:
                observed_after = _status_payload({}, error=str(status_exc))
            artifact = _write_observed_artifact(
                evidence=ports.evidence,
                job_id=job_id,
                target=target,
                idempotency_key=idempotency_key,
                expected=precheck.expected,
                observed_before=precheck.observed_before,
                task=task,
                observed_after=observed_after,
                client=proxmox_client,
                actor=actor_payload,
            )
            retain_target_lock = True
            _record_reconciliation_required(
                ports=ports,
                job_id=job_id,
                code="VM_START_REQUEST_RECONCILIATION_REQUIRED",
                message=f"Proxmox VM start request outcome is ambiguous and requires reconciliation: {exc}",
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
            except VmStartMutationFailure as exc:
                observed_after = _status_payload({}, error=str(exc))
            artifact = _write_observed_artifact(
                evidence=ports.evidence,
                job_id=job_id,
                target=target,
                idempotency_key=idempotency_key,
                expected=precheck.expected,
                observed_before=precheck.observed_before,
                task=task,
                observed_after=observed_after,
                client=proxmox_client,
                actor=actor_payload,
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
                "error": str(exc),
                "details": exc.details,
            }
        try:
            observed_after = _status_payload(proxmox_client.get_vm_status(node=node_id, vmid=vmid))
        except VmStartMutationFailure as exc:
            observed_after = _status_payload({}, error=str(exc))

        if ports.recovery is not None and recovery_lease is not None:
            try:
                _, recovery_item = ports.recovery.commit_observation(
                    recovery_lease,
                    next_status="verifying",
                    event_type="task_and_state_observed",
                    stage="post_check",
                    payload={"task": task, "observed_after": observed_after},
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
                payload={"task": task, "observed_after": observed_after},
                expected_statuses=["running"],
            )
        artifact = _write_observed_artifact(
            evidence=ports.evidence,
            job_id=job_id,
            target=target,
            idempotency_key=idempotency_key,
            expected=precheck.expected,
            observed_before=precheck.observed_before,
            task=task,
            observed_after=observed_after,
            client=proxmox_client,
            actor=actor_payload,
        )

        exitstatus = str(task.get("exitstatus") or "").upper()
        observed_status = normalize_vm_status(observed_after.get("status"))
        side_effects = ["proxmox_start_invoked", "proxmox_task_polled", "proxmox_post_check_observed"]
        if task_poll_ambiguous or not exitstatus or exitstatus == "UNKNOWN":
            retain_target_lock = True
            _record_reconciliation_required(
                ports=ports,
                job_id=job_id,
                code="VM_START_TASK_RECONCILIATION_REQUIRED",
                message=f"Proxmox VM start task status is unknown and requires reconciliation: {task.get('error') or task.get('exitstatus') or 'unknown'}",
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
            if normalize_vm_status(task.get("status")) != "stopped" or observed_status != "stopped":
                retain_target_lock = True
                _record_reconciliation_required(
                    ports=ports,
                    job_id=job_id,
                    code="VM_START_TASK_RECONCILIATION_REQUIRED",
                    message=f"Proxmox VM start task failed but observed VM state is not safely stopped: {task.get('exitstatus') or 'unknown'}",
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
                "message": f"Proxmox VM start task failed: {task.get('exitstatus') or 'unknown'}",
                "target": target,
                "task": task,
                "upid": upid,
                "observed_before": precheck.observed_before,
                "observed_after": observed_after,
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
                        payload={"task": task, "observed_after": observed_after},
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
                    payload={"task": task, "observed_after": observed_after},
                    expected_statuses=["verifying"],
                )
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
            if ports.recovery is not None and recovery_lease is not None:
                try:
                    ports.recovery.commit_observation(
                        recovery_lease,
                        event_type="recovery_compatibility_projection_recorded",
                        stage="task_poll",
                        payload={"operation_status": "failed"},
                        expected_statuses=["failed"],
                        recovery_status="completed",
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
            retain_target_lock = False
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
                message=f"VM start post-check expected running, observed {observed_status or 'unknown'}; reconciliation is required",
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
            "task": task,
            "upid": upid,
            "observed_before": precheck.observed_before,
            "observed_after": observed_after,
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
                    "task": task,
                    "observed_after": observed_after,
                    "artifact": artifact,
                },
                details_patch={"result_status": "completed"},
                expected_statuses=["verifying"],
            )
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
        if ports.recovery is not None and recovery_lease is not None:
            try:
                ports.recovery.commit_observation(
                    recovery_lease,
                    event_type="recovery_compatibility_projection_recorded",
                    stage="post_check",
                    payload={"operation_status": "succeeded"},
                    expected_statuses=["succeeded"],
                    recovery_status="completed",
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
        ports.locks.release_request(lock_fd, job_id)
        if target_lock is not None and not retain_target_lock:
            ports.locks.release_target(target_lock)


class VerifiedVmStartWorkflow:
    """Coordinate VM Start through abstract Operations execution ports."""

    def execute(self, command: VmStartCommand, ports: VmStartExecutionPorts) -> dict[str, Any]:
        return _execute_vm_start_workflow(command=command, ports=ports)


__all__ = ["VerifiedVmStartWorkflow"]
