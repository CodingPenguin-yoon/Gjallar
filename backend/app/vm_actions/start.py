"""Gated VM start operation with Jobs/Runs evidence."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.auth.roles import actor_detail_fields, actor_evidence
from app.core.redaction import redact_secrets
from app.jobs.artifacts import write_json_artifact
from app.jobs.runs import get_job_run, record_job_run, run_dir
from app.proxmox.client import ProxmoxMutationClient, ProxmoxMutationError


class VmStartError(RuntimeError):
    """Raised when a VM start request is blocked or fails."""

    def __init__(self, code: str, message: str, *, status_code: int = 409, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = dict(details or {})

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            **self.details,
        }


@dataclass(frozen=True)
class VmStartPrecheck:
    target: dict[str, Any]
    observed_before: dict[str, Any]
    expected: dict[str, Any]


def _safe_segment(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value)).strip("-")
    return safe[:80] or "vm"


def build_vm_start_job_id(*, node_id: str, vmid: int, idempotency_key: str) -> str:
    digest = hashlib.sha256(f"{node_id}:{int(vmid)}:{idempotency_key}".encode("utf-8")).hexdigest()[:16]
    return f"vm-start-{_safe_segment(node_id)}-{int(vmid)}-{digest}"


def _target_id(node_id: str, vmid: int, name: str = "") -> str:
    suffix = f":{name}" if name else ""
    return f"{node_id}:{int(vmid)}{suffix}"


def _target_payload(node_id: str, vmid: int, name: str = "") -> dict[str, Any]:
    return {
        "node_id": node_id,
        "vmid": int(vmid),
        "name": name,
    }


def _normalize_status(value: object) -> str:
    return str(value or "").strip().lower()


def _to_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return dict(value)
    return {}


def _vm_node_id(value: Any) -> str:
    data = _to_dict(value)
    return str(data.get("node_id") or data.get("node") or "").strip()


def _vm_vmid(value: Any) -> int | None:
    data = _to_dict(value)
    try:
        return int(data.get("vmid") if data.get("vmid") is not None else data.get("id"))
    except (TypeError, ValueError):
        return None


def _find_exact_vm(adapter: Any, *, node_id: str, vmid: int) -> tuple[Any | None, Any | None]:
    vms = list(adapter.list_vms()) if hasattr(adapter, "list_vms") else []
    exact = next((vm for vm in vms if _vm_vmid(vm) == int(vmid) and _vm_node_id(vm) == node_id), None)
    moved = next((vm for vm in vms if _vm_vmid(vm) == int(vmid) and _vm_node_id(vm) != node_id), None)
    return exact, moved


def _find_template(adapter: Any, *, node_id: str, vmid: int) -> Any | None:
    templates = list(adapter.list_templates()) if hasattr(adapter, "list_templates") else []
    return next(
        (
            template
            for template in templates
            if _vm_vmid(template) == int(vmid)
            and (not _vm_node_id(template) or _vm_node_id(template) == node_id)
        ),
        None,
    )


def _expected_context(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "expected_name": str(payload.get("expected_name") or "").strip(),
        "expected_status": str(payload.get("expected_status") or "").strip(),
    }


def _record_vm_start_job(
    *,
    job_id: str,
    status: str,
    stage: str,
    step_status: str,
    message: str,
    target: dict[str, Any],
    artifacts: list[Any] | None = None,
    details: dict[str, Any] | None = None,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    details_payload = {"target": target, **(details or {})}
    details_payload.update(actor_detail_fields(actor))
    return record_job_run(
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
        details=redact_secrets(details_payload),
    )


def _blocked_precheck(
    *,
    job_id: str,
    code: str,
    message: str,
    target: dict[str, Any],
    expected: dict[str, Any],
    observed_before: dict[str, Any] | None = None,
    actor: dict[str, Any] | None = None,
) -> None:
    _record_vm_start_job(
        job_id=job_id,
        status="blocked",
        stage="precheck",
        step_status="blocked",
        message=message,
        target=target,
        actor=actor,
        details={
            "vm_start": {
                "code": code,
                "expected": expected,
                "observed_before": observed_before or {},
                "proxmox_mutation_enabled": False,
            }
        },
    )
    raise VmStartError(
        code,
        message,
        details={
            "job_id": job_id,
            "target": target,
            "observed_before": observed_before or {},
            "proxmox_mutation_enabled": False,
            "side_effects": [],
        },
    )


def _precheck_vm_start(
    *,
    adapter: Any,
    node_id: str,
    vmid: int,
    payload: dict[str, Any],
    job_id: str,
    actor: dict[str, Any] | None = None,
) -> VmStartPrecheck:
    expected = _expected_context(payload)
    target = _target_payload(node_id, vmid, expected.get("expected_name", ""))
    exact_vm, moved_vm = _find_exact_vm(adapter, node_id=node_id, vmid=vmid)
    template = _find_template(adapter, node_id=node_id, vmid=vmid)

    if template is not None:
        observed = _to_dict(template)
        _blocked_precheck(
            job_id=job_id,
            code="VM_START_TEMPLATE_BLOCKED",
            message="VM start is blocked for templates",
            target={**target, "name": str(observed.get("name") or target.get("name") or "")},
            expected=expected,
            observed_before={**observed, "template": True},
            actor=actor,
        )

    if exact_vm is None:
        if moved_vm is not None:
            observed = _to_dict(moved_vm)
            _blocked_precheck(
                job_id=job_id,
                code="VM_START_MOVED_BLOCKED",
                message="VM start target moved from the requested node",
                target={**target, "name": str(observed.get("name") or target.get("name") or "")},
                expected=expected,
                observed_before=observed,
                actor=actor,
            )
        _blocked_precheck(
            job_id=job_id,
            code="VM_START_MISSING_BLOCKED",
            message="VM start target was not found in fresh inventory",
            target=target,
            expected=expected,
            observed_before={},
            actor=actor,
        )

    observed_before = _to_dict(exact_vm)
    target = _target_payload(node_id, vmid, str(observed_before.get("name") or target.get("name") or ""))
    if bool(observed_before.get("template")):
        _blocked_precheck(
            job_id=job_id,
            code="VM_START_TEMPLATE_BLOCKED",
            message="VM start is blocked for templates",
            target=target,
            expected=expected,
            observed_before=observed_before,
            actor=actor,
        )

    status = _normalize_status(observed_before.get("status"))
    expected_name = str(expected.get("expected_name") or "").strip()
    observed_name = str(observed_before.get("name") or "").strip()
    if expected_name and observed_name != expected_name:
        _blocked_precheck(
            job_id=job_id,
            code="VM_START_CONTEXT_MISMATCH",
            message=f"VM start context mismatch: expected name {expected_name}, observed {observed_name or 'unknown'}",
            target=target,
            expected=expected,
            observed_before=observed_before,
            actor=actor,
        )

    expected_status = _normalize_status(expected.get("expected_status"))
    if expected_status and status != expected_status:
        _blocked_precheck(
            job_id=job_id,
            code="VM_START_CONTEXT_MISMATCH",
            message=f"VM start context mismatch: expected status {expected_status}, observed {status or 'unknown'}",
            target=target,
            expected=expected,
            observed_before=observed_before,
            actor=actor,
        )

    if status != "stopped":
        _blocked_precheck(
            job_id=job_id,
            code="VM_START_NON_STOPPED_BLOCKED",
            message=f"VM start requires a stopped VM; observed {status or 'unknown'}",
            target=target,
            expected=expected,
            observed_before=observed_before,
            actor=actor,
        )

    return VmStartPrecheck(target=target, observed_before=observed_before, expected=expected)


def _status_payload(payload: Any, *, error: str | None = None) -> dict[str, Any]:
    status = dict(payload) if isinstance(payload, dict) else {}
    if error:
        status["error"] = error
    return status


def _write_observed_artifact(
    *,
    job_id: str,
    run_path: Path,
    target: dict[str, Any],
    idempotency_key: str,
    expected: dict[str, Any],
    observed_before: dict[str, Any],
    task: dict[str, Any],
    observed_after: dict[str, Any],
    client: ProxmoxMutationClient,
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
    payload.update(actor_detail_fields(actor))
    return write_json_artifact(
        run_dir=run_path,
        job_id=job_id,
        artifact_type="vm_start_observed_after",
        filename="vm_start_observed_after.json",
        payload=payload,
    ).to_dict()


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


def _acquire_lock(lock_path: Path) -> int:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise VmStartError(
            "VM_START_IN_PROGRESS",
            "A VM start operation with this idempotency key is already in progress",
            details={"job_id": lock_path.parent.name, "proxmox_mutation_enabled": False, "side_effects": []},
        ) from exc
    os.write(fd, str(os.getpid()).encode("utf-8"))
    return fd


def _release_lock(fd: int | None, lock_path: Path) -> None:
    if fd is None:
        return
    os.close(fd)
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


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
    return idempotency_key, build_vm_start_job_id(node_id=node_id, vmid=vmid, idempotency_key=idempotency_key)


def run_vm_start(
    *,
    node_id: str,
    vmid: int,
    payload: dict[str, Any] | None,
    inventory_adapter: Any,
    actor: dict[str, Any] | None = None,
    client: ProxmoxMutationClient | None = None,
    client_factory: Callable[[], ProxmoxMutationClient] | None = None,
) -> dict[str, Any]:
    """Start a stopped VM after inventory precheck and persist Jobs/Runs evidence."""
    request_payload = dict(payload or {})
    actor_payload = actor_evidence(actor) if actor is not None else {}
    idempotency_key, job_id = _validated_request(node_id, vmid, request_payload)
    existing = get_job_run(job_id)
    if existing:
        return _result_from_existing(existing)

    run_path = run_dir(job_id)
    lock_path = run_path / "vm_start.lock"
    lock_fd: int | None = None
    try:
        lock_fd = _acquire_lock(lock_path)
        existing = get_job_run(job_id)
        if existing:
            return _result_from_existing(existing)

        target = _target_payload(node_id, vmid, str(request_payload.get("expected_name") or ""))
        _record_vm_start_job(
            job_id=job_id,
            status="running",
            stage="precheck",
            step_status="running",
            message="VM start precheck is running.",
            target=target,
            actor=actor_payload,
            details={
                "vm_start": {
                    "idempotency_key": idempotency_key,
                    "expected": _expected_context(request_payload),
                    "proxmox_mutation_enabled": False,
                }
            },
        )
        precheck = _precheck_vm_start(
            adapter=inventory_adapter,
            node_id=node_id,
            vmid=vmid,
            payload=request_payload,
            job_id=job_id,
            actor=actor_payload,
        )
        try:
            proxmox_client = client if client is not None else client_factory() if client_factory is not None else None
        except ProxmoxMutationError as exc:
            result = {
                "job_id": job_id,
                "status": "failed",
                "message": f"Proxmox mutation client is unavailable for VM start: {exc}",
                "target": precheck.target,
                "observed_before": precheck.observed_before,
                "observed_after": {},
                "artifacts": [],
                "proxmox_mutation_enabled": False,
                "side_effects": [],
            }
            _record_vm_start_job(
                job_id=job_id,
                status="failed",
                stage="start",
                step_status="failed",
                message=result["message"],
                target=precheck.target,
                actor=actor_payload,
                details={"vm_start_result": result},
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
                "proxmox_mutation_enabled": False,
                "side_effects": [],
            }
            _record_vm_start_job(
                job_id=job_id,
                status="failed",
                stage="start",
                step_status="failed",
                message=result["message"],
                target=precheck.target,
                actor=actor_payload,
                details={"vm_start_result": result},
            )
            raise VmStartError(
                "VM_START_CLIENT_UNAVAILABLE",
                result["message"],
                details=result,
            )
        target = precheck.target
        _record_vm_start_job(
            job_id=job_id,
            status="running",
            stage="start",
            step_status="running",
            message="VM start request is being sent to Proxmox.",
            target=target,
            actor=actor_payload,
            details={
                "vm_start": {
                    "idempotency_key": idempotency_key,
                    "expected": precheck.expected,
                    "observed_before": precheck.observed_before,
                    "proxmox_mutation_enabled": False,
                }
            },
        )

        try:
            upid = proxmox_client.start_vm(node=node_id, vmid=vmid)
        except ProxmoxMutationError as exc:
            result = {
                "job_id": job_id,
                "status": "failed",
                "message": f"Proxmox VM start request failed: {exc}",
                "target": target,
                "task": {"node": node_id, "upid": "", "status": "failed", "error": str(exc), "details": exc.details},
                "observed_before": precheck.observed_before,
                "observed_after": {},
                "artifacts": [],
                "proxmox_mutation_enabled": False,
                "side_effects": ["proxmox_start_request_failed"],
            }
            _record_vm_start_job(
                job_id=job_id,
                status="failed",
                stage="start",
                step_status="failed",
                message=result["message"],
                target=target,
                actor=actor_payload,
                details={"vm_start_result": result},
            )
            raise VmStartError(
                "VM_START_REQUEST_FAILED",
                result["message"],
                details={**result, "proxmox_start_ran": False},
            ) from exc
        task: dict[str, Any] = {"node": node_id, "upid": upid}
        _record_vm_start_job(
            job_id=job_id,
            status="running",
            stage="task_poll",
            step_status="running",
            message="Proxmox VM start task is being polled.",
            target=target,
            actor=actor_payload,
            details={
                "vm_start": {
                    "idempotency_key": idempotency_key,
                    "expected": precheck.expected,
                    "observed_before": precheck.observed_before,
                    "task": task,
                    "proxmox_mutation_enabled": True,
                }
            },
        )

        observed_after: dict[str, Any]
        try:
            task = proxmox_client.wait_for_task(node=node_id, upid=upid)
        except ProxmoxMutationError as exc:
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
        except ProxmoxMutationError as exc:
            observed_after = _status_payload({}, error=str(exc))

        artifact = _write_observed_artifact(
            job_id=job_id,
            run_path=run_path,
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
        observed_status = _normalize_status(observed_after.get("status"))
        side_effects = ["proxmox_start_invoked", "proxmox_task_polled", "proxmox_post_check_observed"]
        if exitstatus != "OK":
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
                "proxmox_mutation_enabled": True,
                "side_effects": side_effects,
            }
            _record_vm_start_job(
                job_id=job_id,
                status="failed",
                stage="task_poll",
                step_status="failed",
                message=result["message"],
                target=target,
                artifacts=[artifact],
                actor=actor_payload,
                details={"vm_start_result": result},
            )
            raise VmStartError(
                "VM_START_TASK_FAILED",
                result["message"],
                details={**result, "proxmox_start_ran": True},
            )

        if observed_status != "running":
            result = {
                "job_id": job_id,
                "status": "failed",
                "message": f"VM start post-check expected running, observed {observed_status or 'unknown'}",
                "target": target,
                "task": task,
                "upid": upid,
                "observed_before": precheck.observed_before,
                "observed_after": observed_after,
                "observed_after_artifact": artifact,
                "artifacts": [artifact],
                "proxmox_mutation_enabled": True,
                "side_effects": side_effects,
            }
            _record_vm_start_job(
                job_id=job_id,
                status="failed",
                stage="post_check",
                step_status="failed",
                message=result["message"],
                target=target,
                artifacts=[artifact],
                actor=actor_payload,
                details={"vm_start_result": result},
            )
            raise VmStartError(
                "VM_START_POST_CHECK_FAILED",
                result["message"],
                details={**result, "proxmox_start_ran": True},
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
            "proxmox_mutation_enabled": True,
            "side_effects": side_effects,
        }
        _record_vm_start_job(
            job_id=job_id,
            status="completed",
            stage="post_check",
            step_status="completed",
            message=result["message"],
            target=target,
            artifacts=[artifact],
            actor=actor_payload,
            details={"vm_start_result": result},
        )
        return result
    finally:
        _release_lock(lock_fd, lock_path)
