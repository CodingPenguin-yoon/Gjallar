"""Composition facade for shared Operations queries."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from app.operations.core.application import (
    InvalidOperationQuery,
    OperationListQuery,
    OperationQueryNotFound,
    OperationQueryService,
)
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.core.domain import OperationActor
from app.operations.recovery.application import (
    OperationRecoveryObserveError,
    recovery_error_semantics,
)
from app.operations.recovery.domain import (
    PRE_DISPATCH_RECOVERY_CONTRACT,
    is_pre_dispatch_terminal_no_effect,
    recovery_item_payload,
)
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.recovery.runtime import build_recovery_coordinator
from app.operations.target_lock import get_target_operation_lock


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _expired_recovery_lease(recovery: Any) -> bool:
    return bool(
        recovery.status == "leased"
        and recovery.lease_expires_at is not None
        and _as_utc(recovery.lease_expires_at) <= datetime.now(timezone.utc)
    )


def _safe_no_item_pre_dispatch(
    operation: dict[str, Any],
    target_lock: dict[str, Any] | None,
    *,
    operation_id: str,
    events: list[dict[str, Any]],
) -> bool:
    operation_type = str(operation.get("operation_type") or "")
    status = str(operation.get("status") or "")
    details = dict(operation.get("details") or {})
    durable = dict(target_lock.get("durable") or {}) if isinstance(target_lock, dict) else {}
    latest_event = dict(events[-1]) if events and isinstance(events[-1], dict) else {}
    guided_unissued = bool(
        operation_type == "guided_qm_vm_unlock"
        and str(operation.get("execution_mode") or "") == "guided_manual"
        and status == "planned"
        and details.get("recovery_contract") == PRE_DISPATCH_RECOVERY_CONTRACT
        and details.get("instruction_exposed") is False
        and details.get("instruction_bundle") is None
        and events
        and all(isinstance(event, dict) for event in events)
        and str(events[0].get("event_type") or "") == "operation_created"
        and str(events[0].get("to_status") or "") == "planned"
        and dict(events[0].get("payload") or {}).get("instruction_exposed") is False
        and str(latest_event.get("checksum") or "")
        == str(operation.get("last_event_checksum") or "")
        and all(
            str(event.get("event_type") or "") != "guided_instruction_issued"
            and dict(event.get("payload") or {}).get("instruction_exposed") is not True
            for event in events
        )
    )
    non_terminal_status_matches = (
        operation_type in {"vm_start", "vm_shutdown"} and status in {"planned", "dispatching"}
    ) or (operation_type == "vm_create" and status == "approved")
    terminal_status_matches = is_pre_dispatch_terminal_no_effect(
        operation_type=operation_type,
        status=status,
        details=details,
        event_type=str(latest_event.get("event_type") or ""),
        event_payload=dict(latest_event.get("payload") or {}),
        event_to_status=str(latest_event.get("to_status") or ""),
        event_checksum=str(latest_event.get("checksum") or ""),
        operation_checksum=str(operation.get("last_event_checksum") or ""),
    )
    target_type = str(operation.get("target_type") or "")
    target_id = str(operation.get("target_id") or "")
    try:
        vmid = int(target_id.split(":", 1)[1])
        durable_vmid = int(durable.get("vmid") or 0)
    except (TypeError, ValueError, IndexError):
        return False
    durable_lock_id = str(durable.get("operation_lock_id") or "").strip()
    cluster_id = str(durable.get("cluster_id") or "").strip()
    if guided_unissued:
        target = _mapping(details.get("target"))
        try:
            target_vmid = int(target.get("vmid") or 0)
        except (TypeError, ValueError):
            return False
        return bool(
            target_type == "proxmox_vm"
            and target_id == f"vmid:{vmid}"
            and target_vmid == vmid
            and str(target.get("node_id") or "").strip()
            and not str(details.get("proxmox_upid") or "").strip()
            and not str(details.get("upid") or "").strip()
        )
    return bool(
        (non_terminal_status_matches or terminal_status_matches)
        and details.get("recovery_contract") == PRE_DISPATCH_RECOVERY_CONTRACT
        and not str(details.get("proxmox_upid") or "").strip()
        and not str(details.get("upid") or "").strip()
        and target_type == "proxmox_vm"
        and target_id == f"vmid:{vmid}"
        and isinstance(target_lock, dict)
        and target_lock.get("target_type") == target_type
        and target_lock.get("target_id") == target_id
        and target_lock.get("owner_id") == operation_id
        and str(target_lock.get("lock_id") or "") == durable_lock_id
        and durable.get("owner_id") == operation_id
        and durable.get("operation_type") == operation_type
        and durable.get("scope_type") == "proxmox_locator"
        and durable_vmid == vmid
        and durable_lock_id
        and cluster_id
        and (
            not terminal_status_matches
            or (
                str(details.get("target_lock_id") or "") == durable_lock_id
                and str(details.get("cluster_id") or "") == cluster_id
            )
        )
    )


def _guided_instruction_lock_matches(
    operation: dict[str, Any],
    target_lock: dict[str, Any] | None,
) -> bool:
    details = _mapping(operation.get("details"))
    recorded = _mapping(details.get("target_operation_lock"))
    current = _mapping(target_lock)
    recorded_durable = _mapping(recorded.get("durable"))
    current_durable = _mapping(current.get("durable"))
    operation_id = str(operation.get("operation_id") or "")
    target_type = str(operation.get("target_type") or "")
    target_id = str(operation.get("target_id") or "")
    try:
        target_vmid = int(target_id.split(":", 1)[1])
        recorded_vmid = int(recorded_durable.get("vmid") or 0)
        current_vmid = int(current_durable.get("vmid") or 0)
    except (TypeError, ValueError, IndexError):
        return False
    recorded_lock_id = str(recorded_durable.get("operation_lock_id") or "").strip()
    current_lock_id = str(current_durable.get("operation_lock_id") or "").strip()
    recorded_cluster_id = str(recorded_durable.get("cluster_id") or "").strip()
    current_cluster_id = str(current_durable.get("cluster_id") or "").strip()
    return bool(
        operation_id
        and target_type == "proxmox_vm"
        and target_id == f"vmid:{target_vmid}"
        and str(recorded.get("target_type") or "") == target_type
        and str(recorded.get("target_id") or "") == target_id
        and str(recorded.get("owner_id") or "") == operation_id
        and str(current.get("target_type") or "") == target_type
        and str(current.get("target_id") or "") == target_id
        and str(current.get("owner_id") or "") == operation_id
        and recorded_lock_id
        and recorded_lock_id == current_lock_id
        and recorded_cluster_id
        and recorded_cluster_id == current_cluster_id
        and recorded_vmid == target_vmid
        and current_vmid == target_vmid
        and str(recorded_durable.get("owner_id") or "") == operation_id
        and str(current_durable.get("owner_id") or "") == operation_id
        and str(recorded_durable.get("operation_type") or "")
        == "guided_qm_vm_unlock"
        and str(current_durable.get("operation_type") or "")
        == "guided_qm_vm_unlock"
        and str(recorded_durable.get("scope_type") or "") == "proxmox_locator"
        and str(current_durable.get("scope_type") or "") == "proxmox_locator"
        and str(recorded_durable.get("status") or "") == "active"
        and str(current_durable.get("status") or "") == "active"
    )


def _guided_instruction_state(
    operation: dict[str, Any],
    target_lock: dict[str, Any] | None,
) -> dict[str, Any]:
    status = str(operation.get("status") or "")
    raw_expires_at = operation.get("expires_at")
    expires_at: datetime | None = None
    if isinstance(raw_expires_at, str) and raw_expires_at:
        try:
            expires_at = _as_utc(datetime.fromisoformat(raw_expires_at.replace("Z", "+00:00")))
        except ValueError:
            expires_at = None
    has_valid_expiry = expires_at is not None
    unexpired = has_valid_expiry and datetime.now(timezone.utc) < expires_at
    lock_matches = _guided_instruction_lock_matches(operation, target_lock)
    active = status == "awaiting_operator" and unexpired and lock_matches
    if active:
        reason = "instruction_active"
    elif status == "planned":
        reason = "instruction_handoff_incomplete"
    elif status == "awaiting_operator":
        if not has_valid_expiry:
            reason = "instruction_expiry_invalid"
        elif not unexpired:
            reason = "instruction_ttl_elapsed"
        elif target_lock is None:
            reason = "target_lock_lost"
        else:
            reason = "target_lock_mismatch"
    elif status in {"awaiting_verification", "verifying", "succeeded"}:
        reason = "instruction_already_attested"
    elif status == "needs_reconciliation":
        reason = "instruction_requires_reconciliation"
    else:
        reason = f"instruction_{status}"
    return {
        "active": active,
        "historical": not active,
        "do_not_execute": not active,
        "reason": reason,
        "expires_at": raw_expires_at,
    }


def _create_readiness_summary(
    result: dict[str, Any],
    operation: dict[str, Any],
    recovery: Any,
) -> dict[str, Any] | None:
    observed: dict[str, Any] = {}
    artifact: dict[str, Any] = {}
    workload: dict[str, Any] = {}
    for event in reversed(list(result.get("events") or [])):
        payload = dict(event.get("payload") or {})
        candidate = payload.get("observed_after")
        candidate_artifact = payload.get("observed_after_artifact")
        candidate_workload = payload.get("workload")
        if not observed and isinstance(candidate, dict):
            observed = dict(candidate)
        if not artifact and isinstance(candidate_artifact, dict):
            artifact = dict(candidate_artifact)
        if not workload and isinstance(candidate_workload, dict):
            workload = dict(candidate_workload)
        if observed and artifact and workload:
            break
    operation_details = dict(operation.get("details") or {})
    if recovery is not None:
        recovery_details = dict(recovery.details or {})
        if not observed and isinstance(recovery_details.get("observed_after"), dict):
            observed = dict(recovery_details["observed_after"])
        if not artifact and isinstance(recovery_details.get("observed_after_artifact"), dict):
            artifact = dict(recovery_details["observed_after_artifact"])
    if not workload and isinstance(operation_details.get("workload"), dict):
        workload = dict(operation_details["workload"])
    readiness = dict(observed.get("readiness") or {})
    fingerprint = dict(observed.get("fingerprint") or {})
    fingerprint_hash = str(observed.get("fingerprint_hash") or fingerprint.get("hash") or "")
    artifact_id = str(artifact.get("artifact_id") or artifact.get("id") or "")
    artifact_checksum = str(artifact.get("checksum") or artifact.get("sha256") or "")
    workload_id = str(workload.get("vm_instance_id") or "")
    has_evidence = bool(observed or artifact_id or artifact_checksum or workload_id)
    if not has_evidence:
        return None
    return {
        "status": str(observed.get("status") or workload.get("status") or ""),
        "exists": observed.get("exists"),
        "fingerprint_hash": fingerprint_hash,
        "readiness": readiness,
        "artifact": {
            "artifact_id": artifact_id,
            "checksum": artifact_checksum,
        },
        "workload": {
            "vm_instance_id": workload_id,
            "node_id": str(workload.get("node_id") or ""),
            "vmid": workload.get("vmid"),
            "status": str(workload.get("status") or ""),
        },
        "workload_target": {
            "target_type": operation.get("target_type"),
            "target_id": operation.get("target_id"),
        },
    }


def list_operations(
    *,
    status: str | None = None,
    operation_type: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    return OperationQueryService(operations=SqlAlchemyOperationStore()).list(
        OperationListQuery(
            status=status,
            operation_type=operation_type,
            target_type=target_type,
            target_id=target_id,
            limit=limit,
        )
    )


def get_operation(operation_id: str) -> dict[str, Any]:
    result = OperationQueryService(operations=SqlAlchemyOperationStore()).get(operation_id)
    operation = result["operation"]
    recovery = SqlAlchemyRecoveryStore().get(operation_id)
    target_lock = get_target_operation_lock(
        str(operation.get("target_type") or ""),
        str(operation.get("target_id") or ""),
    )
    result["target_lock"] = target_lock
    available_actions: list[dict[str, Any]] = []
    recovery_observe_eligible = bool(
        recovery is not None
        and recovery_error_semantics(recovery.last_error_code) != "ineligible"
        and (
            recovery.status in {"paused", "retry_wait", "pending"}
            or _expired_recovery_lease(recovery)
        )
    )
    if recovery_observe_eligible:
        available_actions.append(
            {
                "action": "observe",
                "label": "다시 관찰",
                "description": "외부 mutation을 재호출하지 않고 Proxmox 상태와 로컬 증거만 다시 관찰합니다.",
                "enabled": True,
                "required_role": "operator",
            }
        )
    elif recovery is None and _safe_no_item_pre_dispatch(
        operation,
        target_lock,
        operation_id=operation_id,
        events=list(result.get("events") or []),
    ):
        available_actions.append(
            {
                "action": "observe",
                "label": "복구 상태 확인",
                "description": "dispatch 전 복구 항목 누락 여부를 확인하고 mutation 없이 안전하게 닫습니다.",
                "enabled": True,
                "required_role": "operator",
            }
        )
    if recovery is not None:
        recovery_payload = recovery_item_payload(recovery)
        details = dict(recovery_payload.get("details") or {})
        recovery_payload.update(
            {
                "reason": recovery.last_error_code,
                "phase": str(details.get("phase") or operation.get("current_stage") or ""),
                "latest_observation": (
                    details.get("latest_observation")
                    or details.get("last_observation")
                    or details.get("observed_after")
                    or details.get("task")
                    or {}
                ),
                "available_actions": available_actions,
                "incomplete": recovery.status != "completed",
                "manual_action_required": recovery.status == "paused",
            }
        )
        result["recovery"] = recovery_payload
    else:
        result["recovery"] = None
    if operation.get("operation_type") == "guided_qm_vm_unlock":
        result["instruction_bundle"] = dict(operation.get("details") or {}).get("instruction_bundle")
        result["instruction_state"] = _guided_instruction_state(operation, target_lock)
    if operation.get("operation_type") == "vm_create":
        readiness = _create_readiness_summary(result, operation, recovery)
        if readiness is not None:
            result["create_readiness"] = readiness
    result["recovery_available_actions"] = available_actions
    result["coordination_incomplete"] = bool(
        (recovery is not None and recovery.status != "completed")
        or (isinstance(target_lock, dict) and target_lock.get("owner_id") == operation_id)
    )
    return result


def observe_operation_recovery(
    operation_id: str,
    *,
    actor: dict[str, Any],
    expected_version: int,
    expected_checksum: str,
    idempotency_key: str,
) -> dict[str, Any]:
    observation = build_recovery_coordinator().observe(
        operation_id,
        actor=OperationActor.from_mapping(actor),
        expected_version=expected_version,
        expected_checksum=expected_checksum,
        idempotency_key=idempotency_key,
    )
    try:
        detail = get_operation(operation_id)
    except Exception as exc:
        raise OperationRecoveryObserveError(
            "OPERATION_RECOVERY_PERSISTENCE_UNAVAILABLE",
            "Recovery observation was recorded, but the canonical Operation handoff is unavailable",
            status_code=503,
            details={
                "operation_id": str(operation_id),
                "observation_committed": True,
                "idempotent_replay": observation.get("idempotent_replay") is True,
            },
        ) from exc
    return {**detail, "recovery_observation": observation}


__all__ = [
    "InvalidOperationQuery",
    "OperationQueryNotFound",
    "OperationRecoveryObserveError",
    "get_operation",
    "list_operations",
    "observe_operation_recovery",
]
