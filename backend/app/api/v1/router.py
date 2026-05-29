"""PRD v1 /api/v1 router for inventory, Create VM, and job run inspection."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from app.api.v1.responses import success_response
from app.auth.dependencies import require_operator, require_viewer
from app.auth.roles import AuthenticatedUser, actor_detail_fields, actor_evidence
from app.core.redaction import redact_secrets
from app.db.vm_runtime import record_vm_create_request, record_vm_instance_from_create
from app.drs.advisor import build_drs_advisor_model, build_drs_check_result, find_drs_recommendation
from app.jobs.runs import get_job_run, list_job_runs, record_job_run, run_dir
from app.vm_create.approval import validate_approval_request
from app.proxmox.client import ProxmoxMutationError, get_default_proxmox_mutation_client
from app.proxmox.inventory import get_default_inventory_adapter
from app.vm_create.drafts import build_default_vm_draft, list_create_profile_options
from app.vm_create.iac_readiness import run_iac_readiness
from app.vm_create.planner import build_vm_create_plan
from app.vm_create.preflight import run_preflight
from app.vm_create.proxmox_runner import build_proxmox_create_preview, run_proxmox_create
from app.vm_actions.start import VmStartError, run_vm_start

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_viewer)])


def _inventory_adapter():
    return get_default_inventory_adapter()


def _inventory_meta(adapter) -> dict:
    return {"source": adapter.source, "mode": "read_only"}


def _jobs_meta() -> dict[str, str]:
    return {"source": _inventory_adapter().source, "mode": "read_only"}


def _details_with_actor(details: dict[str, Any] | None, actor: AuthenticatedUser | dict | None) -> dict[str, Any]:
    payload = dict(details or {})
    payload.update(actor_detail_fields(actor))
    return payload


def _drs_risks() -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for job in list_job_runs():
        for risk in job.get("risks") or []:
            if isinstance(risk, dict):
                risks.append(risk)
    return risks


def _api_draft_from_payload(draft_id: str, payload: dict | None):
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

    adapter = _inventory_adapter()
    proposed_vmid = adapter.suggest_next_vmid() if hasattr(adapter, "suggest_next_vmid") else None
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
        first_power_on_included=payload.get("first_power_on_included") if "first_power_on_included" in payload else payload.get("firstPowerOnIncluded"),
        power_policy=payload.get("power_policy") or payload.get("powerPolicy"),
    )


def _api_preview_run_dir(job_id: str):
    return run_dir(job_id)


def _api_preview_plan_from_payload(draft_id: str, payload: dict | None):
    draft = _api_draft_from_payload(draft_id, payload)
    preflight = run_preflight(draft, inventory_adapter=_inventory_adapter())
    return build_vm_create_plan(draft, preflight, run_dir=_api_preview_run_dir(draft.job_id))


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


def _risk_dicts_from_plan(plan) -> list[dict[str, Any]]:
    risk_summary = plan.risk_summary or {}
    return [
        *list(risk_summary.get("red") or []),
        *list(risk_summary.get("yellow") or []),
    ]


def _target_label(*, node_id: str, vm_name: str) -> str:
    return f"{node_id}:{vm_name}" if vm_name else node_id


def _record_draft_job(
    draft,
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
    draft,
    preflight,
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
        details=_details_with_actor({
            "draft": draft.to_dict(),
            "preflight": preflight.to_dict(),
        }, actor),
    )


def _record_plan_job(
    plan,
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
        details=_details_with_actor({
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
        }, actor),
    )


def _artifacts_from_result(result: dict[str, Any]) -> list[Any]:
    return [artifact for artifact in result.get("artifacts") or [] if isinstance(artifact, dict)]


def _job_summary(run: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: value for key, value in run.items() if key not in {"artifacts", "risks"}},
        "artifact_count": len(run.get("artifacts") or []),
        "risk_count": len(run.get("risks") or []),
        "artifacts_url": f"/api/v1/jobs/{run['job_id']}/artifacts",
    }


def _job_entry_or_404(job_id: str) -> dict[str, Any]:
    entry = get_job_run(job_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Job not found")
    return entry


def _risk_summary(job: dict[str, Any], risk: dict[str, Any]) -> dict[str, Any]:
    return {
        "risk_id": f"{job.get('job_id')}:{risk.get('code', 'risk')}",
        "job_id": job.get("job_id"),
        "job_type": job.get("job_type"),
        "job_status": job.get("status"),
        **risk,
        "artifacts_url": f"/api/v1/jobs/{job.get('job_id')}/artifacts",
    }


@router.get("/cluster/summary")
def cluster_summary() -> dict:
    """Return a read-only MVP cluster summary."""
    adapter = _inventory_adapter()
    snapshot = adapter.snapshot()
    return success_response(
        {
            "cluster_id": "gjallar-mvp",
            "mode": "read_only_inventory",
            "node_count": len(snapshot.nodes),
            "vm_count": len(snapshot.vms),
            "template_count": len(snapshot.templates),
            "risk_level": "unknown",
        },
        meta=_inventory_meta(adapter),
    )


@router.get("/nodes")
def list_nodes() -> dict:
    """Return read-only node inventory."""
    adapter = _inventory_adapter()
    nodes = adapter.list_nodes()
    return success_response(
        [node.to_dict() for node in nodes],
        meta=_inventory_meta(adapter),
    )


@router.get("/vms")
def list_vms() -> dict:
    """Return read-only VM inventory."""
    adapter = _inventory_adapter()
    vms = adapter.list_vms()
    return success_response(
        [vm.to_dict() for vm in vms],
        meta=_inventory_meta(adapter),
    )


@router.get("/vms/{vmid}")
def get_vm(vmid: int) -> dict:
    """Return a read-only VM detail for the requested VMID."""
    adapter = _inventory_adapter()
    vm = adapter.get_vm(vmid)
    if vm is None:
        raise HTTPException(status_code=404, detail="VM inventory item not found")
    return success_response(vm.to_dict(), meta=_inventory_meta(adapter))


@router.get("/profiles")
async def list_profiles() -> dict:
    """Return active DB-backed VM creation profile defaults."""
    return success_response([profile.to_dict() for profile in list_create_profile_options()])


@router.get("/vm-create/readiness")
async def get_vm_create_readiness() -> dict:
    """Return read-only IaC workspace readiness for the Create VM flow."""
    return success_response(run_iac_readiness().to_dict(), meta={"mode": "read_only_iac_readiness"})


@router.get("/templates")
def list_templates() -> dict:
    """Return read-only template inventory."""
    adapter = _inventory_adapter()
    templates = adapter.list_templates()
    return success_response(
        [template.to_dict() for template in templates],
        meta=_inventory_meta(adapter),
    )


@router.get("/storage")
def list_storage() -> dict:
    """Return read-only storage candidates from inventory."""
    adapter = _inventory_adapter()
    storages = adapter.list_storage()
    return success_response(
        [storage.to_dict() for storage in storages],
        meta=_inventory_meta(adapter),
    )


@router.get("/networks")
def list_networks() -> dict:
    """Return read-only network bridge inventory."""
    adapter = _inventory_adapter()
    networks = adapter.list_networks()
    return success_response(
        [network.to_dict() for network in networks],
        meta=_inventory_meta(adapter),
    )


@router.get("/jobs")
async def list_jobs() -> dict:
    """Return read-only job history from Create VM run status records."""
    jobs = [_job_summary(entry) for entry in list_job_runs()]
    return success_response(jobs, meta=_jobs_meta())


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    """Return one read-only MVP job summary."""
    entry = _job_entry_or_404(job_id)
    return success_response(_job_summary(entry), meta=_jobs_meta())


@router.get("/jobs/{job_id}/artifacts")
async def list_job_artifacts(job_id: str) -> dict:
    """Return read-only artifact metadata for one MVP job."""
    entry = _job_entry_or_404(job_id)
    return success_response(
        list(entry.get("artifacts") or []),
        meta=_jobs_meta(),
    )


@router.get("/risks")
async def list_risks() -> dict:
    """Return read-only risk summaries derived from Create VM run records."""
    risks = []
    for job in list_job_runs():
        for risk in job.get("risks") or []:
            if isinstance(risk, dict):
                risks.append(_risk_summary(job, risk))
    return success_response(risks, meta=_jobs_meta())


@router.get("/drs/summary")
def get_drs_summary() -> dict:
    """Return the read-only DRS Advisor summary and current candidates."""
    adapter = _inventory_adapter()
    return success_response(
        build_drs_advisor_model(adapter, risks=_drs_risks()),
        meta={"source": adapter.source, "mode": "drs_advisor_read_only"},
    )


@router.get("/drs/recommendations")
def list_drs_recommendations() -> dict:
    """Return read-only DRS Advisor recommendations."""
    adapter = _inventory_adapter()
    return success_response(
        build_drs_advisor_model(adapter, risks=_drs_risks()),
        meta={"source": adapter.source, "mode": "drs_advisor_read_only"},
    )


@router.get("/drs/recommendations/{recommendation_id}")
def get_drs_recommendation(recommendation_id: str) -> dict:
    """Return one read-only DRS Advisor recommendation."""
    adapter = _inventory_adapter()
    recommendation = find_drs_recommendation(adapter, recommendation_id, risks=_drs_risks())
    if recommendation is None:
        raise HTTPException(status_code=404, detail="DRS recommendation not found")
    return success_response(
        recommendation,
        meta={"source": adapter.source, "mode": "drs_advisor_read_only"},
    )


@router.post("/drs/recommendations/{recommendation_id}/check")
def check_drs_recommendation(recommendation_id: str, payload: dict | None = None) -> dict:
    """Run a read-only final pre-check for one recommendation."""
    adapter = _inventory_adapter()
    result = build_drs_check_result(adapter, recommendation_id, risks=_drs_risks(), payload=payload)
    if result is None:
        raise HTTPException(status_code=404, detail="DRS recommendation not found")
    return success_response(
        result,
        meta={"source": adapter.source, "mode": "drs_advisor_read_only"},
    )


async def start_vm_action(
    node_id: str,
    vmid: int,
    payload: dict | None = None,
    actor: AuthenticatedUser | dict | None = None,
) -> dict:
    """Start a stopped VM through the explicit VM action path."""
    try:
        result = await run_in_threadpool(
            run_vm_start,
            node_id=node_id,
            vmid=vmid,
            payload=payload or {},
            actor=actor_evidence(actor) if actor is not None else None,
            inventory_adapter=_inventory_adapter(),
            client_factory=get_default_proxmox_mutation_client,
        )
    except VmStartError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
    return success_response(result, meta={"mode": "proxmox_native_vm_start"})


@router.post("/nodes/{node_id}/vms/{vmid}/actions/start")
async def start_vm_action_route(
    node_id: str,
    vmid: int,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    return await start_vm_action(node_id, vmid, payload, actor=actor)


async def create_vm_draft(payload: dict | None = None, actor: AuthenticatedUser | dict | None = None) -> dict:
    """Create a non-mutating default Create VM draft preview."""
    draft = _api_draft_from_payload("job-api-preview", payload or {})
    _record_draft_job(
        draft,
        status="in_progress",
        stage="draft",
        step_status="completed",
        message="VM 생성 요청 입력이 준비되었습니다.",
        actor=actor,
    )
    return success_response(draft.to_dict(), meta={"mode": "dry_run_draft_only"})


@router.post("/vm-create/drafts")
async def create_vm_draft_route(
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    return await create_vm_draft(payload, actor=actor)


async def preflight_vm_draft(
    draft_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser | dict | None = None,
) -> dict:
    """Run non-destructive preflight against the fake/read-only inventory."""
    draft = _api_draft_from_payload(draft_id, payload)
    result = run_preflight(draft, inventory_adapter=_inventory_adapter())
    _record_preflight_job(
        draft,
        result,
        status="blocked" if result.risk_level == "red" else "in_progress",
        step_status="blocked" if result.risk_level == "red" else "completed",
        message="사전 검토가 완료되었습니다." if result.risk_level != "red" else "사전 검토에서 차단 항목이 발견되었습니다.",
        actor=actor,
    )
    return success_response(result.to_dict(), meta={"mode": "read_only_preflight"})


@router.post("/vm-create/{draft_id}/preflight")
async def preflight_vm_draft_route(
    draft_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    return await preflight_vm_draft(draft_id, payload, actor=actor)


async def plan_vm_draft(
    draft_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser | dict | None = None,
) -> dict:
    """Build an artifact-backed dry-run plan without live side effects."""
    draft = _api_draft_from_payload(draft_id, payload)
    preflight = run_preflight(draft, inventory_adapter=_inventory_adapter())
    plan = build_vm_create_plan(draft, preflight, run_dir=_api_preview_run_dir(draft.job_id))
    _record_plan_job(
        plan,
        status="blocked" if plan.risk_summary.get("level") == "red" else "in_progress",
        stage="plan",
        step_status="blocked" if plan.risk_summary.get("level") == "red" else "completed",
        message="생성 계획과 검토 패킷이 준비되었습니다.",
        actor=actor,
    )
    return success_response(plan.to_dict(), meta={"mode": "dry_run_plan_only"})


@router.post("/vm-create/{draft_id}/plan")
async def plan_vm_draft_route(
    draft_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    return await plan_vm_draft(draft_id, payload, actor=actor)


async def approve_vm_draft(
    draft_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser | dict | None = None,
) -> dict:
    """Validate Review & Confirm approval metadata without live side effects."""
    payload = payload or {}
    plan = _api_preview_plan_from_payload(draft_id, payload)
    decision = validate_approval_request(
        plan,
        plan_artifact_id=str(payload.get("plan_artifact_id", "")),
        review_summary_checksum=str(payload.get("review_summary_checksum", "")),
        yellow_risk_acknowledged=payload.get("yellow_risk_acknowledged") is True,
        run_dir=_api_preview_run_dir(plan.job_id),
    )
    _record_plan_job(
        plan,
        status="in_progress" if decision.can_execute else "blocked",
        stage="approval",
        step_status="completed" if decision.can_execute else "blocked",
        message="승인이 확인되었습니다." if decision.can_execute else f"승인이 차단되었습니다: {decision.reason}",
        details={"approval": decision.to_dict()},
        actor=actor,
    )
    return success_response(decision.to_dict(), meta={"mode": "approval_validation_only"})


@router.post("/vm-create/{draft_id}/approve")
async def approve_vm_draft_route(
    draft_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    return await approve_vm_draft(draft_id, payload, actor=actor)


async def preview_vm_draft_proxmox_create(
    draft_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser | dict | None = None,
) -> dict:
    """Build a non-mutating native Proxmox create preview after approval."""
    payload = payload or {}
    plan = _api_preview_plan_from_payload(draft_id, payload)
    decision = validate_approval_request(
        plan,
        plan_artifact_id=str(payload.get("plan_artifact_id", "")),
        review_summary_checksum=str(payload.get("review_summary_checksum", "")),
        yellow_risk_acknowledged=payload.get("yellow_risk_acknowledged") is True,
        run_dir=_api_preview_run_dir(plan.job_id),
    )
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
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PROXMOX_PREVIEW_APPROVAL_GATE_BLOCKED",
                "message": decision.reason,
                "draft_id": draft_id,
                "side_effects": [],
            },
        )

    preview = build_proxmox_create_preview(plan, run_dir=_api_preview_run_dir(plan.job_id))
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
    return success_response(
        {
            **preview,
            "approval": decision.to_dict(),
            "proxmox_create_enabled": False,
            "proxmox_mutation_enabled": False,
        },
        meta={"mode": "proxmox_native_preview_no_mutation"},
    )


@router.post("/vm-create/{draft_id}/proxmox-preview")
async def preview_vm_draft_proxmox_create_route(
    draft_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    return await preview_vm_draft_proxmox_create(draft_id, payload, actor=actor)


async def create_vm_draft_proxmox_native(
    draft_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser | dict | None = None,
) -> dict:
    """Create a powered-off VM through the native Proxmox API after approval and final acknowledgement."""
    payload = payload or {}
    actor_payload = actor_evidence(actor) if actor is not None else {}
    plan = _api_preview_plan_from_payload(draft_id, payload)
    decision = validate_approval_request(
        plan,
        plan_artifact_id=str(payload.get("plan_artifact_id", "")),
        review_summary_checksum=str(payload.get("review_summary_checksum", "")),
        yellow_risk_acknowledged=payload.get("yellow_risk_acknowledged") is True,
        run_dir=_api_preview_run_dir(plan.job_id),
    )
    if not decision.can_execute:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PROXMOX_CREATE_APPROVAL_GATE_BLOCKED",
                "message": decision.reason,
                "draft_id": draft_id,
                "side_effects": [],
            },
        )
    if payload.get("proxmox_mutation_acknowledged") is not True:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PROXMOX_CREATE_ACK_REQUIRED",
                "message": "proxmox_mutation_acknowledged=true is required before native Proxmox create",
                "draft_id": draft_id,
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
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PROXMOX_CREATE_PREFLIGHT_RED_RISK",
                "message": "red risk blocks native Proxmox create",
                "draft_id": draft_id,
                "side_effects": [],
            },
        )

    preview = build_proxmox_create_preview(plan, run_dir=_api_preview_run_dir(plan.job_id))
    record_vm_create_request(
        plan,
        status="running",
        approval=decision.to_dict(),
        result={"proxmox_preview": preview},
        actor=actor_payload,
    )

    _record_plan_job(
        plan,
        status="running",
        stage="create",
        step_status="running",
        message="Proxmox native VM 생성 작업을 시작했습니다.",
        artifacts=[*plan.artifacts, *_artifacts_from_result(preview)],
        details=_details_with_actor({"approval": decision.to_dict(), "proxmox_preview": preview}, actor_payload),
    )

    try:
        client = get_default_proxmox_mutation_client()
        create_result = redact_secrets(
            await run_in_threadpool(
                run_proxmox_create,
                plan,
                run_dir=_api_preview_run_dir(plan.job_id),
                client=client,
            )
        )
    except ProxmoxMutationError as exc:
        create_result = {"success": False, "status": "failed", "message": str(exc), "side_effects": []}

    if create_result.get("success") is not True or not create_result.get("observed_after_artifact"):
        phase = "needs_reconciliation" if create_result.get("status") == "needs_reconciliation" else "apply_failed"
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
            message=f"Proxmox native VM 생성 확인이 실패했습니다: {_native_error_summary(create_result, '')}",
            artifacts=[*plan.artifacts, *_artifacts_from_result(preview), *_artifacts_from_result(create_result)],
            details=_details_with_actor({
                "proxmox_preview": preview,
                "proxmox_create": create_result,
            }, actor_payload),
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PROXMOX_CREATE_NEEDS_RECONCILIATION" if phase == "needs_reconciliation" else "PROXMOX_CREATE_FAILED",
                "message": _native_error_summary(create_result, "native Proxmox create failed"),
                "draft_id": draft_id,
                "side_effects": list(create_result.get("side_effects") or []),
                "proxmox_create": create_result,
                "proxmox_preview": preview,
            },
        )

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
        artifacts=[*plan.artifacts, *_artifacts_from_result(preview), *_artifacts_from_result(create_result)],
        details=_details_with_actor({
            "proxmox_preview": preview,
            "proxmox_create": create_result,
        }, actor_payload),
    )
    return success_response(
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
        },
        meta={"mode": "proxmox_native_create_live_mutation"},
    )


@router.post("/vm-create/{draft_id}/proxmox-create")
async def create_vm_draft_proxmox_native_route(
    draft_id: str,
    payload: dict | None = None,
    actor: AuthenticatedUser = Depends(require_operator),
) -> dict:
    return await create_vm_draft_proxmox_native(draft_id, payload, actor=actor)
