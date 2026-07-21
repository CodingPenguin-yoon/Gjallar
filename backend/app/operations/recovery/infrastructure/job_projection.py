"""Legacy Jobs projection adapter for recovered VM Start operations."""

from __future__ import annotations

from typing import Any, Mapping

from app.jobs.runs import get_job_run, record_job_run


class SqlAlchemyVmStartRecoveryJobProjection:
    """Keep the operator-visible compatibility projection aligned before unlock."""

    def record_terminal(
        self,
        *,
        operation_id: str,
        operation_status: str,
        target: Mapping[str, Any],
        task: Mapping[str, Any],
        observed_after: Mapping[str, Any],
    ) -> None:
        existing = get_job_run(operation_id)
        if not isinstance(existing, dict):
            raise RuntimeError("VM Start compatibility job is missing")
        completed = operation_status == "succeeded"
        job_status = "completed" if completed else "failed"
        stage = "post_check" if completed else "task_poll"
        message = (
            "VM start recovery verified that the VM is running."
            if completed
            else "VM start recovery verified a terminal task failure."
        )
        previous_details = dict(existing.get("details") or {})
        previous_result = dict(previous_details.get("vm_start_result") or {})
        result = {
            **previous_result,
            "job_id": operation_id,
            "status": job_status,
            "message": message,
            "target": dict(target),
            "task": dict(task),
            "observed_after": dict(observed_after),
            "recovered_after_restart": True,
            "proxmox_mutation_enabled": True,
            "side_effects": ["proxmox_task_observed", "proxmox_post_check_observed"],
        }
        record_job_run(
            job_id=operation_id,
            job_type="vm_start",
            status=job_status,
            target_id=str(existing.get("target_id") or f"{target.get('node_id', '')}:{target.get('vmid', '')}"),
            risk_level=str(existing.get("risk_level") or "unknown"),
            stage=stage,
            step_status=job_status,
            message=message,
            details={**previous_details, "vm_start_result": result},
        )


class SqlAlchemyVmShutdownRecoveryJobProjection:
    """Keep the shutdown Jobs projection aligned before target unlock."""

    def record_terminal(
        self,
        *,
        operation_id: str,
        operation_status: str,
        target: Mapping[str, Any],
        task: Mapping[str, Any],
        observed_after: Mapping[str, Any],
    ) -> None:
        existing = get_job_run(operation_id)
        if not isinstance(existing, dict):
            raise RuntimeError("VM Shutdown compatibility job is missing")
        completed = operation_status == "succeeded"
        job_status = "completed" if completed else "failed"
        message = (
            "VM shutdown recovery verified that the VM is stopped."
            if completed
            else "VM shutdown recovery recorded a terminal failure."
        )
        previous_details = dict(existing.get("details") or {})
        previous_result = dict(previous_details.get("vm_shutdown_result") or {})
        result = {
            **previous_result,
            "job_id": operation_id,
            "status": job_status,
            "message": message,
            "target": dict(target),
            "task": dict(task),
            "observed_after": dict(observed_after),
            "recovered_after_restart": True,
            "proxmox_mutation_enabled": True,
            "forced_stop_enabled": False,
            "side_effects": ["proxmox_task_observed", "proxmox_post_check_observed"],
        }
        record_job_run(
            job_id=operation_id,
            job_type="vm_shutdown",
            status=job_status,
            target_id=str(existing.get("target_id") or f"{target.get('node_id', '')}:{target.get('vmid', '')}"),
            risk_level=str(existing.get("risk_level") or "high"),
            stage="post_check",
            step_status=job_status,
            message=message,
            details={**previous_details, "vm_shutdown_result": result},
        )


__all__ = ["SqlAlchemyVmShutdownRecoveryJobProjection", "SqlAlchemyVmStartRecoveryJobProjection"]
