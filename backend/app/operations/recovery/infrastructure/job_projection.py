"""Legacy Jobs projection adapter for recovered VM Start operations."""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import JobRunRecord
from app.db.session import session_scope
from app.jobs.runs import record_job_run_in_session


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
        mutation_dispatched: bool = True,
    ) -> None:
        with session_scope() as session:
            self.record_terminal_in_transaction(
                session,
                operation_id=operation_id,
                operation_status=operation_status,
                target=target,
                task=task,
                observed_after=observed_after,
                mutation_dispatched=mutation_dispatched,
            )

    def record_terminal_in_transaction(
        self,
        transaction: Session,
        *,
        operation_id: str,
        operation_status: str,
        target: Mapping[str, Any],
        task: Mapping[str, Any],
        observed_after: Mapping[str, Any],
        mutation_dispatched: bool = True,
    ) -> None:
        row = transaction.scalar(
            select(JobRunRecord)
            .where(JobRunRecord.job_id == operation_id)
            .with_for_update()
        )
        if row is None and mutation_dispatched:
            raise RuntimeError("VM Start compatibility job is missing")
        if row is not None and row.job_type != "vm_start":
            raise RuntimeError("VM Start compatibility job type does not match")
        existing = {
            "target_id": row.target_id,
            "risk_level": row.risk_level,
            "details": dict(row.details or {}),
        } if row is not None else {}
        completed = operation_status == "succeeded"
        job_status = "completed" if completed else "blocked" if operation_status == "blocked" else "failed"
        no_effect = mutation_dispatched is False
        stage = "post_check" if completed else "reconciliation" if no_effect else "task_poll"
        if no_effect:
            message = "VM start pre-dispatch recovery closed without invoking Proxmox."
        else:
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
            "recovered_after_restart": not no_effect,
            "recovered_pre_dispatch": no_effect,
            "proxmox_start_ran": False if no_effect else previous_result.get("proxmox_start_ran"),
            "proxmox_mutation_enabled": not no_effect,
            "side_effects": [] if no_effect else ["proxmox_task_observed", "proxmox_post_check_observed"],
        }
        record_job_run_in_session(
            transaction,
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
        mutation_dispatched: bool = True,
    ) -> None:
        with session_scope() as session:
            self.record_terminal_in_transaction(
                session,
                operation_id=operation_id,
                operation_status=operation_status,
                target=target,
                task=task,
                observed_after=observed_after,
                mutation_dispatched=mutation_dispatched,
            )

    def record_terminal_in_transaction(
        self,
        transaction: Session,
        *,
        operation_id: str,
        operation_status: str,
        target: Mapping[str, Any],
        task: Mapping[str, Any],
        observed_after: Mapping[str, Any],
        mutation_dispatched: bool = True,
    ) -> None:
        row = transaction.scalar(
            select(JobRunRecord)
            .where(JobRunRecord.job_id == operation_id)
            .with_for_update()
        )
        if row is None and mutation_dispatched:
            raise RuntimeError("VM Shutdown compatibility job is missing")
        if row is not None and row.job_type != "vm_shutdown":
            raise RuntimeError("VM Shutdown compatibility job type does not match")
        existing = {
            "target_id": row.target_id,
            "risk_level": row.risk_level,
            "details": dict(row.details or {}),
        } if row is not None else {}
        completed = operation_status == "succeeded"
        job_status = "completed" if completed else "blocked" if operation_status == "blocked" else "failed"
        no_effect = mutation_dispatched is False
        if no_effect:
            message = "VM shutdown pre-dispatch recovery closed without invoking Proxmox."
        else:
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
            "recovered_after_restart": not no_effect,
            "recovered_pre_dispatch": no_effect,
            "proxmox_shutdown_ran": False if no_effect else previous_result.get("proxmox_shutdown_ran"),
            "proxmox_mutation_enabled": not no_effect,
            "forced_stop_enabled": False,
            "side_effects": [] if no_effect else ["proxmox_task_observed", "proxmox_post_check_observed"],
        }
        record_job_run_in_session(
            transaction,
            job_id=operation_id,
            job_type="vm_shutdown",
            status=job_status,
            target_id=str(existing.get("target_id") or f"{target.get('node_id', '')}:{target.get('vmid', '')}"),
            risk_level=str(existing.get("risk_level") or "high"),
            stage="reconciliation" if no_effect else "post_check",
            step_status=job_status,
            message=message,
            details={**previous_details, "vm_shutdown_result": result},
        )


__all__ = ["SqlAlchemyVmShutdownRecoveryJobProjection", "SqlAlchemyVmStartRecoveryJobProjection"]
