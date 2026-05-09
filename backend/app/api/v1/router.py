"""Minimal non-mutating /api/v1 router skeleton.

Set 5 wires the read-only/fake Proxmox inventory adapter into the public
inventory routes. Live Proxmox mutations and create/apply flows remain out of
scope and require later RED tests plus approval gates.
"""

from __future__ import annotations
import hashlib
import re
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.v1.responses import success_response
from app.vm_create.approval import validate_approval_request
from app.jobs.models import ArtifactRecord, JobRecord
from app.manifests.loader import load_builtin_profiles
from app.proxmox.inventory import get_default_inventory_adapter
from app.vm_create.drafts import build_default_vm_draft
from app.vm_create.planner import build_vm_create_plan
from app.vm_create.preflight import run_preflight

router = APIRouter(prefix="/api/v1")


def _inventory_adapter():
    return get_default_inventory_adapter()


def _inventory_meta(adapter) -> dict:
    return {"source": adapter.source, "mode": "read_only"}


def _jobs_meta() -> dict[str, str]:
    return {"source": _inventory_adapter().source, "mode": "read_only"}


def _api_draft_from_payload(draft_id: str, payload: dict | None):
    payload = payload or {}
    return build_default_vm_draft(
        operator_id=str(payload.get("operator_id", "api-preview")),
        job_id=str(payload.get("job_id", draft_id)),
        target_node_id=payload.get("target_node_id"),
        static_ip=payload.get("static_ip"),
        ip_mode=payload.get("ip_mode"),
    )


def _safe_preview_segment(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value)).strip("-")
    return safe[:120] or "job"


def _api_preview_run_dir(job_id: str) -> Path:
    return Path(tempfile.gettempdir()) / "gjallar-set6-api-preview" / _safe_preview_segment(job_id)


def _api_preview_plan_from_payload(draft_id: str, payload: dict | None):
    draft = _api_draft_from_payload(draft_id, payload)
    preflight = run_preflight(draft, inventory_adapter=_inventory_adapter())
    return build_vm_create_plan(draft, preflight, run_dir=_api_preview_run_dir(draft.job_id))


def _artifact_checksum(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _artifact_id(job_id: str, artifact_type: str, filename: str) -> str:
    safe_type = artifact_type.replace("-", "_").replace("/", "_")
    safe_job = job_id.replace("-", "_").replace("/", "_")
    safe_file = Path(filename).stem.replace("-", "_")
    return f"artifact_{safe_type}_{safe_job}_{safe_file}"


def _artifact_record(
    *,
    job_id: str,
    artifact_type: str,
    filename: str,
    created_at: str,
) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=_artifact_id(job_id, artifact_type, filename),
        job_id=job_id,
        type=artifact_type,
        path=f"/artifacts/read-only-preview/{job_id}/{filename}",
        checksum=_artifact_checksum(f"{job_id}:{artifact_type}:{filename}"),
        created_at=created_at,
    )


def _job_fixture_index() -> dict[str, dict[str, Any]]:
    adapter = _inventory_adapter()

    planned_draft = build_default_vm_draft(
        operator_id="api-read-only",
        job_id="job-api-v1-plan",
    )
    planned_preflight = run_preflight(planned_draft, inventory_adapter=adapter)

    blocked_draft = build_default_vm_draft(
        operator_id="api-read-only",
        job_id="job-api-v1-risk",
        static_ip="192.168.2.141",
    )
    blocked_preflight = run_preflight(blocked_draft, inventory_adapter=adapter)

    return {
        planned_draft.job_id: {
            "job": JobRecord(
                job_id=planned_draft.job_id,
                job_type="vm_create_plan",
                status="completed",
                target_id=planned_draft.target_node_id,
                risk_level=planned_preflight.risk_level,
                started_at="2026-05-09T02:40:00+09:00",
                finished_at="2026-05-09T02:41:00+09:00",
            ),
            "artifacts": [
                _artifact_record(
                    job_id=planned_draft.job_id,
                    artifact_type="preflight_report",
                    filename="preflight_report.json",
                    created_at="2026-05-09T02:40:10+09:00",
                ),
                _artifact_record(
                    job_id=planned_draft.job_id,
                    artifact_type="plan",
                    filename="plan.json",
                    created_at="2026-05-09T02:40:20+09:00",
                ),
                _artifact_record(
                    job_id=planned_draft.job_id,
                    artifact_type="planned_git_diff",
                    filename="planned_git_diff.txt",
                    created_at="2026-05-09T02:40:25+09:00",
                ),
                _artifact_record(
                    job_id=planned_draft.job_id,
                    artifact_type="review_summary",
                    filename="review_summary.json",
                    created_at="2026-05-09T02:40:30+09:00",
                ),
            ],
            "risks": planned_preflight.risks,
        },
        blocked_draft.job_id: {
            "job": JobRecord(
                job_id=blocked_draft.job_id,
                job_type="vm_create_preflight",
                status="blocked",
                target_id=blocked_draft.target_node_id,
                risk_level=blocked_preflight.risk_level,
                started_at="2026-05-09T02:42:00+09:00",
                finished_at="2026-05-09T02:42:30+09:00",
            ),
            "artifacts": [
                _artifact_record(
                    job_id=blocked_draft.job_id,
                    artifact_type="preflight_report",
                    filename="preflight_report.json",
                    created_at="2026-05-09T02:42:10+09:00",
                ),
            ],
            "risks": blocked_preflight.risks,
        },
    }


def _job_summary(entry: dict[str, Any]) -> dict[str, Any]:
    job = entry["job"]
    risks = entry["risks"]
    return {
        **job.to_dict(),
        "artifact_count": len(entry["artifacts"]),
        "risk_count": len(risks),
        "artifacts_url": f"/api/v1/jobs/{job.job_id}/artifacts",
    }


def _job_entry_or_404(job_id: str) -> dict[str, Any]:
    try:
        return _job_fixture_index()[job_id]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc


def _risk_summary(job: JobRecord, risk) -> dict[str, Any]:
    return {
        "risk_id": f"{job.job_id}:{risk.code}",
        "job_id": job.job_id,
        "job_type": job.job_type,
        "job_status": job.status,
        **risk.to_dict(),
        "artifacts_url": f"/api/v1/jobs/{job.job_id}/artifacts",
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
    """Return builtin VM creation profile defaults."""
    return success_response([profile.to_dict() for profile in load_builtin_profiles()])


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
    """Return read-only MVP job history previews."""
    jobs = [_job_summary(entry) for entry in _job_fixture_index().values()]
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
        [artifact.to_dict() for artifact in entry["artifacts"]],
        meta=_jobs_meta(),
    )


@router.get("/risks")
async def list_risks() -> dict:
    """Return read-only risk summaries derived from MVP job previews."""
    risks = []
    for entry in _job_fixture_index().values():
        job = entry["job"]
        for risk in entry["risks"]:
            risks.append(_risk_summary(job, risk))
    return success_response(risks, meta=_jobs_meta())


@router.post("/vm-create/drafts")
async def create_vm_draft(payload: dict | None = None) -> dict:
    """Create a non-mutating default Create VM draft preview."""
    payload = payload or {}
    draft = build_default_vm_draft(
        operator_id=str(payload.get("operator_id", "api-preview")),
        job_id=str(payload.get("job_id", "job-api-preview")),
        target_node_id=payload.get("target_node_id"),
        static_ip=payload.get("static_ip"),
        ip_mode=payload.get("ip_mode"),
    )
    return success_response(draft.to_dict(), meta={"mode": "dry_run_draft_only"})


@router.post("/vm-create/{draft_id}/preflight")
async def preflight_vm_draft(draft_id: str, payload: dict | None = None) -> dict:
    """Run non-destructive preflight against the fake/read-only inventory."""
    payload = payload or {}
    draft = build_default_vm_draft(
        operator_id=str(payload.get("operator_id", "api-preview")),
        job_id=str(payload.get("job_id", draft_id)),
        target_node_id=payload.get("target_node_id"),
        static_ip=payload.get("static_ip"),
        ip_mode=payload.get("ip_mode"),
    )
    result = run_preflight(draft, inventory_adapter=_inventory_adapter())
    return success_response(result.to_dict(), meta={"mode": "fake_read_only_preflight"})


@router.post("/vm-create/{draft_id}/plan")
async def plan_vm_draft(draft_id: str, payload: dict | None = None) -> dict:
    """Build an artifact-backed dry-run plan without live side effects."""
    payload = payload or {}
    draft = build_default_vm_draft(
        operator_id=str(payload.get("operator_id", "api-preview")),
        job_id=str(payload.get("job_id", draft_id)),
        target_node_id=payload.get("target_node_id"),
        static_ip=payload.get("static_ip"),
        ip_mode=payload.get("ip_mode"),
    )
    preflight = run_preflight(draft, inventory_adapter=_inventory_adapter())
    plan = build_vm_create_plan(draft, preflight, run_dir=_api_preview_run_dir(draft.job_id))
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
    return success_response(decision.to_dict(), meta={"mode": "approval_validation_only"})


@router.post("/vm-create/{draft_id}/execute")
async def execute_vm_draft(draft_id: str, payload: dict | None = None) -> dict:
    """Fail closed until live GitOps/apply/Proxmox execution is explicitly approved."""
    raise HTTPException(
        status_code=409,
        detail={
            "code": "EXECUTE_REQUIRES_EXPLICIT_LIVE_APPROVAL",
            "message": "Live IaC mutation, Proxmox VM creation, and first power-on are not enabled in this safe backend slice.",
            "draft_id": draft_id,
            "side_effects": [],
        },
    )
