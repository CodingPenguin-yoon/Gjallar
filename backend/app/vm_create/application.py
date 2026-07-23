"""Application orchestration for the compatibility Create VM workflow.

This module owns the draft -> preflight -> plan -> approval -> execution
sequence. HTTP concerns stay in ``app.api.v1.vm_create_compat``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.auth.roles import AuthenticatedUser, actor_detail_fields, actor_evidence
from app.core.redaction import redact_secrets
from app.db.vm_runtime import (
    find_vm_create_request_for_target,
    get_vm_create_request_record,
    get_vm_instance_record,
    record_vm_create_request,
    record_vm_instance_from_create,
)
from app.jobs.runs import record_job_run, run_dir
from app.operations.core.domain import OperationIntentConflict, OperationStateConflict
from app.operations.target_lock import (
    TargetOperationLockBusy,
    acquire_target_operation_lock,
    release_target_operation_lock,
)
from app.operations.vm_create.domain import vm_create_plan_intent
from app.operations.vm_create.facade import (
    prepare_vm_create_operation,
    record_vm_create_approval,
    record_vm_create_compatibility_replay,
    record_vm_create_dispatch_prepared,
    record_vm_create_guard_blocked,
    record_vm_create_preview,
    record_vm_create_result,
    record_vm_create_succeeded,
    vm_create_operation_link,
)
from app.proxmox.client import ProxmoxMutationError
from app.vm_create.approval import validate_approval_request
from app.vm_create.drafts import build_default_vm_draft
from app.vm_create.planner import build_vm_create_plan
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

    proposed_vmid = (
        inventory_adapter.suggest_next_vmid()
        if hasattr(inventory_adapter, "suggest_next_vmid")
        else None
    )
    return build_default_vm_draft(
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


def preview_run_dir(job_id: str):
    return run_dir(job_id)


def build_preview_plan(
    draft_id: str,
    payload: dict | None,
    *,
    inventory_adapter: Any,
):
    draft = build_draft_from_payload(draft_id, payload, inventory_adapter=inventory_adapter)
    preflight = run_preflight(draft, inventory_adapter=inventory_adapter)
    return build_vm_create_plan(draft, preflight, run_dir=preview_run_dir(draft.job_id))


def _native_error_summary(result: dict[str, Any] | None, fallback: str) -> str:
    if isinstance(result, dict):
        message = str(result.get("message") or "").strip()
        if message:
            return message[:1000]
        task = result.get("task") if isinstance(result.get("task"), dict) else {}
        exitstatus = str(task.get("exitstatus") or "").strip()
        if exitstatus:
            return f"Proxmox task exitstatus: {exitstatus}"[:1000]
    return str(fallback or "Native Proxmox create failed")[:1000]


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


def _vm_instance_from_existing_result(plan: Any, existing: dict[str, Any]) -> dict[str, Any]:
    stored = get_vm_instance_record(plan.target_node_id, plan.vmid)
    if stored is not None:
        return stored
    result = existing.get("result") if isinstance(existing.get("result"), dict) else {}
    observed_after = result.get("observed_after") if isinstance(result.get("observed_after"), dict) else {}
    return {
        "vm_instance_id": f"{plan.target_node_id}:{int(plan.vmid)}",
        "node_id": plan.target_node_id,
        "vmid": int(plan.vmid),
        "name": plan.vm_name,
        "status": str(observed_after.get("status") or "not_recorded"),
        "updated_at": existing.get("updated_at", ""),
    }


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
            "vm_instance": _vm_instance_from_existing_result(plan, existing),
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
    if target_status == "completed":
        _raise_vm_create_target_block(
            draft_id=draft_id,
            plan=plan,
            existing=existing_target,
            code="PROXMOX_CREATE_TARGET_CONFLICT",
            message="this Proxmox VM target is already owned by a completed Create VM request",
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
    result = run_preflight(draft, inventory_adapter=inventory_adapter)
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
    preflight = run_preflight(draft, inventory_adapter=inventory_adapter)
    plan = build_vm_create_plan(draft, preflight, run_dir=preview_run_dir(draft.job_id))
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
        _with_vm_create_operation(plan.to_dict(), operation),
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
    plan = build_preview_plan(draft_id, payload, inventory_adapter=inventory_adapter)
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
    plan = build_preview_plan(draft_id, payload, inventory_adapter=inventory_adapter)
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
    plan = build_preview_plan(draft_id, payload, inventory_adapter=inventory_adapter)
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
        stored_workload = get_vm_instance_record(plan.target_node_id, plan.vmid)
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
        detail = _target_lock_busy_detail(exc, target_id=target_id, owner_id=owner_id)
        record_vm_create_guard_blocked(plan.job_id, detail, actor=actor)
        raise VmCreateApplicationError(
            409,
            {**detail, "operation_id": plan.job_id},
        ) from exc

    retain_target_lock = False
    try:
        target_lock_evidence = (
            target_lock.to_dict()
            if hasattr(target_lock, "to_dict")
            else {"handle": str(target_lock)}
        )
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

        try:
            operation = record_vm_create_dispatch_prepared(
                plan.job_id,
                preview=preview,
                target_lock=target_lock_evidence,
                actor=actor,
            )
        except OperationStateConflict as exc:
            raise _vm_create_operation_conflict(exc, draft_id=draft_id) from exc

        try:
            client = mutation_client_factory()
            retain_target_lock = True
            create_result = redact_secrets(
                await asyncio.to_thread(
                    run_proxmox_create,
                    plan,
                    run_dir=preview_run_dir(plan.job_id),
                    client=client,
                )
            )
        except ProxmoxMutationError as exc:
            create_result = {
                "success": False,
                "status": "failed",
                "message": str(exc),
                "side_effects": [],
            }

        if create_result.get("success") is not True or not create_result.get("observed_after_artifact"):
            side_effect_free_failure = not retain_target_lock or _is_clear_clone_rejection(create_result)
            if create_result.get("status") == "needs_reconciliation":
                phase = "needs_reconciliation"
            elif side_effect_free_failure:
                phase = "failed"
            else:
                phase = "apply_failed"
            try:
                operation = record_vm_create_result(
                    plan.job_id,
                    create_result,
                    side_effect_free_failure=side_effect_free_failure,
                    actor=actor,
                )
            except OperationStateConflict as exc:
                raise _vm_create_operation_conflict(exc, draft_id=draft_id) from exc
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
            if side_effect_free_failure:
                retain_target_lock = False
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
            operation = record_vm_create_result(
                plan.job_id,
                create_result,
                side_effect_free_failure=False,
                actor=actor,
            )
        except OperationStateConflict as exc:
            raise _vm_create_operation_conflict(exc, draft_id=draft_id) from exc
        request_record = record_vm_create_request(
            plan,
            status="completed",
            approval=decision.to_dict(),
            result=create_result,
            actor=actor_payload,
        )
        vm_instance = record_vm_instance_from_create(plan, create_result)
        _record_plan_job(
            plan,
            status="completed",
            stage="create",
            step_status="completed",
            message="Proxmox native VM 생성이 완료되었습니다.",
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
        try:
            operation = record_vm_create_succeeded(
                plan.job_id,
                result=create_result,
                request=request_record,
                workload=vm_instance,
                actor=actor,
            )
        except OperationStateConflict as exc:
            raise _vm_create_operation_conflict(exc, draft_id=draft_id) from exc
        retain_target_lock = False
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
        if not retain_target_lock:
            release_target_operation_lock(target_lock)
