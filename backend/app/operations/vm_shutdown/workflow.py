"""Verified graceful VM Shutdown application workflow."""

from __future__ import annotations

from typing import Any, NoReturn

from app.operations.core.domain import OperationIntentConflict
from app.operations.recovery.domain import RecoveryLease, RecoveryLeaseLost, RecoverySpec
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


def _compact_task(task: dict[str, Any], *, node_id: str, upid: str) -> dict[str, Any]:
    return {
        "node": str(task.get("node") or node_id),
        "upid": str(task.get("upid") or upid),
        "status": str(task.get("status") or ""),
        "exitstatus": str(task.get("exitstatus") or ""),
    }


def _compact_status(observed: dict[str, Any], *, node_id: str, vmid: int) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "vmid": vmid,
        "name": str(observed.get("name") or ""),
        "status": str(observed.get("status") or ""),
        "error": str(observed.get("error") or ""),
    }


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
        "task": task,
        "observed_after": observed_after,
        "evidence": {
            "connection": client.redacted_connection_context(),
            "shutdown_endpoint": f"/nodes/{node_id}/qemu/{vmid}/status/shutdown",
            "task_status_endpoint": f"/nodes/{node_id}/tasks/{task.get('upid', '')}/status" if task.get("upid") else "",
            "post_check_endpoint": f"/nodes/{node_id}/qemu/{vmid}/status/current",
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


def _raise_precheck(
    *,
    ports: VmShutdownExecutionPorts,
    job_id: str,
    blocked: VmShutdownPrecheckBlocked,
    actor: dict[str, Any],
    intent: dict[str, Any],
) -> NoReturn:
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
        },
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

    request_lock: Any = None
    target_lock: VmShutdownTargetLockHandle | None = None
    recovery_lease: RecoveryLease | None = None
    retain_target_lock = False
    try:
        request_lock = ports.locks.acquire_request(job_id)
        existing = ports.jobs.get(job_id)
        if existing:
            _ensure_replay_matches(existing, intent)
            return _existing_result(existing)
        try:
            target_lock = ports.locks.acquire_target("proxmox_vm", vm_shutdown_target_lock_id(vmid), job_id)
        except VmShutdownTargetLockBusy as exc:
            ports.operations.append_event(
                job_id,
                event_type="target_lock_blocked",
                stage="precheck",
                payload={"target_operation_lock": exc.evidence},
                expected_statuses=["planned"],
            )
            raise VmShutdownError(
                "VM_SHUTDOWN_TARGET_LOCK_BUSY",
                "Another VM mutation for this target is already in progress or awaiting reconciliation",
                details={
                    "target": vm_shutdown_target(node_id=node_id, vmid=vmid),
                    "target_operation_lock": dict(exc.evidence),
                    "proxmox_mutation_enabled": False,
                    "side_effects": [],
                },
            ) from exc

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
            _raise_precheck(ports=ports, job_id=job_id, blocked=blocked, actor=actor, intent=intent)

        try:
            client = ports.mutation_factory()
        except VmShutdownMutationFailure as exc:
            transition_vm_shutdown_operation(
                ports.operations,
                job_id,
                next_status="failed",
                event_type="mutation_client_unavailable",
                stage="shutdown",
                payload={"error_type": type(exc).__name__},
                expected_statuses=["planned"],
            )
            result = {
                "job_id": job_id,
                "status": "failed",
                "message": f"Proxmox mutation client is unavailable for VM shutdown: {exc}",
                "target": precheck.target,
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
                target=precheck.target,
                actor=actor,
                intent=intent,
                details={"vm_shutdown_result": result},
            )
            raise VmShutdownError("VM_SHUTDOWN_CLIENT_UNAVAILABLE", result["message"], details=result) from exc
        if client is None:
            result = {
                "job_id": job_id,
                "status": "failed",
                "message": "Proxmox mutation client is unavailable for VM shutdown",
                "target": precheck.target,
                "proxmox_mutation_enabled": False,
                "side_effects": [],
            }
            transition_vm_shutdown_operation(
                ports.operations,
                job_id,
                next_status="failed",
                event_type="mutation_client_unavailable",
                stage="shutdown",
                payload={"message": result["message"]},
                expected_statuses=["planned"],
            )
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
            raise VmShutdownError(
                "VM_SHUTDOWN_CLIENT_UNAVAILABLE",
                result["message"],
                status_code=503,
                details=result,
            )

        target = precheck.target
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
        if ports.recovery is not None:
            try:
                recovery_lease = ports.recovery.prepare_and_claim(
                    RecoverySpec(
                        operation_id=job_id,
                        recovery_kind="vm_shutdown_observation",
                        details={
                            "node_id": node_id,
                            "vmid": vmid,
                            "target_type": "proxmox_vm",
                            "target_id": vm_shutdown_target_lock_id(vmid),
                        },
                    ),
                    lease_owner=f"foreground:{job_id}",
                    lease_seconds=ports.recovery_lease_seconds,
                )
            except Exception as exc:
                transition_vm_shutdown_operation(
                    ports.operations,
                    job_id,
                    next_status="failed",
                    event_type="recovery_registration_failed",
                    stage="shutdown",
                    payload={"code": "VM_SHUTDOWN_RECOVERY_UNAVAILABLE"},
                    expected_statuses=["dispatching"],
                )
                result = {
                    "job_id": job_id,
                    "status": "failed",
                    "message": "Durable recovery could not be registered before VM shutdown dispatch",
                    "target": target,
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
                    details={"vm_shutdown_result": result},
                )
                raise VmShutdownError(
                    "VM_SHUTDOWN_RECOVERY_UNAVAILABLE",
                    result["message"],
                    status_code=503,
                    details=result,
                ) from exc

        retain_target_lock = True
        try:
            upid = str(client.shutdown_vm(node=node_id, vmid=vmid) or "").strip()
        except VmShutdownMutationFailure as exc:
            if _is_clear_4xx_rejection(exc):
                if ports.recovery is not None and recovery_lease is not None:
                    try:
                        ports.recovery.commit_observation(
                            recovery_lease,
                            next_status="failed",
                            event_type="dispatch_rejected",
                            stage="shutdown",
                            payload={"error_type": type(exc).__name__},
                            expected_statuses=["dispatching"],
                            recovery_status="completed",
                            error_code="VM_SHUTDOWN_REQUEST_FAILED",
                            release_target_lock=True,
                        )
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
                result = {
                    "job_id": job_id,
                    "status": "failed",
                    "message": f"Proxmox VM shutdown request was rejected: {exc}",
                    "target": target,
                    "proxmox_mutation_enabled": False,
                    "side_effects": ["proxmox_shutdown_request_rejected"],
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
                    details={"vm_shutdown_result": result},
                )
                retain_target_lock = False
                raise VmShutdownError(
                    "VM_SHUTDOWN_REQUEST_FAILED",
                    result["message"],
                    details={**result, "proxmox_shutdown_ran": False},
                ) from exc
            try:
                observed_after = _status_payload(client.get_vm_status(node=node_id, vmid=vmid))
            except VmShutdownMutationFailure as status_exc:
                observed_after = _status_payload({}, error=str(status_exc))
            task = {"node": node_id, "upid": "", "status": "unknown", "exitstatus": "unknown", "error": str(exc)}
            artifact = _write_artifact(
                evidence=ports.evidence,
                job_id=job_id,
                target=target,
                idempotency_key=idempotency_key,
                expected=precheck.expected,
                observed_before=precheck.observed_before,
                task=task,
                observed_after=observed_after,
                client=client,
                actor=actor,
            )
            _record_reconciliation(
                ports=ports,
                lease=recovery_lease,
                job_id=job_id,
                code="VM_SHUTDOWN_REQUEST_RECONCILIATION_REQUIRED",
                message=f"Proxmox VM shutdown request outcome is ambiguous and requires reconciliation: {exc}",
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
            except VmShutdownMutationFailure as exc:
                observed_after = _status_payload({}, error=str(exc))
            task = {"node": node_id, "upid": "", "status": "unknown", "exitstatus": "unknown"}
            artifact = _write_artifact(
                evidence=ports.evidence,
                job_id=job_id,
                target=target,
                idempotency_key=idempotency_key,
                expected=precheck.expected,
                observed_before=precheck.observed_before,
                task=task,
                observed_after=observed_after,
                client=client,
                actor=actor,
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
            task = {"node": node_id, "upid": upid, "status": "unknown", "exitstatus": "unknown", "error": str(exc)}
        try:
            observed_after = _status_payload(client.get_vm_status(node=node_id, vmid=vmid))
        except VmShutdownMutationFailure as exc:
            observed_after = _status_payload({}, error=str(exc))

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
        artifact = _write_artifact(
            evidence=ports.evidence,
            job_id=job_id,
            target=target,
            idempotency_key=idempotency_key,
            expected=precheck.expected,
            observed_before=precheck.observed_before,
            task=task,
            observed_after=observed_after,
            client=client,
            actor=actor,
        )
        exitstatus = str(task.get("exitstatus") or "").strip().upper()
        task_status = normalize_vm_status(task.get("status"))
        observed_status = normalize_vm_status(observed_after.get("status"))
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
        ports.locks.release_request(request_lock, job_id)
        if target_lock is not None and not retain_target_lock:
            ports.locks.release_target(target_lock)


class VerifiedVmShutdownWorkflow:
    def execute(self, command: VmShutdownCommand, ports: VmShutdownExecutionPorts) -> dict[str, Any]:
        return _execute(command, ports)


__all__ = ["VerifiedVmShutdownWorkflow"]
