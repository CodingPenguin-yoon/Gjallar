"""Application orchestration for the compatibility Create VM workflow.

This module owns the draft -> preflight -> plan -> approval -> execution
sequence. HTTP concerns stay in ``app.api.v1.vm_create_compat``.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from app.auth.roles import AuthenticatedUser, actor_detail_fields, actor_evidence
from app.core.redaction import redact_secrets
from app.db.vm_runtime import (
    find_vm_create_request_for_target,
    get_vm_create_request_record,
    get_vm_instance_record,
    record_vm_create_request,
)
from app.jobs.runs import record_job_run, run_dir
from app.operations.core.domain import (
    OperationActor,
    OperationIntentConflict,
    OperationStateConflict,
)
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.recovery.domain import PRE_DISPATCH_RECOVERY_CONTRACT
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.target_lock import TargetOperationLockBusy, acquire_target_operation_lock, get_target_operation_lock, release_target_operation_lock
from app.operations.vm_create.recovery import VmCreateRecoveryError, VmCreateRecoverySession
from app.operations.vm_create.recovery_adapters import SqlAlchemyVmCreateRecoveryProjection
from app.operations.vm_create.domain import vm_create_plan_intent
from app.operations.vm_create.domain import compact_create_result
from app.operations.vm_create.facade import (
    prepare_vm_create_operation,
    record_vm_create_approval,
    record_vm_create_compatibility_replay,
    record_vm_create_dispatch_prepared,
    record_vm_create_guard_blocked,
    record_vm_create_preview,
    vm_create_operation_link,
)
from app.vm_create.approval import validate_approval_request
from app.operations.vm_create.domain import completed_workload_history
from app.vm_create.drafts import build_default_vm_draft
from app.db.create_vm_profiles import get_active_create_vm_profiles_by_id
from app.vm_create.planner import calculate_vm_create_plan
from app.vm_create.plan_persistence import persist_vm_create_plan
from app.workloads.inventory import WorkloadInventoryQuery, WorkloadInventoryUnavailableError
from app.vm_create.preflight import run_preflight
from app.vm_create.proxmox_runner import build_proxmox_create_preview, run_proxmox_create


@dataclass(frozen=True)
class VmCreateApplicationResult:
    """Transport-neutral Create VM result and its compatibility mode."""

    data: dict[str, Any]
    mode: str


class VmCreateApplicationError(RuntimeError):
    """Transport-neutral error mapped to an HTTP response by the API layer."""

    def __init__(self, status_code: int, detail: dict[str, Any]):
        super().__init__(str(detail.get("message") or detail.get("code") or "Create VM failed"))
        self.status_code = status_code
        self.detail = detail


def _details_with_actor(
    details: dict[str, Any] | None,
    actor: AuthenticatedUser | dict | None,
) -> dict[str, Any]:
    payload = dict(details or {})
    payload.update(actor_detail_fields(actor))
    return payload


def _profiles_for_payload(payload):
    payload = payload or {}
    mode = payload.get("creation_mode", "profile")
    if mode not in ("template", "profile"):
        raise VmCreateApplicationError(422, {"code": "INVALID_CREATE_MODE", "message": "Unknown creation mode", "side_effects": []})
    if mode == "template":
        if payload.get("profile_id") or payload.get("profileId"):
            raise VmCreateApplicationError(422, {"code": "AMBIGUOUS_CREATE_MODE", "message": "Template input cannot also select a profile", "side_effects": []})
        return {}
    return get_active_create_vm_profiles_by_id()


def build_draft_from_payload(
    draft_id: str,
    payload: dict | None,
    *,
    inventory_adapter: Any,
):
    payload = payload or {}
    network_payload = payload.get("network") if isinstance(payload.get("network"), dict) else {}
    access_payload = payload.get("access") if isinstance(payload.get("access"), dict) else {}
    hardware_payload = payload.get("hardware_overrides") if isinstance(payload.get("hardware_overrides"), dict) else {}
    if not hardware_payload and isinstance(payload.get("hardware"), dict):
        hardware_payload = payload.get("hardware") or {}

    def network_value(*keys: str):
        for key in keys:
            if key in payload:
                return payload.get(key)
        for key in keys:
            if key in network_payload:
                return network_payload.get(key)
        return None

    def access_value(*keys: str):
        for key in keys:
            if key in payload:
                return payload.get(key)
        for key in keys:
            if key in access_payload:
                return access_payload.get(key)
        return None

    requested_vmid = payload.get("vmid")
    if requested_vmid is not None:
        if isinstance(requested_vmid, bool) or not re.fullmatch(r"[0-9]+", str(requested_vmid)):
            raise VmCreateApplicationError(422, {"code": "INVALID_VM_ID", "message": "VMID must be an integer"})
        proposed_vmid = int(requested_vmid)
        if not 100 <= proposed_vmid <= 999999999:
            raise VmCreateApplicationError(422, {"code": "INVALID_VM_ID", "message": "VMID must be between 100 and 999999999"})
    else:
        proposed_vmid = inventory_adapter.suggest_next_vmid() if hasattr(inventory_adapter, "suggest_next_vmid") else None
    vm_name = payload.get("vm_name")
    if vm_name is not None and (not isinstance(vm_name, str) or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", vm_name)):
        raise VmCreateApplicationError(422, {"code": "INVALID_VM_NAME", "message": "VM name must be a hostname of 1 to 63 characters"})
    profiles = _profiles_for_payload(payload)
    template = None
    if payload.get("creation_mode") == "template":
        template = next((item for item in inventory_adapter.list_templates()
                         if str(item.vmid) == str(payload.get("template_vmid"))
                         and item.node_id == payload.get("template_node_id")), None)
        if template is None:
            raise VmCreateApplicationError(422, {
                "code": "CREATE_TEMPLATE_UNAVAILABLE", "message": "Select an available template node and VMID", "side_effects": [],
            })
        if payload.get("template_id") and payload["template_id"] != template.template_id:
            raise VmCreateApplicationError(422, {
                "code": "CREATE_TEMPLATE_ID_MISMATCH", "message": "Template identifiers do not match", "side_effects": [],
            })
        aliases = {"memory_mb": "memoryMb", "disk_gb": "diskGb"}
        hardware_payload = {
            key: hardware_payload.get(key, hardware_payload.get(aliases.get(key), getattr(template, key)))
            for key in ("cpu", "memory_mb", "disk_gb")
        }
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in hardware_payload.values()):
            raise VmCreateApplicationError(422, {
                "code": "INVALID_CREATE_HARDWARE", "message": "CPU, memory and disk must be positive integers", "side_effects": [],
            })
    draft = build_default_vm_draft(
        profiles=profiles,
        template=template,
        operator_id=str(payload.get("operator_id", "api-preview")),
        job_id=str(payload.get("job_id", draft_id)),
        profile_id=payload.get("profile_id") or payload.get("profileId"),
        target_node_id=payload.get("target_node_id"),
        storage_id=payload.get("storage_id"),
        bridge_id=network_value("bridge_id", "bridgeId"),
        static_ip=network_value("static_ip", "staticIp"),
        prefix=network_value("prefix"),
        gateway=network_value("gateway"),
        ip_mode=network_value("ip_mode", "ipMode"),
        proposed_vmid=proposed_vmid,
        template_id=payload.get("template_id"),
        template_vmid=payload.get("template_vmid"),
        template_node_id=payload.get("template_node_id"),
        hardware_overrides=hardware_payload,
        access_overrides={
            "cloud_init_user": access_value("cloud_init_user", "cloudInitUser", "username", "user"),
            "ssh_public_key": access_value("ssh_public_key", "sshPublicKey", "public_key", "publicKey"),
            "password_login": access_value("password_login", "passwordLogin"),
        },
        first_power_on_included=(
            payload.get("first_power_on_included")
            if "first_power_on_included" in payload
            else payload.get("firstPowerOnIncluded")
        ),
        power_policy=payload.get("power_policy") or payload.get("powerPolicy"),
    )

    return replace(draft, vm_name=vm_name) if vm_name is not None else draft


def preview_run_dir(job_id: str):
    return run_dir(job_id)


def build_preview_plan(
    draft_id: str,
    payload: dict | None,
    *,
    inventory_adapter: Any,
):
    draft = build_draft_from_payload(draft_id, payload, inventory_adapter=inventory_adapter)
    preflight = run_preflight(draft, profiles=_profiles_for_payload(payload), inventory_adapter=inventory_adapter)
    return persist_vm_create_plan(calculate_vm_create_plan(draft, preflight), run_dir=preview_run_dir(draft.job_id))


def _validate_fresh_create_state(plan, payload, inventory_adapter) -> None:
    """Recheck the approved target without overwriting its persisted evidence."""
    try:
        fresh = WorkloadInventoryQuery(inventory_adapter).require_create_adapter(fresh=True)
    except WorkloadInventoryUnavailableError as exc:
        raise VmCreateApplicationError(503, exc.to_detail()) from exc
    try:
        draft = build_draft_from_payload(plan.draft_id, payload, inventory_adapter=fresh)
    except VmCreateApplicationError as exc:
        raise VmCreateApplicationError(409, {
            "code": "PROXMOX_CREATE_STATE_CHANGED", "message": "Create conditions changed; review a new plan", "side_effects": [],
        }) from exc
    # VMID belongs to the approved plan, not a new suggestion from fresh inventory.
    draft = replace(draft, proposed_vmid=plan.vmid)
    preflight = run_preflight(
        draft, profiles=_profiles_for_payload(payload), inventory_adapter=fresh,
    )
    calculated = calculate_vm_create_plan(draft, preflight)
    approved = {**plan.to_dict(), **plan.review_confirm}
    if preflight.risk_level == "red" or any(
        approved.get(key) != value for key, value in calculated.core.items()
    ):
        raise VmCreateApplicationError(409, {
            "code": "PROXMOX_CREATE_STATE_CHANGED",
            "message": "Proxmox conditions changed; review and approve a new Create VM plan",
            "side_effects": [],
        })


def _native_error_summary(result: dict[str, Any] | None, fallback: str) -> str:
    if isinstance(result, dict):
        return compact_create_result(result)["message"]
    return "Native Proxmox create did not establish a verified result."


def _vm_create_operation_conflict(
    exc: OperationIntentConflict | OperationStateConflict,
    *,
    draft_id: str,
) -> VmCreateApplicationError:
    if isinstance(exc, OperationIntentConflict):
        code = "PROXMOX_CREATE_IDEMPOTENCY_CONFLICT"
        message = "same Create VM job_id already belongs to a different creation intent or exact plan"
        status = ""
    else:
        status = str(exc.current_status)
        if status in {"dispatching", "running", "verifying", "needs_reconciliation"}:
            code = "PROXMOX_CREATE_RECONCILIATION_REQUIRED"
        elif status == "failed":
            code = "PROXMOX_CREATE_IDEMPOTENCY_CONFLICT"
        else:
            code = "PROXMOX_CREATE_OPERATION_STATE_CONFLICT"
        message = f"Create VM operation cannot continue from status {status}"
    return VmCreateApplicationError(
        409,
        {
            "code": code,
            "message": message,
            "draft_id": draft_id,
            "operation_id": exc.operation_id,
            "operation_status": status,
            "side_effects": [],
        },
    )


def _prepare_vm_create_operation(
    plan: Any,
    *,
    actor: AuthenticatedUser | dict | None = None,
):
    try:
        return prepare_vm_create_operation(plan, actor=actor).operation
    except OperationIntentConflict as exc:
        raise _vm_create_operation_conflict(exc, draft_id=str(plan.draft_id)) from exc


def _record_vm_create_approval_or_conflict(
    plan: Any,
    decision: Any,
    *,
    actor: AuthenticatedUser | dict | None = None,
):
    try:
        return record_vm_create_approval(plan.job_id, decision.to_dict(), actor=actor)
    except OperationStateConflict as exc:
        raise _vm_create_operation_conflict(exc, draft_id=str(plan.draft_id)) from exc


def _with_vm_create_operation(payload: dict[str, Any], operation: Any) -> dict[str, Any]:
    return {
        **payload,
        "operation_id": operation.operation_id,
        "operation": vm_create_operation_link(operation),
    }


def _public_vm_create_request(record: dict[str, Any]) -> dict[str, Any]:
    keys = ("request_id", "status", "target_node_id", "vmid", "vm_name", "updated_at")
    response = {key: record[key] for key in keys if key in record}
    actor = record.get("actor") if isinstance(record.get("actor"), dict) else None
    if actor:
        response["actor"] = dict(actor)
        response["actor_user_id"] = str(actor.get("user_id") or "")
        response["actor_username"] = str(actor.get("username") or "")
        response["actor_role"] = str(actor.get("role") or "")
    return response


def _vm_instance_from_existing_result(plan: Any) -> dict[str, Any] | None:
    operation = SqlAlchemyOperationStore().get(plan.job_id)
    if operation is not None and operation.status == "succeeded":
        return completed_workload_history(operation, node_id=plan.target_node_id, vmid=plan.vmid)
    # Only legacy compatibility adoption still needs exact current linkage.
    return get_vm_instance_record(plan.target_node_id, plan.vmid, create_job_id=plan.job_id)


def _raise_vm_create_idempotency_block(
    *,
    draft_id: str,
    existing: dict[str, Any],
    code: str,
    message: str,
    preview: dict[str, Any],
) -> None:
    result = existing.get("result") if isinstance(existing.get("result"), dict) else {}
    raise VmCreateApplicationError(
        409,
        {
            "code": code,
            "message": message,
            "draft_id": draft_id,
            "request_id": existing.get("request_id", ""),
            "existing_status": existing.get("status", ""),
            "side_effects": list(result.get("side_effects") or []),
            "proxmox_create": result,
            "proxmox_preview": preview,
            "idempotency": {
                "replayed": False,
                "request_id": existing.get("request_id", ""),
                "reason": code,
            },
        },
    )


def _raise_vm_create_target_block(
    *,
    draft_id: str,
    plan: Any,
    existing: dict[str, Any],
    code: str,
    message: str,
    preview: dict[str, Any],
) -> None:
    result = existing.get("result") if isinstance(existing.get("result"), dict) else {}
    target_id = f"vmid:{int(plan.vmid)}"
    raise VmCreateApplicationError(
        409,
        {
            "code": code,
            "message": message,
            "draft_id": draft_id,
            "request_id": existing.get("request_id", ""),
            "requested_request_id": plan.job_id,
            "existing_status": existing.get("status", ""),
            "target_type": "proxmox_vm",
            "target_id": target_id,
            "side_effects": [],
            "historical_side_effects": list(result.get("side_effects") or []),
            "proxmox_create": result,
            "proxmox_preview": preview,
            "idempotency": {
                "replayed": False,
                "request_id": existing.get("request_id", ""),
                "requested_request_id": plan.job_id,
                "reason": code,
            },
        },
    )


def _idempotent_create_replay_result(
    *,
    plan: Any,
    decision: Any,
    preview: dict[str, Any],
    existing: dict[str, Any],
) -> VmCreateApplicationResult:
    result = dict(existing.get("result") or {})
    historical_side_effects = list(result.get("side_effects") or [])
    return VmCreateApplicationResult(
        data={
            **result,
            "approval": dict(existing.get("approval") or decision.to_dict()),
            "proxmox_preview": preview,
            "proxmox_create_ran": False,
            "proxmox_mutation_ran_previously": True,
            "proxmox_create_status": str(result.get("status") or "completed"),
            "vm_create_request": _public_vm_create_request(existing),
            "vm_instance": _vm_instance_from_existing_result(plan),
            "proxmox_create_enabled": True,
            "proxmox_mutation_enabled": False,
            "side_effects": [],
            "historical_side_effects": historical_side_effects,
            "idempotent_replay": True,
            "idempotency": {
                "replayed": True,
                "request_id": existing.get("request_id", ""),
                "status": existing.get("status", ""),
                "historical_side_effects": historical_side_effects,
            },
        },
        mode="proxmox_native_create_live_mutation",
    )


def _existing_vm_create_result_if_blocked(
    *,
    draft_id: str,
    plan: Any,
    decision: Any,
    preview: dict[str, Any],
) -> VmCreateApplicationResult | None:
    existing = get_vm_create_request_record(plan.job_id)
    if existing is not None:
        if existing.get("plan_intent") != vm_create_plan_intent(plan):
            _raise_vm_create_idempotency_block(
                draft_id=draft_id,
                existing=existing,
                code="PROXMOX_CREATE_IDEMPOTENCY_CONFLICT",
                message="same Create VM job_id already exists with a different creation intent",
                preview=preview,
            )

        status = str(existing.get("status") or "").strip()
        result = existing.get("result") if isinstance(existing.get("result"), dict) else {}
        persisted_operation = SqlAlchemyOperationStore().get(plan.job_id)
        if persisted_operation is not None and persisted_operation.status in {
            "dispatching",
            "running",
            "verifying",
            "needs_reconciliation",
        }:
            requires_reconciliation = persisted_operation.status == "needs_reconciliation"
            _raise_vm_create_idempotency_block(
                draft_id=draft_id,
                existing=existing,
                code=(
                    "PROXMOX_CREATE_RECONCILIATION_REQUIRED"
                    if requires_reconciliation
                    else "PROXMOX_CREATE_TARGET_IN_PROGRESS"
                ),
                message=(
                    "existing Create VM execution requires reconciliation before retry"
                    if requires_reconciliation
                    else "existing Create VM execution is awaiting local recovery completion"
                ),
                preview=preview,
            )
        if status == "completed" and result.get("success") is True and result.get("observed_after_artifact"):
            return _idempotent_create_replay_result(
                plan=plan,
                decision=decision,
                preview=preview,
                existing=existing,
            )

        if status == "running":
            _raise_vm_create_idempotency_block(
                draft_id=draft_id,
                existing=existing,
                code="PROXMOX_CREATE_TARGET_IN_PROGRESS",
                message="existing Create VM request is still running",
                preview=preview,
            )

        if status in {"needs_reconciliation", "apply_failed"}:
            _raise_vm_create_idempotency_block(
                draft_id=draft_id,
                existing=existing,
                code="PROXMOX_CREATE_RECONCILIATION_REQUIRED",
                message="existing Create VM result requires reconciliation before retry",
                preview=preview,
            )

        if status:
            _raise_vm_create_idempotency_block(
                draft_id=draft_id,
                existing=existing,
                code="PROXMOX_CREATE_IDEMPOTENCY_CONFLICT",
                message=f"same Create VM job_id already exists with status {status}",
                preview=preview,
            )

    existing_target = find_vm_create_request_for_target(
        vmid=plan.vmid,
        exclude_request_id=plan.job_id,
    )
    if existing_target is None:
        return None

    target_status = str(existing_target.get("status") or "").strip()
    target_operation = SqlAlchemyOperationStore().get(
        str(existing_target.get("request_id") or "")
    )
    if (
        target_status == "running"
        and target_operation is not None
        and target_operation.status == "needs_reconciliation"
    ):
        _raise_vm_create_target_block(
            draft_id=draft_id,
            plan=plan,
            existing=existing_target,
            code="PROXMOX_CREATE_RECONCILIATION_REQUIRED",
            message="another Create VM request for this target requires reconciliation before reuse",
            preview=preview,
        )
    if target_status == "running":
        _raise_vm_create_target_block(
            draft_id=draft_id,
            plan=plan,
            existing=existing_target,
            code="PROXMOX_CREATE_TARGET_IN_PROGRESS",
            message="another Create VM request is already running for this Proxmox VM target",
            preview=preview,
        )
    if target_status in {"needs_reconciliation", "apply_failed"}:
        _raise_vm_create_target_block(
            draft_id=draft_id,
            plan=plan,
            existing=existing_target,
            code="PROXMOX_CREATE_RECONCILIATION_REQUIRED",
            message="another Create VM request for this target requires reconciliation before reuse",
            preview=preview,
        )

    return None


def _target_lock_busy_detail(
    exc: TargetOperationLockBusy,
    *,
    target_id: str,
    owner_id: str,
) -> dict[str, Any]:
    if hasattr(exc, "to_dict"):
        lock = exc.to_dict()
    else:
        lock = getattr(exc, "evidence", {})
    if not isinstance(lock, dict):
        lock = {}
    target_type = str(lock.get("target_type") or "proxmox_vm")
    return {
        "code": "PROXMOX_CREATE_TARGET_IN_PROGRESS",
        "message": "another operation is already running for this Proxmox VM target",
        "target_type": target_type,
        "target_id": str(lock.get("target_id") or target_id),
        "owner_id": str(lock.get("owner_id") or lock.get("requested_owner_id") or owner_id),
        "lock": lock,
        "side_effects": [],
    }


def _recover_owned_pre_dispatch_lock_if_safe(
    *,
    operation: Any,
    plan: Any,
    decision: Any,
    preview: dict[str, Any],
    actor: AuthenticatedUser | dict | None,
    actor_payload: dict[str, Any],
) -> Any | None:
    """Adopt only the provable no-item/no-request post-acquire crash window."""

    if operation.status != "approved":
        return None
    if (
        not isinstance(operation.details, Mapping)
        or operation.details.get("recovery_contract") != PRE_DISPATCH_RECOVERY_CONTRACT
    ):
        return None
    if get_vm_create_request_record(plan.job_id) is not None:
        return None
    recovery_store = SqlAlchemyRecoveryStore()
    if recovery_store.get(plan.job_id) is not None:
        return None
    target_id = f"vmid:{int(plan.vmid)}"
    target_lock = get_target_operation_lock("proxmox_vm", target_id)
    if not isinstance(target_lock, dict) or str(target_lock.get("owner_id") or "") != plan.job_id:
        return None
    durable = target_lock.get("durable") if isinstance(target_lock.get("durable"), dict) else {}
    if str(durable.get("operation_type") or "") != "vm_create":
        return None

    session = VmCreateRecoverySession.prepare(
        recovery=recovery_store,
        operations=SqlAlchemyOperationStore(),
        operation=operation,
        plan=plan,
        preview=preview,
        target_lock=target_lock,
        actor=OperationActor.from_mapping(actor_payload),
        lease_owner=f"foreground:vm-create-orphan:{plan.job_id}",
        lease_seconds=60,
    )
    return session.complete_pre_dispatch_failure(
        code="PROXMOX_CREATE_ORPHANED_PRE_DISPATCH_LOCK",
        message="Recovered an owned target lock with no request, recovery item, or dispatched mutation",
        record_compatibility_failure=lambda: _record_pre_dispatch_failure_projections(
            plan,
            decision=decision,
            preview=preview,
            target_lock=target_lock,
            code="PROXMOX_CREATE_ORPHANED_PRE_DISPATCH_LOCK",
            message="Recovered an owned target lock before any Proxmox mutation",
            actor=actor,
            actor_payload=actor_payload,
        ),

    )


def _is_clear_clone_rejection(create_result: dict[str, Any]) -> bool:
    side_effects = {str(item) for item in list(create_result.get("side_effects") or [])}
    mutation_markers = {
        "proxmox_clone_invoked",
        "proxmox_task_polled",
        "proxmox_task_poll_state_unknown",
        "proxmox_disk_resize_invoked",
        "proxmox_disk_resize_succeeded",
        "proxmox_config_updated",
        "proxmox_start_invoked",
        "proxmox_post_check_observed",
    }
    return (
        create_result.get("success") is not True
        and str(create_result.get("status") or "") == "failed"
        and "proxmox_clone_rejected" in side_effects
        and side_effects.isdisjoint(mutation_markers)
    )


def _risk_dicts_from_plan(plan: Any) -> list[dict[str, Any]]:
    risk_summary = plan.risk_summary or {}
    return [
        *list(risk_summary.get("red") or []),
        *list(risk_summary.get("yellow") or []),
    ]


def _target_label(*, node_id: str, vm_name: str) -> str:
    return f"{node_id}:{vm_name}" if vm_name else node_id


def _record_draft_job(
    draft: Any,
    *,
    status: str,
    stage: str,
    step_status: str,
    message: str,
    actor: AuthenticatedUser | dict | None = None,
) -> dict[str, Any]:
    return record_job_run(
        job_id=draft.job_id,
        job_type="vm_create",
        status=status,
        target_id=_target_label(node_id=draft.target_node_id, vm_name=draft.vm_name),
        risk_level="unknown",
        stage=stage,
        step_status=step_status,
        message=message,
        details=_details_with_actor(draft.to_dict(), actor),
    )


def _record_preflight_job(
    draft: Any,
    preflight: Any,
    *,
    status: str,
    step_status: str,
    message: str,
    actor: AuthenticatedUser | dict | None = None,
) -> dict[str, Any]:
    return record_job_run(
        job_id=draft.job_id,
        job_type="vm_create",
        status=status,
        target_id=_target_label(node_id=draft.target_node_id, vm_name=draft.vm_name),
        risk_level=preflight.risk_level,
        stage="preflight",
        step_status=step_status,
        message=message,
        risks=preflight.risks,
        details=_details_with_actor(
            {
                "draft": draft.to_dict(),
                "preflight": preflight.to_dict(),
            },
            actor,
        ),
    )


def _record_plan_job(
    plan: Any,
    *,
    status: str,
    stage: str,
    step_status: str,
    message: str,
    artifacts: list[Any] | None = None,
    details: dict[str, Any] | None = None,
    actor: AuthenticatedUser | dict | None = None,
) -> dict[str, Any]:
    return record_job_run(
        job_id=plan.job_id,
        job_type="vm_create",
        status=status,
        target_id=_target_label(node_id=plan.target_node_id, vm_name=plan.vm_name),
        risk_level=plan.risk_summary.get("level", "unknown"),
        stage=stage,
        step_status=step_status,
        message=message,
        artifacts=artifacts if artifacts is not None else plan.artifacts,
        risks=_risk_dicts_from_plan(plan),
        details=_details_with_actor(
            {
                "draft_id": plan.draft_id,
                "manifest_id": plan.manifest_id,
                "profile_id": plan.profile_id,
                "vm_name": plan.vm_name,
                "vmid": plan.vmid,
                "target_node_id": plan.target_node_id,
                "storage_id": plan.storage_id,
                "template_id": plan.template_id,
                "hardware": plan.hardware,
                "access": plan.access,
                "selected_template": plan.selected_template,
                "selected_bridge": plan.selected_bridge,
                "network": plan.network,
                "first_power_on_included": plan.first_power_on_included,
                "power_policy": plan.power_policy,
                **(details or {}),
            },
            actor,
        ),
    )


def _artifacts_from_result(result: dict[str, Any]) -> list[Any]:
    return [artifact for artifact in result.get("artifacts") or [] if isinstance(artifact, dict)]


def _record_pre_dispatch_failure_projections(
    plan: Any,
    *,
    decision: Any,
    preview: dict[str, Any],
    target_lock: dict[str, Any],
    code: str,
    message: str,
    error_type: str = "",
    actor: AuthenticatedUser | dict | None,
    actor_payload: dict[str, Any],
) -> None:
    result = {
        "success": False,
        "status": "failed",
        "message": str(message)[:1000],
        "code": str(code),
        "error_type": str(error_type)[:200],
        "external_effect": False,
        "side_effects": [],
        "target_lock": target_lock,
    }
    record_vm_create_request(
        plan,
        status="failed",
        approval=decision.to_dict(),
        result=result,
        actor=actor_payload,
    )
    _record_plan_job(
        plan,
        status="failed",
        stage="create",
        step_status="failed",
        message="Proxmox mutation 전에 Create VM 로컬 준비가 종료되었습니다.",
        artifacts=[*plan.artifacts, *_artifacts_from_result(preview)],
        details=_details_with_actor(
            {
                "approval": decision.to_dict(),
                "proxmox_preview": preview,
                "target_lock": target_lock,
                "failure": result,
            },
            actor,
        ),
        actor=actor_payload,
    )


async def create_draft(
    payload: dict | None,
    *,
    actor: AuthenticatedUser | dict | None,
    inventory_adapter: Any,
) -> VmCreateApplicationResult:
    draft = build_draft_from_payload(
        "job-api-preview",
        payload or {},
        inventory_adapter=inventory_adapter,
    )
    _record_draft_job(
        draft,
        status="in_progress",
        stage="draft",
        step_status="completed",
        message="VM 생성 요청 입력이 준비되었습니다.",
        actor=actor,
    )
    return VmCreateApplicationResult(draft.to_dict(), "dry_run_draft_only")


async def preflight_draft(
    draft_id: str,
    payload: dict | None,
    *,
    actor: AuthenticatedUser | dict | None,
    inventory_adapter: Any,
) -> VmCreateApplicationResult:
    draft = build_draft_from_payload(draft_id, payload, inventory_adapter=inventory_adapter)
    result = await asyncio.to_thread(
        run_preflight, draft, profiles=_profiles_for_payload(payload), inventory_adapter=inventory_adapter,
    )
    _record_preflight_job(
        draft,
        result,
        status="blocked" if result.risk_level == "red" else "in_progress",
        step_status="blocked" if result.risk_level == "red" else "completed",
        message=(
            "사전 검토가 완료되었습니다."
            if result.risk_level != "red"
            else "사전 검토에서 차단 항목이 발견되었습니다."
        ),
        actor=actor,
    )
    return VmCreateApplicationResult(result.to_dict(), "read_only_preflight")


async def plan_draft(
    draft_id: str,
    payload: dict | None,
    *,
    actor: AuthenticatedUser | dict | None,
    inventory_adapter: Any,
) -> VmCreateApplicationResult:
    draft = build_draft_from_payload(draft_id, payload, inventory_adapter=inventory_adapter)
    preflight = await asyncio.to_thread(
        run_preflight, draft, profiles=_profiles_for_payload(payload), inventory_adapter=inventory_adapter,
    )
    plan = persist_vm_create_plan(calculate_vm_create_plan(draft, preflight), run_dir=preview_run_dir(draft.job_id))
    operation = _prepare_vm_create_operation(plan, actor=actor)
    _record_plan_job(
        plan,
        status="blocked" if plan.risk_summary.get("level") == "red" else "in_progress",
        stage="plan",
        step_status="blocked" if plan.risk_summary.get("level") == "red" else "completed",
        message="생성 계획과 검토 패킷이 준비되었습니다.",
        actor=actor,
    )
    return VmCreateApplicationResult(
        _with_vm_create_operation({**plan.to_dict(), "preflight": preflight.to_dict()}, operation),
        "dry_run_plan_only",
    )


async def approve_draft(
    draft_id: str,
    payload: dict | None,
    *,
    actor: AuthenticatedUser | dict | None,
    inventory_adapter: Any,
) -> VmCreateApplicationResult:
    payload = payload or {}
    plan = await asyncio.to_thread(build_preview_plan, draft_id, payload, inventory_adapter=inventory_adapter)
    decision = validate_approval_request(
        plan,
        plan_artifact_id=str(payload.get("plan_artifact_id", "")),
        review_summary_checksum=str(payload.get("review_summary_checksum", "")),
        yellow_risk_acknowledged=payload.get("yellow_risk_acknowledged") is True,
        run_dir=preview_run_dir(plan.job_id),
    )
    _prepare_vm_create_operation(plan, actor=actor)
    operation = _record_vm_create_approval_or_conflict(plan, decision, actor=actor)
    _record_plan_job(
        plan,
        status="in_progress" if decision.can_execute else "blocked",
        stage="approval",
        step_status="completed" if decision.can_execute else "blocked",
        message=(
            "승인이 확인되었습니다."
            if decision.can_execute
            else f"승인이 차단되었습니다: {decision.reason}"
        ),
        details={"approval": decision.to_dict()},
        actor=actor,
    )
    return VmCreateApplicationResult(
        _with_vm_create_operation(decision.to_dict(), operation),
        "approval_validation_only",
    )


async def preview_proxmox_create(
    draft_id: str,
    payload: dict | None,
    *,
    actor: AuthenticatedUser | dict | None,
    inventory_adapter: Any,
) -> VmCreateApplicationResult:
    payload = payload or {}
    plan = await asyncio.to_thread(build_preview_plan, draft_id, payload, inventory_adapter=inventory_adapter)
    decision = validate_approval_request(
        plan,
        plan_artifact_id=str(payload.get("plan_artifact_id", "")),
        review_summary_checksum=str(payload.get("review_summary_checksum", "")),
        yellow_risk_acknowledged=payload.get("yellow_risk_acknowledged") is True,
        run_dir=preview_run_dir(plan.job_id),
    )
    _prepare_vm_create_operation(plan, actor=actor)
    operation = _record_vm_create_approval_or_conflict(plan, decision, actor=actor)
    if not decision.can_execute:
        _record_plan_job(
            plan,
            status="blocked",
            stage="approval",
            step_status="blocked",
            message=f"Proxmox native 생성 미리보기가 차단되었습니다: {decision.reason}",
            details={"approval": decision.to_dict()},
            actor=actor,
        )
        raise VmCreateApplicationError(
            409,
            {
                "code": "PROXMOX_PREVIEW_APPROVAL_GATE_BLOCKED",
                "message": decision.reason,
                "draft_id": draft_id,
                "side_effects": [],
            },
        )

    preview = build_proxmox_create_preview(plan, run_dir=preview_run_dir(plan.job_id))
    try:
        operation = record_vm_create_preview(plan.job_id, preview, actor=actor)
    except OperationStateConflict as exc:
        raise _vm_create_operation_conflict(exc, draft_id=draft_id) from exc
    _record_plan_job(
        plan,
        status="in_progress",
        stage="plan",
        step_status="completed",
        message="Proxmox native 생성 미리보기가 준비되었습니다.",
        artifacts=[*plan.artifacts, *_artifacts_from_result(preview)],
        details={"approval": decision.to_dict(), "proxmox_preview": preview},
        actor=actor,
    )
    return VmCreateApplicationResult(
        _with_vm_create_operation(
            {
                **preview,
                "approval": decision.to_dict(),
                "proxmox_create_enabled": False,
                "proxmox_mutation_enabled": False,
            },
            operation,
        ),
        "proxmox_native_preview_no_mutation",
    )


async def execute_proxmox_create(
    draft_id: str,
    payload: dict | None,
    *,
    actor: AuthenticatedUser | dict | None,
    inventory_adapter: Any,
    mutation_client_factory: Callable[[], Any],
) -> VmCreateApplicationResult:
    payload = payload or {}
    actor_payload = actor_evidence(actor) if actor is not None else {}
    plan = await asyncio.to_thread(build_preview_plan, draft_id, payload, inventory_adapter=inventory_adapter)
    decision = validate_approval_request(
        plan,
        plan_artifact_id=str(payload.get("plan_artifact_id", "")),
        review_summary_checksum=str(payload.get("review_summary_checksum", "")),
        yellow_risk_acknowledged=payload.get("yellow_risk_acknowledged") is True,
        run_dir=preview_run_dir(plan.job_id),
    )
    _prepare_vm_create_operation(plan, actor=actor)
    operation = _record_vm_create_approval_or_conflict(plan, decision, actor=actor)
    if not decision.can_execute:
        raise VmCreateApplicationError(
            409,
            {
                "code": "PROXMOX_CREATE_APPROVAL_GATE_BLOCKED",
                "message": decision.reason,
                "draft_id": draft_id,
                "operation_id": operation.operation_id,
                "side_effects": [],
            },
        )
    if payload.get("proxmox_mutation_acknowledged") is not True:
        raise VmCreateApplicationError(
            409,
            {
                "code": "PROXMOX_CREATE_ACK_REQUIRED",
                "message": "proxmox_mutation_acknowledged=true is required before native Proxmox create",
                "draft_id": draft_id,
                "operation_id": operation.operation_id,
                "side_effects": [],
            },
        )
    if plan.risk_summary.get("level") == "red":
        _record_plan_job(
            plan,
            status="blocked",
            stage="preflight",
            step_status="blocked",
            message="생성 직전 사전 검토에서 차단 항목이 발견되었습니다.",
            details=_details_with_actor(None, actor_payload),
        )
        raise VmCreateApplicationError(
            409,
            {
                "code": "PROXMOX_CREATE_PREFLIGHT_RED_RISK",
                "message": "red risk blocks native Proxmox create",
                "draft_id": draft_id,
                "operation_id": operation.operation_id,
                "side_effects": [],
            },
        )

    preview = build_proxmox_create_preview(plan, run_dir=preview_run_dir(plan.job_id))
    try:
        existing_result = _existing_vm_create_result_if_blocked(
            draft_id=draft_id,
            plan=plan,
            decision=decision,
            preview=preview,
        )
    except VmCreateApplicationError as exc:
        record_vm_create_guard_blocked(plan.job_id, exc.detail, actor=actor)
        raise
    if existing_result is not None:
        existing_data = dict(existing_result.data)
        stored_workload = existing_data.get("vm_instance")
        if stored_workload is None:
            operation = record_vm_create_guard_blocked(
                plan.job_id,
                {
                    "code": "PROXMOX_CREATE_WORKLOAD_LINKAGE_MISSING",
                    "message": "completed Create VM evidence exists without persisted workload linkage",
                    "existing_status": "completed",
                    "request_id": plan.job_id,
                },
                actor=actor,
            )
            raise VmCreateApplicationError(
                409,
                {
                    "code": "PROXMOX_CREATE_RECONCILIATION_REQUIRED",
                    "message": "completed Create VM evidence is missing its persisted workload projection",
                    "draft_id": draft_id,
                    "operation_id": operation.operation_id,
                    "operation_status": operation.status,
                    "request_id": plan.job_id,
                    "side_effects": [],
                },
            )
        else:
            try:
                operation = record_vm_create_compatibility_replay(
                    plan.job_id,
                    result=existing_data,
                    request=dict(existing_data.get("vm_create_request") or {}),
                    workload=stored_workload,
                    actor=actor,
                )
            except OperationStateConflict as exc:
                raise _vm_create_operation_conflict(exc, draft_id=draft_id) from exc
        return VmCreateApplicationResult(
            _with_vm_create_operation(existing_data, operation),
            existing_result.mode,
        )

    target_id = f"vmid:{int(plan.vmid)}"
    owner_id = plan.job_id
    try:
        target_lock = acquire_target_operation_lock(
            target_type="proxmox_vm",
            target_id=target_id,
            owner_id=owner_id,
            operation_type="vm_create",
        )
    except TargetOperationLockBusy as exc:
        try:
            recovered_operation = _recover_owned_pre_dispatch_lock_if_safe(
                operation=operation,
                plan=plan,
                decision=decision,
                preview=preview,
                actor=actor,
                actor_payload=actor_payload,
            )
        except Exception as recovery_exc:
            raise VmCreateApplicationError(
                503,
                {
                    "code": "PROXMOX_CREATE_ORPHAN_RECOVERY_FAILED",
                    "message": "An owned pre-dispatch Create VM lock was found but could not be safely closed",
                    "draft_id": draft_id,
                    "operation_id": operation.operation_id,
                    "operation_status": operation.status,
                    "side_effects": [],
                },
            ) from recovery_exc
        if recovered_operation is not None:
            raise VmCreateApplicationError(
                503,
                {
                    "code": "PROXMOX_CREATE_ORPHANED_PRE_DISPATCH_LOCK_RECOVERED",
                    "message": "A previous no-effect Create VM lock was closed; submit a newly planned operation to execute",
                    "draft_id": draft_id,
                    "operation_id": recovered_operation.operation_id,
                    "operation_status": recovered_operation.status,
                    "side_effects": [],
                },
            ) from exc
        detail = _target_lock_busy_detail(exc, target_id=target_id, owner_id=owner_id)
        record_vm_create_guard_blocked(plan.job_id, detail, actor=actor)
        raise VmCreateApplicationError(
            409,
            {**detail, "operation_id": plan.job_id},
        ) from exc

    recovery_session: VmCreateRecoverySession | None = None
    try:
        target_lock_evidence = (
            target_lock.to_dict()
            if hasattr(target_lock, "to_dict")
            else {"handle": str(target_lock)}
        )
        try:
            recovery_session = VmCreateRecoverySession.prepare(
                recovery=SqlAlchemyRecoveryStore(),
                operations=SqlAlchemyOperationStore(),
                operation=operation,
                plan=plan,
                preview=preview,
                target_lock=target_lock_evidence,
                actor=OperationActor.from_mapping(actor_payload),
                lease_owner=f"foreground:vm-create:{plan.job_id}",
                lease_seconds=60,
            )
        except Exception as exc:
            code = (
                exc.code
                if isinstance(exc, VmCreateRecoveryError)
                else "PROXMOX_CREATE_RECOVERY_UNAVAILABLE"
            )
            raise VmCreateApplicationError(
                503,
                {
                    "code": code,
                    "message": "Create VM durable recovery could not be prepared; no Proxmox mutation was dispatched",
                    "draft_id": draft_id,
                    "operation_id": operation.operation_id,
                    "operation_status": operation.status,
                    "side_effects": [],
                },
            ) from exc



        try:
            record_vm_create_request(
                plan,
                status="running",
                approval=decision.to_dict(),
                result={"proxmox_preview": preview, "target_lock": target_lock_evidence},
                actor=actor_payload,
            )

            _record_plan_job(
                plan,
                status="running",
                stage="create",
                step_status="running",
                message="Proxmox native VM 생성 작업을 시작했습니다.",
                artifacts=[*plan.artifacts, *_artifacts_from_result(preview)],
                details=_details_with_actor(
                    {
                        "approval": decision.to_dict(),
                        "proxmox_preview": preview,
                        "target_lock": target_lock_evidence,
                    },
                    actor_payload,
                ),
            )

            operation = record_vm_create_dispatch_prepared(
                plan.job_id,
                preview=preview,
                target_lock=target_lock_evidence,
                actor=actor,
            )
            recovery_session.bind_operation(operation)
            recovery_session.checkpoint(
                "dispatch_prepared",
                {
                    "clone_endpoint": str(dict(preview.get("clone") or {}).get("endpoint") or ""),
                    "mutation_dispatched": False,
                },
                event_type="vm_create_recovery_armed",
            )
            recovery_session.heartbeat()
            await asyncio.to_thread(_validate_fresh_create_state, plan, payload, inventory_adapter)
            recovery_session.heartbeat()
            client = mutation_client_factory()
        except Exception as exc:
            code = (
                exc.detail.get("code", "PROXMOX_CREATE_PRE_DISPATCH_FAILED")
                if isinstance(exc, VmCreateApplicationError)
                else "PROXMOX_CREATE_PRE_DISPATCH_FAILED"
            )
            failure_message = (
                exc.detail.get("message", "Create VM pre-dispatch validation failed")
                if isinstance(exc, VmCreateApplicationError)
                else "Create VM local coordination failed before mutation dispatch"
            )
            error_type = type(exc).__name__
            try:
                operation = recovery_session.complete_pre_dispatch_failure(
                    code=str(code),
                    message=failure_message,
                    error_type=error_type,
                    record_compatibility_failure=lambda: _record_pre_dispatch_failure_projections(
                        plan,
                        decision=decision,
                        preview=preview,
                        target_lock=target_lock_evidence,
                        code=str(code),
                        message=failure_message,
                        error_type=error_type,
                        actor=actor,
                        actor_payload=actor_payload,
                    ),

                )
            except Exception as recovery_exc:
                raise VmCreateApplicationError(
                    503,
                    {
                        "code": "PROXMOX_CREATE_RECOVERY_PERSISTENCE_FAILED",
                        "message": "Create VM pre-dispatch failure could not be durably closed",
                        "draft_id": draft_id,
                        "operation_id": operation.operation_id,
                        "operation_status": operation.status,
                        "side_effects": [],
                    },
                ) from recovery_exc
            raise VmCreateApplicationError(
                exc.status_code if isinstance(exc, VmCreateApplicationError) else 503,
                {
                    "code": code,
                    "message": failure_message,
                    "draft_id": draft_id,
                    "operation_id": operation.operation_id,
                    "operation_status": operation.status,
                    "side_effects": [],
                },
            ) from exc

        try:
            create_result = redact_secrets(
                await asyncio.to_thread(
                    run_proxmox_create,
                    plan,
                    run_dir=preview_run_dir(plan.job_id),
                    client=client,
                    checkpoint=recovery_session.checkpoint,
                    heartbeat=recovery_session.heartbeat,
                )
            )
        except Exception as exc:
            if recovery_session.phase == "dispatch_prepared":
                failure_message = "Create VM execution stopped before clone mutation dispatch"
                error_type = type(exc).__name__
                try:
                    operation = recovery_session.complete_pre_dispatch_failure(
                        code="PROXMOX_CREATE_MUTATION_NOT_DISPATCHED",
                        message=failure_message,
                        error_type=error_type,
                        record_compatibility_failure=lambda: _record_pre_dispatch_failure_projections(
                            plan,
                            decision=decision,
                            preview=preview,
                            target_lock=target_lock_evidence,
                            code="PROXMOX_CREATE_MUTATION_NOT_DISPATCHED",
                            message=failure_message,
                            error_type=error_type,
                            actor=actor,
                            actor_payload=actor_payload,
                        ),

                    )
                except Exception as recovery_exc:
                    raise VmCreateApplicationError(
                        503,
                        {
                            "code": "PROXMOX_CREATE_RECOVERY_PERSISTENCE_FAILED",
                            "message": "Create VM execution preparation failed and could not be durably closed",
                            "draft_id": draft_id,
                            "operation_id": operation.operation_id,
                            "operation_status": operation.status,
                            "side_effects": [],
                        },
                    ) from recovery_exc
                raise VmCreateApplicationError(
                    503,
                    {
                        "code": "PROXMOX_CREATE_MUTATION_NOT_DISPATCHED",
                        "message": "Create VM stopped before the clone mutation was dispatched",
                        "draft_id": draft_id,
                        "operation_id": operation.operation_id,
                        "operation_status": operation.status,
                        "side_effects": [],
                    },
                ) from exc

            try:
                operation = recovery_session.pause_for_reconciliation(
                    code="PROXMOX_CREATE_EXECUTION_INTERRUPTED",
                    message="Create VM execution was interrupted after a possible external effect",
                    evidence={
                        "last_durable_phase": recovery_session.phase,
                        "error_type": type(exc).__name__,
                    },
                )
            except Exception as recovery_exc:
                raise VmCreateApplicationError(
                    503,
                    {
                        "code": "PROXMOX_CREATE_RECOVERY_PERSISTENCE_FAILED",
                        "message": "Create VM may have changed Proxmox, but reconciliation evidence could not be persisted",
                        "draft_id": draft_id,
                        "operation_id": operation.operation_id,
                        "operation_status": operation.status,
                        "side_effects": [],
                    },
                ) from recovery_exc
            raise VmCreateApplicationError(
                503,
                {
                    "code": "PROXMOX_CREATE_EXECUTION_INTERRUPTED",
                    "message": "Create VM execution stopped after a possible external effect; mutation will not be retried automatically",
                    "draft_id": draft_id,
                    "operation_id": operation.operation_id,
                    "operation_status": operation.status,
                    "side_effects": [],
                    "last_durable_phase": recovery_session.phase,
                },
            ) from exc

        if create_result.get("success") is not True or not create_result.get("observed_after_artifact"):
            side_effect_free_failure = _is_clear_clone_rejection(create_result)
            if create_result.get("status") == "needs_reconciliation":
                phase = "needs_reconciliation"
            elif side_effect_free_failure:
                phase = "failed"
            else:
                phase = "apply_failed"
            if side_effect_free_failure:
                try:
                    record_vm_create_request(
                        plan,
                        status=phase,
                        approval=decision.to_dict(),
                        result=create_result,
                        actor=actor_payload,
                    )
                    _record_plan_job(
                        plan,
                        status="failed",
                        stage="create",
                        step_status=phase,
                        message=(
                            "Proxmox native VM 생성 확인이 실패했습니다: "
                            f"{_native_error_summary(create_result, '')}"
                        ),
                        artifacts=[
                            *plan.artifacts,
                            *_artifacts_from_result(preview),
                            *_artifacts_from_result(create_result),
                        ],
                        details=_details_with_actor(
                            {
                                "proxmox_preview": preview,
                                "proxmox_create": create_result,
                                "target_lock": target_lock_evidence,
                            },
                            actor_payload,
                        ),
                    )
                    operation = recovery_session.complete_clear_failure(
                        result=create_result,

                    )
                except Exception as exc:
                    if recovery_session.lease.item.status == "leased":
                        try:
                            operation = recovery_session.checkpoint(
                                "clone_rejection_completion_pending",
                                {
                                    "result_status": phase,
                                    "external_effect": False,
                                    "error_type": type(exc).__name__,
                                },
                                stage="reconciliation",
                                event_type="vm_create_clear_rejection_completion_deferred",
                                recovery_status="retry_wait",
                                error_code="PROXMOX_CREATE_RECOVERY_PROJECTION_FAILED",
                                recovery_details_patch={"clear_rejection": True},
                            )
                        except Exception:
                            pass
                    raise VmCreateApplicationError(
                        503,
                        {
                            "code": "PROXMOX_CREATE_PROJECTION_FAILED",
                            "message": "Create VM rejection was observed, but its local evidence could not be closed",
                            "draft_id": draft_id,
                            "operation_id": operation.operation_id,
                            "operation_status": operation.status,
                            "side_effects": list(create_result.get("side_effects") or []),
                        },
                    ) from exc
            else:
                try:
                    operation = recovery_session.pause_for_reconciliation(
                        code="PROXMOX_CREATE_NEEDS_RECONCILIATION",
                        message=_native_error_summary(create_result, "native Proxmox create requires reconciliation"),
                        evidence={
                            "last_durable_phase": recovery_session.phase,
                            "result": create_result,
                        },
                    )
                except Exception as exc:
                    raise VmCreateApplicationError(
                        503,
                        {
                            "code": "PROXMOX_CREATE_RECOVERY_PERSISTENCE_FAILED",
                            "message": "Create VM result requires reconciliation, but its durable evidence could not be persisted",
                            "draft_id": draft_id,
                            "operation_id": operation.operation_id,
                            "operation_status": operation.status,
                            "side_effects": list(create_result.get("side_effects") or []),
                        },
                    ) from exc
                try:
                    record_vm_create_request(
                        plan,
                        status=phase,
                        approval=decision.to_dict(),
                        result=create_result,
                        actor=actor_payload,
                    )
                    _record_plan_job(
                        plan,
                        status="failed",
                        stage="create",
                        step_status=phase,
                        message=(
                            "Proxmox native VM 생성 확인이 실패했습니다: "
                            f"{_native_error_summary(create_result, '')}"
                        ),
                        artifacts=[
                            *plan.artifacts,
                            *_artifacts_from_result(preview),
                            *_artifacts_from_result(create_result),
                        ],
                        details=_details_with_actor(
                            {
                                "proxmox_preview": preview,
                                "proxmox_create": create_result,
                                "target_lock": target_lock_evidence,
                            },
                            actor_payload,
                        ),
                    )
                except Exception as exc:
                    raise VmCreateApplicationError(
                        503,
                        {
                            "code": "PROXMOX_CREATE_PROJECTION_FAILED",
                            "message": "Create VM reconciliation evidence is durable, but a compatibility projection failed",
                            "draft_id": draft_id,
                            "operation_id": operation.operation_id,
                            "operation_status": operation.status,
                            "side_effects": list(create_result.get("side_effects") or []),
                        },
                    ) from exc
            raise VmCreateApplicationError(
                409,
                {
                    "code": (
                        "PROXMOX_CREATE_NEEDS_RECONCILIATION"
                        if phase == "needs_reconciliation"
                        else "PROXMOX_CREATE_FAILED"
                    ),
                    "message": _native_error_summary(
                        create_result,
                        "native Proxmox create failed",
                    ),
                    "draft_id": draft_id,
                    "operation_id": operation.operation_id,
                    "operation_status": operation.status,
                    "side_effects": list(create_result.get("side_effects") or []),
                    "proxmox_create": create_result,
                    "proxmox_preview": preview,
                },
            )

        try:
            operation = recovery_session.record_success_observed(create_result)
        except Exception as exc:
            if recovery_session.lease.item.status == "leased":
                try:
                    operation = recovery_session.pause_for_reconciliation(
                        code="PROXMOX_CREATE_SUCCESS_EVIDENCE_PERSISTENCE_FAILED",
                        message="Create success evidence could not be durably checkpointed",
                        evidence={
                            "last_durable_phase": recovery_session.phase,
                            "error_type": type(exc).__name__,
                        },
                    )
                except Exception:
                    pass
            raise VmCreateApplicationError(
                503,
                {
                    "code": "PROXMOX_CREATE_PROJECTION_FAILED",
                    "message": "Proxmox Create was observed, but its success evidence could not be durably checkpointed",
                    "draft_id": draft_id,
                    "operation_id": operation.operation_id,
                    "operation_status": operation.status,
                    "side_effects": list(create_result.get("side_effects") or []),
                },
            ) from exc

        try:
            projection = SqlAlchemyVmCreateRecoveryProjection()
            operation = recovery_session.complete_success(
                result=create_result,
                project_compatibility=lambda transaction: (
                    projection.record_verified_success_in_transaction(
                        transaction,
                        operation_id=plan.job_id,
                        target={"node_id": plan.target_node_id, "vmid": plan.vmid},
                        observed_after=dict(create_result.get("observed_after") or {}),
                        observed_after_artifact=dict(
                            create_result.get("observed_after_artifact") or {}
                        ),
                        completion_result=create_result,
                        recovered_after_restart=False,
                        job_details_patch=_details_with_actor(
                            {
                                "proxmox_preview": preview,
                                "proxmox_create": create_result,
                                "target_lock": target_lock_evidence,
                            },
                            actor_payload,
                        ),
                    )
                ),

            )
            request_record = dict(operation.details.get("vm_create_request") or {})
            vm_instance = dict(operation.details.get("workload") or {})
        except Exception as exc:
            if recovery_session.lease.item.status == "leased":
                try:
                    operation = recovery_session.defer_verified_projection(
                        error_type=type(exc).__name__,
                    )
                except Exception:
                    pass
            raise VmCreateApplicationError(
                503,
                {
                    "code": "PROXMOX_CREATE_PROJECTION_FAILED",
                    "message": "Proxmox Create was observed, but terminal evidence or a compatibility projection could not be closed",
                    "draft_id": draft_id,
                    "operation_id": operation.operation_id,
                    "operation_status": operation.status,
                    "side_effects": list(create_result.get("side_effects") or []),
                },
            ) from exc
        return VmCreateApplicationResult(
            _with_vm_create_operation(
                {
                    **create_result,
                    "approval": decision.to_dict(),
                    "proxmox_preview": preview,
                    "proxmox_create_ran": True,
                    "proxmox_create_status": "applied",
                    "vm_create_request": request_record,
                    "vm_instance": vm_instance,
                    "proxmox_create_enabled": True,
                    "proxmox_mutation_enabled": True,
                    "side_effects": list(create_result.get("side_effects") or []),
                    "idempotency": {"replayed": False, "request_id": plan.job_id},
                },
                operation,
            ),
            "proxmox_native_create_live_mutation",
        )
    finally:
        if recovery_session is None:
            release_target_operation_lock(target_lock)
