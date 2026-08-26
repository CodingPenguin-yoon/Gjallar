"""Legacy Jobs/Artifacts read projection routes kept for API compatibility."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.v1 import inventory_context
from app.api.v1.responses import success_response
from app.jobs.runs import get_job_run_strict, list_job_runs_strict

router = APIRouter()


def _jobs_meta() -> dict[str, str]:
    return {"source": inventory_context.inventory_query().adapter.source, "mode": "read_only"}


def _job_summary(run: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: value for key, value in run.items() if key not in {"artifacts", "risks"}},
        "artifact_count": len(run.get("artifacts") or []),
        "risk_count": len(run.get("risks") or []),
        "artifacts_url": f"/api/v1/jobs/{run['job_id']}/artifacts",
    }


def _persistence_unavailable(*, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": code,
            "message": message,
            "retryable": True,
            "side_effects": [],
        },
    )


def _list_job_entries(*, risks: bool = False) -> list[dict[str, Any]]:
    try:
        return list_job_runs_strict()
    except Exception as exc:
        if risks:
            raise _persistence_unavailable(
                code="RISKS_PERSISTENCE_UNAVAILABLE",
                message="Risk history is temporarily unavailable",
            ) from exc
        raise _persistence_unavailable(
            code="JOBS_PERSISTENCE_UNAVAILABLE",
            message="Job history is temporarily unavailable",
        ) from exc


def _job_entry_or_404(job_id: str) -> dict[str, Any]:
    try:
        entry = get_job_run_strict(job_id)
    except Exception as exc:
        raise _persistence_unavailable(
            code="JOBS_PERSISTENCE_UNAVAILABLE",
            message="Job history is temporarily unavailable",
        ) from exc
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


@router.get("/jobs")
async def list_jobs() -> dict:
    """Return read-only job history from compatibility run projections."""
    jobs = [_job_summary(entry) for entry in _list_job_entries()]
    return success_response(jobs, meta=_jobs_meta())


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    """Return one read-only compatibility job summary."""
    entry = _job_entry_or_404(job_id)
    return success_response(_job_summary(entry), meta=_jobs_meta())


@router.get("/jobs/{job_id}/artifacts")
async def list_job_artifacts(job_id: str) -> dict:
    """Return read-only artifact metadata for one compatibility job."""
    entry = _job_entry_or_404(job_id)
    return success_response(
        list(entry.get("artifacts") or []),
        meta=_jobs_meta(),
    )


@router.get("/risks")
async def list_risks() -> dict:
    """Return read-only risk summaries derived from compatibility job projections."""
    risks = []
    for job in _list_job_entries(risks=True):
        for risk in job.get("risks") or []:
            if isinstance(risk, dict):
                risks.append(_risk_summary(job, risk))
    return success_response(risks, meta=_jobs_meta())
