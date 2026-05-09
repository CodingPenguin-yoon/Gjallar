from pathlib import Path


def test_drop_candidate_legacy_domains_are_not_active_import_packages():
    backend_root = Path(__file__).resolve().parents[2]

    active_legacy_dirs = [
        backend_root / "app/domains/deploy",
        backend_root / "app/domains/llm",
        backend_root / "app/domains/proxmox",
    ]

    offenders = [str(path.relative_to(backend_root)) for path in active_legacy_dirs if path.exists()]

    assert offenders == [], (
        "PRD v1 MVP active backend tree must not keep legacy deploy, LLM, "
        f"or legacy Proxmox domain packages importable: {offenders}"
    )

def test_legacy_task_domain_is_not_active_after_jobs_api_replacement():
    backend_root = Path(__file__).resolve().parents[2]
    task_domain = backend_root / "app/domains/task"

    assert not task_domain.exists(), (
        "PRD v1 MVP should use /api/v1/jobs and /api/v1/jobs/{job_id}/artifacts "
        "instead of keeping the legacy task/status/log domain importable"
    )
