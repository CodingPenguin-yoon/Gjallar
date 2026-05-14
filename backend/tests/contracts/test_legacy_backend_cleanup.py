from pathlib import Path
import re


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


def test_legacy_terraform_executor_is_removed_from_active_tree():
    backend_root = Path(__file__).resolve().parents[2]
    repo_root = backend_root.parent

    removed_paths = [
        backend_root / "app/vm_create/terraform_runner.py",
        repo_root / "infra/terraform",
    ]
    offenders = [str(path.relative_to(repo_root)) for path in removed_paths if path.exists()]

    assert offenders == [], f"Legacy Terraform Create VM executor files must stay removed: {offenders}"


def test_removed_state_metadata_symbols_are_absent_from_active_tree():
    backend_root = Path(__file__).resolve().parents[2]
    repo_root = backend_root.parent
    active_roots = [
        backend_root / "app",
        backend_root / "tests",
        repo_root / "frontend/src",
        repo_root / "frontend/tests",
        repo_root / "docs/current",
        repo_root / "docs/architecture",
        repo_root / "docs/engineering",
        repo_root / "docs/ko",
        repo_root / "docs/product",
    ]
    forbidden_patterns = [
        "".join(parts)
        for parts in [
            ("terraform_", "state_path"),
            ("terraform_", "state_root"),
            ("GJALLAR_", "TF_STATE_ROOT"),
            ("GJALLAR_", "TERRAFORM_STATE_ROOT"),
            ("terraform", r"\.tf", "state"),
            ("terraform_", "apply_enabled"),
            ("legacy", "StateRoot"),
            ("terraform_", "state_lock_available"),
            ("state_", "backend"),
        ]
    ]
    combined = re.compile("|".join(forbidden_patterns))
    text_suffixes = {
        ".css",
        ".html",
        ".js",
        ".json",
        ".jsx",
        ".md",
        ".mjs",
        ".py",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
    }
    excluded_parts = {
        ".git",
        ".pytest_cache",
        "__pycache__",
        "dist",
        "legacy-prd",
        "node_modules",
    }
    offenders: list[str] = []

    for root in active_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in text_suffixes:
                continue
            relative = path.relative_to(repo_root)
            if excluded_parts & set(relative.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line_number, line in enumerate(text.splitlines(), start=1):
                match = combined.search(line)
                if match:
                    offenders.append(f"{relative}:{line_number}: {match.group(0)}")

    assert offenders == [], "Removed Terraform state/API symbols remain active: " + repr(offenders)


def test_korean_non_index_docs_declare_source_documents():
    backend_root = Path(__file__).resolve().parents[2]
    repo_root = backend_root.parent
    ko_docs_root = repo_root / "docs/ko"
    pages = sorted(path for path in ko_docs_root.glob("*.md") if path.name != "README.md")

    assert pages, "Expected Korean reader-facing docs under docs/ko"

    offenders = [
        str(path.relative_to(repo_root))
        for path in pages
        if "기준 문서:" not in path.read_text(encoding="utf-8")
    ]

    assert offenders == [], "Korean docs must declare 기준 문서: " + repr(offenders)
