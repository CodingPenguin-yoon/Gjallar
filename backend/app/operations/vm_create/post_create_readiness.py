"""Exact, idempotent linkage for local post-create readiness evidence."""

from __future__ import annotations

import json

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select

from app.db.models import JobArtifactRecord
from app.db.session import session_scope
from app.operations.core.domain import OperationActor
from app.operations.core.infrastructure.models import OperationEventRecord, OperationRecord
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.core.read_models import operation_payload


POST_CREATE_READINESS_EVENT_TYPE = "post_create_readiness_evidence_linked"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _vmid(value: Any) -> int | None:
    """Normalize persisted JSON without turning corrupt ownership into an error."""

    if isinstance(value, bool):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return normalized if normalized > 0 else None


def _artifact_reference(artifact: Mapping[str, Any]) -> dict[str, str]:
    return {
        "artifact_id": str(artifact.get("artifact_id") or "").strip(),
        "type": str(artifact.get("type") or "").strip(),
        "checksum": str(artifact.get("checksum") or "").strip(),
    }


def ensure_post_create_readiness_operation_link(
    *,
    node_id: str,
    vmid: int,
    create_operation_id: str = "",
    readiness_job_id: str,
    evidence_summary: Mapping[str, Any],
    artifact: Mapping[str, Any],
    actor: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Append one evidence link only when Create ownership is exact.

    Missing or mismatched compatibility ownership deliberately remains
    Jobs-only. Persistence and integrity failures are raised so an idempotent
    replay can retry the local link without recreating the evidence artifact.
    """

    normalized_node = str(node_id).strip()
    normalized_vmid = int(vmid)
    normalized_job_id = str(readiness_job_id).strip()
    artifact_ref = _artifact_reference(artifact)
    if (
        not normalized_node
        or normalized_vmid <= 0
        or not normalized_job_id
        or not artifact_ref["artifact_id"]
        or artifact_ref["type"] != "post_create_readiness_evidence"
        or not artifact_ref["checksum"]
    ):
        return None

    operations = SqlAlchemyOperationStore()
    owner_operation_id = ""
    with session_scope() as session:
        artifact_row = session.get(JobArtifactRecord, artifact_ref["artifact_id"])
        if (
            artifact_row is None
            or str(artifact_row.job_id) != normalized_job_id
            or str(artifact_row.type) != "post_create_readiness_evidence"
            or str(artifact_row.checksum) != artifact_ref["checksum"]
        ):
            return None

        owner_operation_id = str(create_operation_id).strip()
        if not owner_operation_id:
            return None
        evidence_payload = json.loads(artifact_row.content_text)
        evidence_target = _mapping(evidence_payload.get("target"))
        if (
            evidence_payload.get("create_operation_id") != owner_operation_id
            or evidence_payload.get("job_id") != normalized_job_id
            or evidence_target.get("node_id") != normalized_node
            or _vmid(evidence_target.get("vmid")) != normalized_vmid
        ):
            return None
        operation = session.scalar(
            select(OperationRecord)
            .where(OperationRecord.operation_id == owner_operation_id)
            .with_for_update()
        )
        if operation is None:
            return None

        target = _mapping(_mapping(operation.details).get("target"))
        projected_workload = _mapping(_mapping(operation.details).get("workload"))
        exact_owner = bool(
            operation.operation_type == "vm_create"
            and operation.execution_mode == "managed_api"
            and operation.status == "succeeded"
            and operation.target_type == "proxmox_vm"
            and operation.target_id == f"vmid:{normalized_vmid}"
            and str(target.get("node_id") or "") == normalized_node
            and _vmid(target.get("vmid")) == normalized_vmid
            and str(projected_workload.get("vm_instance_id") or "")
            == f"{normalized_node}:{normalized_vmid}"
            and str(projected_workload.get("node_id") or "") == normalized_node
            and _vmid(projected_workload.get("vmid")) == normalized_vmid
        )
        if not exact_owner:
            return None

        existing_events = session.scalars(
            select(OperationEventRecord)
            .where(
                OperationEventRecord.operation_id == owner_operation_id,
                OperationEventRecord.event_type == POST_CREATE_READINESS_EVENT_TYPE,
            )
            .order_by(OperationEventRecord.sequence.asc())
        ).all()
        already_linked = False
        for event in existing_events:
            payload = _mapping(event.payload)
            if str(payload.get("readiness_job_id") or "") != normalized_job_id:
                continue
            recorded_artifact = _mapping(payload.get("artifact"))
            if (
                str(recorded_artifact.get("artifact_id") or "") != artifact_ref["artifact_id"]
                or str(recorded_artifact.get("checksum") or "") != artifact_ref["checksum"]
            ):
                raise ValueError(
                    "Post-create readiness job is already linked to different artifact evidence"
                )
            already_linked = True
            break

        link_summary = {
            "readiness_job_id": normalized_job_id,
            "target": {"node_id": normalized_node, "vmid": normalized_vmid},
            "evidence_summary": dict(evidence_summary),
            "artifact": artifact_ref,
            "local_evidence_only": True,
            "live_checks_performed_by_gjallar": False,
        }
        if not already_linked:
            operations.append_in_session(
                session,
                owner_operation_id,
                next_status=None,
                event_type=POST_CREATE_READINESS_EVENT_TYPE,
                stage="post_check",
                payload=link_summary,
                details_patch={"post_create_readiness_evidence": link_summary},
                actor=OperationActor.from_mapping(actor or {}),
                expected_statuses=["succeeded"],
                is_transition=False,
            )

    linked_operation = operations.get(owner_operation_id)
    if linked_operation is None:
        raise RuntimeError("Linked Create Operation disappeared after readiness evidence commit")
    return operation_payload(linked_operation)


__all__ = [
    "POST_CREATE_READINESS_EVENT_TYPE",
    "ensure_post_create_readiness_operation_link",
]
