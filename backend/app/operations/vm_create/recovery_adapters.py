"""Production GET-only observation and idempotent Create recovery projections."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.redaction import redact_secrets
from app.db.models import JobRunRecord, VmCreateRequestRecord
from app.db.session import session_scope
from app.jobs.artifacts import (
    get_artifact_record_in_session,
    read_artifact_text_in_session,
    write_json_artifact_in_session,
)
from app.jobs.runs import record_job_run_in_session, run_dir
from app.proxmox.client import ProxmoxMutationError


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _public_request(row: VmCreateRequestRecord) -> dict[str, Any]:
    response = {
        "request_id": row.request_id,
        "status": row.status,
        "target_node_id": row.target_node_id,
        "vmid": row.vmid,
        "vm_name": row.vm_name,
        "updated_at": row.updated_at,
    }
    if row.actor_user_id or row.actor_username or row.actor_role:
        response.update(
            {
                "actor_user_id": row.actor_user_id or "",
                "actor_username": row.actor_username or "",
                "actor_role": row.actor_role or "",
                "actor": {
                    "user_id": row.actor_user_id or "",
                    "username": row.actor_username or "",
                    "role": row.actor_role or "",
                },
            }
        )
    return response


class ProxmoxVmCreateRecoveryObservationAdapter:
    """Expose only Proxmox GET methods to the recovery handler."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def get_task_status(self, *, node: str, upid: str) -> dict[str, Any]:
        return dict(self._client.get_task_status(node=node, upid=upid) or {})

    def get_vm_status(self, *, node: str, vmid: int) -> dict[str, Any]:
        try:
            return dict(self._client.get_vm_status(node=node, vmid=vmid) or {})
        except ProxmoxMutationError as exc:
            if exc.details.get("status_code") == 404:
                return {"exists": False}
            raise

    def get_vm_config(self, *, node: str, vmid: int) -> dict[str, Any]:
        return dict(self._client.get_vm_config(node=node, vmid=vmid) or {})


class SqlAlchemyVmCreateRecoveryProjection:
    """Retry-safe request/workload/job/artifact projection for observed Create results."""

    def record_pre_dispatch_failed(
        self,
        *,
        operation_id: str,
        target: Mapping[str, Any],
        code: str,
    ) -> None:
        with session_scope() as session:
            self.record_pre_dispatch_failed_in_transaction(
                session,
                operation_id=operation_id,
                target=target,
                code=code,
            )

    def record_pre_dispatch_failed_in_transaction(
        self,
        transaction: Session,
        *,
        operation_id: str,
        target: Mapping[str, Any],
        code: str,
    ) -> None:
        operation_id = str(operation_id)
        vmid = int(target.get("vmid") or 0)
        node_id = str(target.get("node_id") or "")
        now = _now_iso()
        request = transaction.scalar(
            select(VmCreateRequestRecord)
            .where(VmCreateRequestRecord.request_id == operation_id)
            .with_for_update()
        )
        job = transaction.scalar(
            select(JobRunRecord)
            .where(JobRunRecord.job_id == operation_id)
            .with_for_update()
        )
        if request is not None:
            if request.vmid != vmid or request.target_node_id != node_id:
                raise ValueError("Create recovery request target does not match")
            request.status = "failed"
            request.result = redact_secrets(
                {
                    **dict(request.result or {}),
                    "success": False,
                    "status": "failed",
                    "code": str(code),
                    "message": "Create VM stopped before any Proxmox mutation",
                    "external_effect": False,
                    "side_effects": [],
                }
            )
            request.updated_at = now
        if job is None:
            return
        if job.job_type != "vm_create":
            raise ValueError("Create recovery job type does not match")
        record_job_run_in_session(
            transaction,
            job_id=operation_id,
            job_type="vm_create",
            status="failed",
            target_id=str(job.target_id or f"{node_id}:{request.vm_name if request else vmid}"),
            risk_level=str(job.risk_level or "unknown"),
            stage="create",
            step_status="failed",
            message="Proxmox mutation 전에 Create VM 로컬 준비가 종료되었습니다.",
        )

    def record_clear_rejection(
        self,
        *,
        operation_id: str,
        target: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> None:
        with session_scope() as session:
            self.record_clear_rejection_in_transaction(
                session,
                operation_id=operation_id,
                target=target,
                evidence=evidence,
            )

    def record_clear_rejection_in_transaction(
        self,
        transaction: Session,
        *,
        operation_id: str,
        target: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> None:
        operation_id = str(operation_id)
        vmid = int(target.get("vmid") or 0)
        node_id = str(target.get("node_id") or "")
        request, job = self._locked_request_and_job(
            transaction,
            operation_id=operation_id,
            node_id=node_id,
            vmid=vmid,
        )
        request.status = "failed"
        request.result = redact_secrets(
            {
                **dict(request.result or {}),
                "success": False,
                "status": "failed",
                "message": "Proxmox clone request was definitively rejected",
                "external_effect": False,
                "mutation_replayed": False,
                "side_effects": ["proxmox_clone_rejected"],
                "recovery_evidence": dict(evidence),
            }
        )
        request.updated_at = _now_iso()
        record_job_run_in_session(
            transaction,
            job_id=operation_id,
            job_type="vm_create",
            status="failed",
            target_id=str(job.target_id or f"{node_id}:{vmid}"),
            risk_level=str(job.risk_level or "unknown"),
            stage="create",
            step_status="failed",
            message="Proxmox clone 요청이 명확히 거부되어 mutation 재호출 없이 종료되었습니다.",
        )

    def record_verified_absent_failure(
        self,
        *,
        operation_id: str,
        target: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> None:
        with session_scope() as session:
            self.record_verified_absent_failure_in_transaction(
                session,
                operation_id=operation_id,
                target=target,
                evidence=evidence,
            )

    def record_verified_absent_failure_in_transaction(
        self,
        transaction: Session,
        *,
        operation_id: str,
        target: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> None:
        operation_id = str(operation_id)
        vmid = int(target.get("vmid") or 0)
        node_id = str(target.get("node_id") or "")
        request, job = self._locked_request_and_job(
            transaction,
            operation_id=operation_id,
            node_id=node_id,
            vmid=vmid,
        )
        if job.status == "completed":
            raise ValueError("Completed Create recovery job cannot be projected as failed")
        existing_result = _mapping(request.result)
        if request.status == "completed" or existing_result.get("success") is True:
            raise ValueError("Completed Create recovery request cannot be projected as failed")
        bounded_evidence = _mapping(redact_secrets(dict(evidence)))
        request.status = "failed"
        request.result = redact_secrets(
            {
                **existing_result,
                "job_id": operation_id,
                "vmid": vmid,
                "target_node_id": node_id,
                "success": False,
                "status": "failed",
                "message": (
                    "Stored Proxmox task failed and exact VM absence was verified "
                    "by GET-only recovery observation"
                ),
                "target_absence_verified": True,
                "recovered_after_restart": True,
                "mutation_replayed": False,
                "recovery_evidence": bounded_evidence,
            }
        )
        request.updated_at = _now_iso()
        record_job_run_in_session(
            transaction,
            job_id=operation_id,
            job_type="vm_create",
            status="failed",
            target_id=str(job.target_id or f"{node_id}:{vmid}"),
            risk_level=str(job.risk_level or "unknown"),
            stage="create",
            step_status="failed",
            message=(
                "저장된 Proxmox task 실패와 exact VM 부재가 확인되어 "
                "mutation 재호출 없이 종료되었습니다."
            ),
        )

    def record_verified_success(
        self,
        *,
        operation_id: str,
        target: Mapping[str, Any],
        observed_after: Mapping[str, Any],
        observed_after_artifact: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
        with session_scope() as session:
            return self.record_verified_success_in_transaction(
                session,
                operation_id=operation_id,
                target=target,
                observed_after=observed_after,
                observed_after_artifact=observed_after_artifact,
            )

    def record_verified_success_in_transaction(
        self,
        transaction: Session,
        *,
        operation_id: str,
        target: Mapping[str, Any],
        observed_after: Mapping[str, Any],
        observed_after_artifact: Mapping[str, Any],
        completion_result: Mapping[str, Any] | None = None,
        recovered_after_restart: bool = True,
        job_details_patch: Mapping[str, Any] | None = None,
    ) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
        operation_id = str(operation_id)
        node_id = str(target.get("node_id") or "")
        vmid = int(target.get("vmid") or 0)
        observed = _mapping(redact_secrets(dict(observed_after)))
        instance_id = f"{node_id}:{vmid}"
        request, job = self._locked_request_and_job(
            transaction,
            operation_id=operation_id,
            node_id=node_id,
            vmid=vmid,
        )
        declared_artifact_id = str(observed_after_artifact.get("artifact_id") or "").strip()
        declared_checksum = str(observed_after_artifact.get("checksum") or "").strip()
        if declared_artifact_id or declared_checksum:
            if not declared_artifact_id or not declared_checksum:
                raise ValueError("Create recovery artifact binding is incomplete")
            existing_artifact = get_artifact_record_in_session(
                transaction,
                declared_artifact_id,
                expected_job_id=operation_id,
                expected_artifact_type="observed_after",
            )
            if existing_artifact is None or existing_artifact.checksum != declared_checksum:
                raise ValueError("Create recovery artifact binding does not match")
            try:
                artifact_payload = json.loads(
                    read_artifact_text_in_session(
                        transaction,
                        existing_artifact,
                        expected_job_id=operation_id,
                        expected_artifact_type="observed_after",
                        expected_checksum=declared_checksum,
                    )
                )
            except (FileNotFoundError, json.JSONDecodeError, TypeError) as exc:
                raise ValueError("Create recovery artifact content is unavailable") from exc
            bounded_artifact_payload = _mapping(redact_secrets(artifact_payload))
            if (
                not observed
                or bounded_artifact_payload != observed
            ):
                raise ValueError("Create recovery artifact content does not match")
            artifact = existing_artifact.to_dict()
        else:
            artifact = write_json_artifact_in_session(
                transaction,
                run_dir=run_dir(operation_id),
                job_id=operation_id,
                artifact_type="observed_after",
                filename="observed_after.json",
                payload=observed,
            ).to_dict()

        now = _now_iso()
        existing_result = _mapping(request.result)
        historical_side_effects = list(existing_result.get("side_effects") or [])
        request.status = "completed"
        if completion_result is None:
            result_payload = {
                **existing_result,
                "job_id": operation_id,
                "vmid": vmid,
                "target_node_id": node_id,
                "success": True,
                "status": "completed",
                "message": "Create VM was verified by GET-only recovery observation",
                "observed_after": observed,
                "observed_after_artifact": artifact,
                "artifacts": [artifact],
                "side_effects": historical_side_effects,
                "recovered_after_restart": True,
                "mutation_replayed": False,
            }
        else:
            result_payload = {
                **existing_result,
                **dict(completion_result),
                "job_id": operation_id,
                "vmid": vmid,
                "target_node_id": node_id,
                "success": True,
                "status": "completed",
                "observed_after": observed,
                "observed_after_artifact": artifact,
                "artifacts": [artifact],
            }
            if recovered_after_restart:
                result_payload.update(
                    {"recovered_after_restart": True, "mutation_replayed": False}
                )
        request.result = redact_secrets(result_payload)
        request.updated_at = now

        request_payload = _mapping(request.request_payload)
        request_payload_out = _public_request(request)
        workload_payload_out = {
            "vm_instance_id": instance_id, "node_id": node_id, "vmid": vmid,
            "name": request.vm_name, "status": str(observed.get("status") or "stopped"),
            "updated_at": now,
        }
        risk_level = str(_mapping(request_payload.get("risk_summary")).get("level") or "unknown")
        record_job_run_in_session(
            transaction,
            job_id=operation_id,
            job_type="vm_create",
            status="completed",
            target_id=str(job.target_id or f"{node_id}:{request.vm_name}"),
            risk_level=str(job.risk_level or risk_level),
            stage="create",
            step_status="completed",
            message=(
                "GET-only 복구 관찰로 Proxmox VM 생성 결과가 검증되었습니다."
                if recovered_after_restart
                else "Proxmox native VM 생성이 완료되었습니다."
            ),
            artifacts=[artifact],
            details={
                **_mapping(job.details),
                **_mapping(job_details_patch),
            },
        )
        return request_payload_out, workload_payload_out, artifact

    @staticmethod
    def _locked_request_and_job(
        transaction: Session,
        *,
        operation_id: str,
        node_id: str,
        vmid: int,
    ) -> tuple[VmCreateRequestRecord, JobRunRecord]:
        request = transaction.scalar(
            select(VmCreateRequestRecord)
            .where(VmCreateRequestRecord.request_id == operation_id)
            .with_for_update()
        )
        if request is None:
            raise LookupError(f"Create recovery request is missing: {operation_id}")
        if request.target_node_id != node_id or request.vmid != vmid:
            raise ValueError("Create recovery request target does not match")
        job = transaction.scalar(
            select(JobRunRecord)
            .where(JobRunRecord.job_id == operation_id)
            .with_for_update()
        )
        if job is None:
            raise LookupError(f"Create recovery job projection is missing: {operation_id}")
        if job.job_type != "vm_create":
            raise ValueError("Create recovery job type does not match")
        return request, job


__all__ = [
    "ProxmoxVmCreateRecoveryObservationAdapter",
    "SqlAlchemyVmCreateRecoveryProjection",
]
