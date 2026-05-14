"""PRD v1 /api/v1 router for inventory, Create VM, and job run inspection."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from app.api.v1.responses import success_response
from app.core.redaction import redact_secrets
from app.jobs.runs import get_job_run, list_job_runs, record_job_run, run_dir
from app.network_policy import NetworkPolicyError, build_network_policy_view, save_network_policy
from app.vm_create.approval import validate_approval_request
from app.proxmox.client import ProxmoxMutationError, get_default_proxmox_mutation_client
from app.proxmox.inventory import get_default_inventory_adapter
from app.vm_create.drafts import build_default_vm_draft, list_create_profile_options
from app.vm_create.gitops import (
    GitOpsCommitError,
    archive_plan_manifest,
    commit_plan_manifest,
    update_plan_manifest_status,
    verify_plan_manifest_commit,
)
from app.vm_create.iac_readiness import run_iac_readiness
from app.vm_create.planner import build_vm_create_plan
from app.vm_create.preflight import run_preflight
from app.vm_create.proxmox_runner import build_proxmox_create_preview, run_proxmox_create
from app.vm_create.terraform_runner import (
    TerraformRunnerError,
    build_terraform_workspace,
    run_terraform_apply,
    run_terraform_plan,
    terraform_apply_commands,
    terraform_plan_commands,
)

router = APIRouter(prefix="/api/v1")


def _inventory_adapter():
    return get_default_inventory_adapter()


def _inventory_meta(adapter) -> dict:
    return {"source": adapter.source, "mode": "read_only"}


def _jobs_meta() -> dict[str, str]:
    return {"source": _inventory_adapter().source, "mode": "read_only"}


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
    )


def _api_preview_run_dir(job_id: str):
    return run_dir(job_id)


def _api_preview_plan_from_payload(draft_id: str, payload: dict | None):
    draft = _api_draft_from_payload(draft_id, payload)
    preflight = run_preflight(draft, inventory_adapter=_inventory_adapter())
    return build_vm_create_plan(draft, preflight, run_dir=_api_preview_run_dir(draft.job_id))


def _terraform_error_summary(results: list[dict[str, Any]], fallback: str) -> str:
    for result in reversed(results):
        text = str(result.get("stderr") or result.get("stdout") or "").strip()
        if text:
            return text[:1000]
    return str(fallback or "Terraform apply failed")[:1000]


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


def _record_draft_job(draft, *, status: str, stage: str, step_status: str, message: str) -> dict[str, Any]:
    return record_job_run(
        job_id=draft.job_id,
        job_type="vm_create",
        status=status,
        target_id=_target_label(node_id=draft.target_node_id, vm_name=draft.vm_name),
        risk_level="unknown",
        stage=stage,
        step_status=step_status,
        message=message,
        details=draft.to_dict(),
    )


def _record_preflight_job(draft, preflight, *, status: str, step_status: str, message: str) -> dict[str, Any]:
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
        details={
            "draft": draft.to_dict(),
            "preflight": preflight.to_dict(),
        },
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
        details={
            "draft_id": plan.draft_id,
            "manifest_id": plan.manifest_id,
            "profile_id": plan.profile_id,
            "vm_name": plan.vm_name,
            "vmid": plan.vmid,
            "target_node_id": plan.target_node_id,
            "storage_id": plan.storage_id,
            "template_id": plan.template_id,
            "network": plan.network,
            **(details or {}),
        },
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
    """Return static read-only VM creation profile defaults."""
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


@router.get("/networks/policy")
def get_network_policy() -> dict:
    """Return live vmbr inventory combined with IaC network policy state."""
    adapter = _inventory_adapter()
    networks = adapter.list_networks()
    try:
        view = build_network_policy_view(networks)
    except NetworkPolicyError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "NETWORK_POLICY_READ_FAILED",
                "message": str(exc),
                "side_effects": [],
            },
        ) from exc
    return success_response(view, meta={**_inventory_meta(adapter), "mode": "network_policy_read"})


@router.put("/networks/policy")
def put_network_policy(payload: dict | None = None) -> dict:
    """Persist the network policy under the shared IaC manifests folder."""
    try:
        result = save_network_policy((payload or {}).get("policy") or payload or {})
    except NetworkPolicyError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "NETWORK_POLICY_WRITE_FAILED",
                "message": str(exc),
                "side_effects": [],
            },
        ) from exc
    return success_response(result, meta={"mode": "iac_network_policy_write"})


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


@router.post("/vm-create/drafts")
async def create_vm_draft(payload: dict | None = None) -> dict:
    """Create a non-mutating default Create VM draft preview."""
    draft = _api_draft_from_payload("job-api-preview", payload or {})
    _record_draft_job(
        draft,
        status="in_progress",
        stage="draft",
        step_status="completed",
        message="VM 생성 요청 입력이 준비되었습니다.",
    )
    return success_response(draft.to_dict(), meta={"mode": "dry_run_draft_only"})


@router.post("/vm-create/{draft_id}/preflight")
async def preflight_vm_draft(draft_id: str, payload: dict | None = None) -> dict:
    """Run non-destructive preflight against the fake/read-only inventory."""
    draft = _api_draft_from_payload(draft_id, payload)
    result = run_preflight(draft, inventory_adapter=_inventory_adapter())
    _record_preflight_job(
        draft,
        result,
        status="blocked" if result.risk_level == "red" else "in_progress",
        step_status="blocked" if result.risk_level == "red" else "completed",
        message="사전 검토가 완료되었습니다." if result.risk_level != "red" else "사전 검토에서 차단 항목이 발견되었습니다.",
    )
    return success_response(result.to_dict(), meta={"mode": "read_only_preflight"})


@router.post("/vm-create/{draft_id}/plan")
async def plan_vm_draft(draft_id: str, payload: dict | None = None) -> dict:
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
    )
    return success_response(plan.to_dict(), meta={"mode": "dry_run_plan_only"})

@router.post("/vm-create/{draft_id}/approve")
async def approve_vm_draft(draft_id: str, payload: dict | None = None) -> dict:
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
    )
    return success_response(decision.to_dict(), meta={"mode": "approval_validation_only"})


@router.post("/vm-create/{draft_id}/proxmox-preview")
async def preview_vm_draft_proxmox_create(draft_id: str, payload: dict | None = None) -> dict:
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
        stage="workspace",
        step_status="completed",
        message="Proxmox native 생성 미리보기가 준비되었습니다.",
        artifacts=[*plan.artifacts, *_artifacts_from_result(preview)],
        details={"approval": decision.to_dict(), "proxmox_preview": preview},
    )
    return success_response(
        {
            **preview,
            "approval": decision.to_dict(),
            "proxmox_create_enabled": False,
            "proxmox_mutation_enabled": False,
            "terraform_apply_enabled": False,
        },
        meta={"mode": "proxmox_native_preview_no_mutation"},
    )


@router.post("/vm-create/{draft_id}/proxmox-create")
async def create_vm_draft_proxmox_native(draft_id: str, payload: dict | None = None) -> dict:
    """Create a powered-off VM through the native Proxmox API after commit and final acknowledgement."""
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

    try:
        manifest_path = verify_plan_manifest_commit(plan, str(payload.get("manifest_commit_sha", "")))
    except GitOpsCommitError as exc:
        _record_plan_job(
            plan,
            status="blocked",
            stage="commit",
            step_status="blocked",
            message=f"저장된 생성 요청 확인이 차단되었습니다: {exc}",
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PROXMOX_CREATE_MANIFEST_COMMIT_BLOCKED",
                "message": str(exc),
                "draft_id": draft_id,
                "side_effects": [],
            },
        ) from exc

    _record_plan_job(
        plan,
        status="running",
        stage="create",
        step_status="running",
        message="Proxmox native VM 생성 작업을 시작했습니다.",
        details={"manifest_path": manifest_path, "approval": decision.to_dict()},
    )
    try:
        applying_status = update_plan_manifest_status(plan, "applying")
    except GitOpsCommitError as exc:
        _record_plan_job(
            plan,
            status="blocked",
            stage="create",
            step_status="blocked",
            message=f"생성 상태 기록이 차단되었습니다: {exc}",
            details={"manifest_path": manifest_path},
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PROXMOX_CREATE_STATUS_BLOCKED",
                "message": str(exc),
                "draft_id": draft_id,
                "side_effects": [],
            },
        ) from exc

    status_side_effects = list(applying_status.side_effects)
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
        manifest_status: dict[str, Any] = {}
        manifest_status_commit_sha = ""
        try:
            failed_status = update_plan_manifest_status(
                plan,
                phase,
                last_error=_native_error_summary(create_result, "native Proxmox create failed"),
            )
            manifest_status = failed_status.manifest_status
            manifest_status_commit_sha = failed_status.commit_sha
            status_side_effects.extend(failed_status.side_effects)
        except GitOpsCommitError as status_exc:
            status_side_effects.append("iac_manifest_status_update_failed")
            manifest_status = {"phase": phase, "last_error": str(status_exc), "updated_at": ""}
        _record_plan_job(
            plan,
            status="failed",
            stage="create",
            step_status=phase,
            message=f"Proxmox native VM 생성 확인이 실패했습니다: {_native_error_summary(create_result, '')}",
            artifacts=[*plan.artifacts, *_artifacts_from_result(create_result)],
            details={
                "manifest_path": manifest_path,
                "manifest_status": manifest_status,
                "proxmox_create": create_result,
            },
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PROXMOX_CREATE_NEEDS_RECONCILIATION" if phase == "needs_reconciliation" else "PROXMOX_CREATE_FAILED",
                "message": _native_error_summary(create_result, "native Proxmox create failed"),
                "draft_id": draft_id,
                "side_effects": [*status_side_effects, *list(create_result.get("side_effects") or [])],
                "proxmox_create": create_result,
                "manifest_status": manifest_status,
                "manifest_status_commit_sha": manifest_status_commit_sha,
            },
        )

    try:
        applied_status = update_plan_manifest_status(plan, "applied")
    except GitOpsCommitError as exc:
        _record_plan_job(
            plan,
            status="failed",
            stage="create",
            step_status="failed",
            message=f"VM 생성은 확인됐지만 상태 기록이 실패했습니다: {exc}",
            artifacts=[*plan.artifacts, *_artifacts_from_result(create_result)],
            details={"manifest_path": manifest_path, "proxmox_create": create_result},
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PROXMOX_CREATE_STATUS_UPDATE_FAILED",
                "message": f"Native Proxmox create was observed, but manifest status update failed: {exc}",
                "draft_id": draft_id,
                "side_effects": [*status_side_effects, *list(create_result.get("side_effects") or [])],
                "proxmox_create": create_result,
                "proxmox_create_ran": True,
            },
        ) from exc

    status_side_effects.extend(applied_status.side_effects)
    _record_plan_job(
        plan,
        status="completed",
        stage="create",
        step_status="completed",
        message="Proxmox native VM 생성이 완료되었습니다.",
        artifacts=[*plan.artifacts, *_artifacts_from_result(create_result)],
        details={
            "manifest_path": manifest_path,
            "manifest_status": applied_status.manifest_status,
            "proxmox_create": create_result,
        },
    )
    return success_response(
        {
            **create_result,
            "approval": decision.to_dict(),
            "manifest_path": manifest_path,
            "manifest_commit_sha": str(payload.get("manifest_commit_sha", "")),
            "manifest_status": applied_status.manifest_status,
            "manifest_status_commit_sha": applied_status.commit_sha,
            "proxmox_create_ran": True,
            "proxmox_create_status": "applied",
            "proxmox_create_enabled": True,
            "proxmox_mutation_enabled": True,
            "terraform_apply_enabled": False,
            "side_effects": [*status_side_effects, *list(create_result.get("side_effects") or [])],
        },
        meta={"mode": "proxmox_native_create_live_mutation"},
    )


@router.post("/vm-create/{draft_id}/terraform-plan")
async def prepare_vm_draft_terraform_plan(draft_id: str, payload: dict | None = None) -> dict:
    """Prepare an approved Terraform plan workspace without applying changes."""
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
            message=f"생성 준비가 차단되었습니다: {decision.reason}",
            details={"approval": decision.to_dict()},
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "TERRAFORM_PLAN_APPROVAL_GATE_BLOCKED",
                "message": decision.reason,
                "draft_id": draft_id,
                "side_effects": [],
            },
        )
    if plan.review_confirm.get("iac_ready_for_plan") is not True:
        _record_plan_job(
            plan,
            status="blocked",
            stage="workspace",
            step_status="blocked",
            message="IaC 작업 공간이 준비되지 않아 생성 준비가 차단되었습니다.",
            details={"approval": decision.to_dict()},
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "TERRAFORM_PLAN_IAC_BLOCKED",
                "message": "IaC workspace is not ready for Terraform plan preparation",
                "draft_id": draft_id,
                "side_effects": [],
            },
        )

    workspace = build_terraform_workspace(
        plan,
        workspace_root=_api_preview_run_dir(plan.job_id) / "terraform-workspace",
    )
    commands = terraform_plan_commands(workspace)
    should_run_plan = payload.get("run_terraform_plan") is True
    run_results: list[dict[str, Any]] = []
    _record_plan_job(
        plan,
        status="running" if should_run_plan else "in_progress",
        stage="workspace",
        step_status="running" if should_run_plan else "completed",
        message="Terraform 검토를 실행 중입니다." if should_run_plan else "생성 준비 파일이 만들어졌습니다.",
        details={"workspace": workspace.to_dict(), "approval": decision.to_dict()},
    )
    if should_run_plan:
        if payload.get("terraform_plan_acknowledged") is not True:
            _record_plan_job(
                plan,
                status="blocked",
                stage="workspace",
                step_status="blocked",
                message="Terraform 검토 실행 승인이 필요합니다.",
                details={"workspace": workspace.to_dict(), "approval": decision.to_dict()},
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "TERRAFORM_PLAN_RUN_ACK_REQUIRED",
                    "message": "terraform_plan_acknowledged=true is required before contacting the live provider",
                    "draft_id": draft_id,
                    "side_effects": workspace.side_effects,
                },
            )
        try:
            run_results = redact_secrets(await run_in_threadpool(run_terraform_plan, workspace))
        except TerraformRunnerError as exc:
            run_results = redact_secrets(getattr(exc, "results", []))
            _record_plan_job(
                plan,
                status="failed",
                stage="workspace",
                step_status="failed",
                message=f"Terraform 검토가 실패했습니다: {exc}",
                details={"workspace": workspace.to_dict(), "terraform_plan_results": run_results},
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "TERRAFORM_PLAN_FAILED",
                    "message": str(exc),
                    "draft_id": draft_id,
                    "side_effects": workspace.side_effects,
                    "terraform_plan_results": run_results,
                },
            ) from exc
        _record_plan_job(
            plan,
            status="in_progress",
            stage="workspace",
            step_status="completed",
            message="Terraform 검토가 완료되었습니다.",
            details={"workspace": workspace.to_dict(), "terraform_plan_results": run_results},
        )

    return success_response(
        {
            **workspace.to_dict(),
            "approval": decision.to_dict(),
            "commands": commands,
            "terraform_plan_ran": should_run_plan,
            "terraform_plan_results": run_results,
            "terraform_apply_enabled": False,
            "proxmox_mutation_enabled": False,
        },
        meta={"mode": "terraform_plan_prepare_only" if not should_run_plan else "terraform_plan_live_read_only"},
    )


@router.post("/vm-create/{draft_id}/terraform-apply")
async def apply_vm_draft_terraform_plan(draft_id: str, payload: dict | None = None) -> dict:
    """Run Terraform apply for an approved, committed VM create plan."""
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
        raise HTTPException(
            status_code=409,
            detail={
                "code": "TERRAFORM_APPLY_APPROVAL_GATE_BLOCKED",
                "message": decision.reason,
                "draft_id": draft_id,
                "side_effects": [],
            },
        )
    if plan.review_confirm.get("iac_ready_for_execute") is not True:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "TERRAFORM_APPLY_IAC_BLOCKED",
                "message": "IaC workspace is not ready for Terraform apply",
                "draft_id": draft_id,
                "side_effects": [],
            },
        )
    if payload.get("terraform_plan_acknowledged") is not True:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "TERRAFORM_APPLY_PLAN_ACK_REQUIRED",
                "message": "terraform_plan_acknowledged=true is required before Terraform apply",
                "draft_id": draft_id,
                "side_effects": [],
            },
        )
    if payload.get("terraform_apply_acknowledged") is not True or payload.get("proxmox_mutation_acknowledged") is not True:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "TERRAFORM_APPLY_ACK_REQUIRED",
                "message": "terraform_apply_acknowledged=true and proxmox_mutation_acknowledged=true are required",
                "draft_id": draft_id,
                "side_effects": [],
            },
        )

    try:
        manifest_path = verify_plan_manifest_commit(plan, str(payload.get("manifest_commit_sha", "")))
    except GitOpsCommitError as exc:
        _record_plan_job(
            plan,
            status="blocked",
            stage="commit",
            step_status="blocked",
            message=f"저장된 생성 요청 확인이 차단되었습니다: {exc}",
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "TERRAFORM_APPLY_MANIFEST_COMMIT_BLOCKED",
                "message": str(exc),
                "draft_id": draft_id,
                "side_effects": [],
            },
        ) from exc

    workspace = build_terraform_workspace(
        plan,
        workspace_root=_api_preview_run_dir(plan.job_id) / "terraform-workspace",
    )
    expected_plan_path = str(payload.get("expected_plan_path") or "").strip()
    if expected_plan_path and expected_plan_path != workspace.plan_path:
        _record_plan_job(
            plan,
            status="blocked",
            stage="workspace",
            step_status="blocked",
            message="검토된 Terraform plan 경로가 현재 작업 공간과 다릅니다.",
            details={"workspace": workspace.to_dict()},
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "TERRAFORM_APPLY_PLAN_PATH_MISMATCH",
                "message": "expected_plan_path does not match the generated workspace plan path",
                "draft_id": draft_id,
                "side_effects": workspace.side_effects,
            },
        )

    _record_plan_job(
        plan,
        status="running",
        stage="create",
        step_status="running",
        message="실제 VM 생성 작업을 시작했습니다.",
        details={"workspace": workspace.to_dict(), "manifest_path": manifest_path},
    )
    try:
        applying_status = update_plan_manifest_status(plan, "applying")
    except GitOpsCommitError as exc:
        _record_plan_job(
            plan,
            status="blocked",
            stage="create",
            step_status="blocked",
            message=f"생성 상태 기록이 차단되었습니다: {exc}",
            details={"workspace": workspace.to_dict(), "manifest_path": manifest_path},
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "TERRAFORM_APPLY_STATUS_BLOCKED",
                "message": str(exc),
                "draft_id": draft_id,
                "side_effects": workspace.side_effects,
            },
        ) from exc

    status_side_effects = list(applying_status.side_effects)
    try:
        apply_results = redact_secrets(await run_in_threadpool(run_terraform_apply, workspace))
    except TerraformRunnerError as exc:
        apply_results = redact_secrets(getattr(exc, "results", []))
        manifest_status: dict[str, Any] = {}
        manifest_status_commit_sha = ""
        try:
            failed_status = update_plan_manifest_status(
                plan,
                "apply_failed",
                last_error=_terraform_error_summary(apply_results, str(exc)),
            )
            manifest_status = failed_status.manifest_status
            manifest_status_commit_sha = failed_status.commit_sha
            status_side_effects.extend(failed_status.side_effects)
        except GitOpsCommitError as status_exc:
            status_side_effects.append("iac_manifest_status_update_failed")
            manifest_status = {"phase": "apply_failed", "last_error": str(status_exc), "updated_at": ""}
        _record_plan_job(
            plan,
            status="failed",
            stage="create",
            step_status="failed",
            message=f"VM 생성이 실패했습니다: {_terraform_error_summary(apply_results, str(exc))}",
            details={
                "workspace": workspace.to_dict(),
                "manifest_path": manifest_path,
                "manifest_status": manifest_status,
                "terraform_apply_results": apply_results,
            },
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "TERRAFORM_APPLY_FAILED",
                "message": str(exc),
                "draft_id": draft_id,
                "side_effects": [*workspace.side_effects, *status_side_effects, "terraform_apply_invoked"],
                "terraform_apply_results": apply_results,
                "manifest_status": manifest_status,
                "manifest_status_commit_sha": manifest_status_commit_sha,
            },
        ) from exc

    try:
        applied_status = update_plan_manifest_status(plan, "applied")
    except GitOpsCommitError as exc:
        _record_plan_job(
            plan,
            status="failed",
            stage="create",
            step_status="failed",
            message=f"VM 생성은 실행됐지만 상태 기록이 실패했습니다: {exc}",
            details={
                "workspace": workspace.to_dict(),
                "manifest_path": manifest_path,
                "terraform_apply_results": apply_results,
            },
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "TERRAFORM_APPLY_STATUS_UPDATE_FAILED",
                "message": f"Terraform apply ran, but manifest status update failed: {exc}",
                "draft_id": draft_id,
                "side_effects": [*workspace.side_effects, *status_side_effects, "terraform_apply_invoked"],
                "terraform_apply_results": apply_results,
                "terraform_apply_ran": True,
            },
        ) from exc
    status_side_effects.extend(applied_status.side_effects)
    _record_plan_job(
        plan,
        status="completed",
        stage="create",
        step_status="completed",
        message="VM 생성이 완료되었습니다.",
        details={
            "workspace": workspace.to_dict(),
            "manifest_path": manifest_path,
            "manifest_status": applied_status.manifest_status,
            "terraform_apply_results": apply_results,
        },
    )

    return success_response(
        {
            **workspace.to_dict(),
            "approval": decision.to_dict(),
            "manifest_path": manifest_path,
            "manifest_commit_sha": str(payload.get("manifest_commit_sha", "")),
            "manifest_status": applied_status.manifest_status,
            "manifest_status_commit_sha": applied_status.commit_sha,
            "commands": terraform_apply_commands(workspace),
            "terraform_apply_ran": True,
            "terraform_apply_results": apply_results,
            "terraform_apply_enabled": True,
            "proxmox_mutation_enabled": True,
            "side_effects": [*workspace.side_effects, *status_side_effects, "terraform_apply_invoked"],
        },
        meta={"mode": "terraform_apply_live_mutation"},
    )


@router.post("/vm-create/{draft_id}/execute")
async def execute_vm_draft(draft_id: str, payload: dict | None = None) -> dict:
    """Commit the approved VMInstance manifest, but do not apply or touch Proxmox."""
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
        raise HTTPException(
            status_code=409,
            detail={
                "code": "EXECUTE_APPROVAL_GATE_BLOCKED",
                "message": decision.reason,
                "draft_id": draft_id,
                "side_effects": [],
            },
        )
    try:
        result = commit_plan_manifest(plan)
    except GitOpsCommitError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "GITOPS_COMMIT_BLOCKED",
                "message": str(exc),
                "draft_id": draft_id,
                "side_effects": [],
            },
        ) from exc
    _record_plan_job(
        plan,
        status="pending",
        stage="commit",
        step_status="completed",
        message="생성 요청이 저장되었습니다. 실제 VM 생성 실행을 기다립니다.",
        details={"approval": decision.to_dict(), "commit": result.to_dict()},
    )
    return success_response(
        {
            **result.to_dict(),
            "approval": decision.to_dict(),
            "proxmox_mutation_enabled": False,
            "terraform_apply_enabled": False,
        },
        meta={"mode": "gitops_commit_only"},
    )


@router.post("/vm-create/{draft_id}/archive")
async def archive_vm_draft_manifest(draft_id: str, payload: dict | None = None) -> dict:
    """Archive an unapplied VMInstance manifest without touching Proxmox."""
    payload = payload or {}
    if payload.get("archive_acknowledged") is not True:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ARCHIVE_ACK_REQUIRED",
                "message": "archive_acknowledged=true is required before archiving a VM create request",
                "draft_id": draft_id,
                "side_effects": [],
            },
        )

    plan = _api_preview_plan_from_payload(draft_id, payload)
    try:
        result = archive_plan_manifest(
            plan,
            reason=str(payload.get("reason") or "operator archived unapplied create request"),
            operator_id=str(payload.get("operator_id") or ""),
        )
    except GitOpsCommitError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "GITOPS_ARCHIVE_BLOCKED",
                "message": str(exc),
                "draft_id": draft_id,
                "side_effects": [],
            },
        ) from exc

    _record_plan_job(
        plan,
        status="completed",
        stage="commit",
        step_status="completed",
        message="생성 요청이 보관되었습니다.",
        details={"archive": result.to_dict()},
    )
    return success_response(
        {
            **result.to_dict(),
            "proxmox_mutation_enabled": False,
            "terraform_apply_enabled": False,
        },
        meta={"mode": "gitops_archive_only"},
    )
