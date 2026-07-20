from pathlib import Path
import re
from urllib.parse import unquote


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


def test_legacy_bootstrap_playbooks_are_removed_from_active_tree():
    backend_root = Path(__file__).resolve().parents[2]
    repo_root = backend_root.parent

    removed_paths = [
        repo_root / "infra/ansible",
    ]
    offenders = [str(path.relative_to(repo_root)) for path in removed_paths if path.exists()]

    assert offenders == [], f"Legacy Ansible bootstrap files must stay removed: {offenders}"


def test_legacy_create_vm_iac_readiness_is_removed_from_active_tree():
    backend_root = Path(__file__).resolve().parents[2]
    repo_root = backend_root.parent

    removed_paths = [
        backend_root / "app/vm_create/iac_readiness.py",
        backend_root / "app/vm_create/paths.py",
    ]
    missing_path_offenders = [str(path.relative_to(repo_root)) for path in removed_paths if path.exists()]

    active_roots = [
        backend_root / "app",
        backend_root / "tests",
        repo_root / "frontend/src",
        repo_root / "frontend/tests",
        repo_root / "project-docs",
        repo_root / "README.md",
        repo_root / "backend/README.md",
        repo_root / "frontend/README.md",
        repo_root / ".env.example",
    ]
    forbidden_patterns = [
        r"run_iac_readiness",
        r"iac_readiness",
        r"IacReadiness",
        r"vm-create/readiness",
        r"getVmCreateReadiness",
        r"GJALLAR_SHARED_ROOT",
        r"GJALLAR_IAC_ROOT",
        r"HERMES_DATA_ROOT",
        r"\biac_root\b",
        r"\biac_ready_for_plan\b",
        r"\biac_ready_for_execute\b",
        r"shared_root_available",
        r"iac_root_available",
        r"iac_git_repo_available",
        r"iac_write_allowlist_ready",
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
    symbol_offenders: list[str] = []
    self_path = Path(__file__).resolve()

    for root in active_roots:
        if not root.exists():
            continue
        paths = [root] if root.is_file() else root.rglob("*")
        for path in paths:
            if path.resolve() == self_path:
                continue
            if not path.is_file() or path.suffix not in text_suffixes:
                continue
            relative = path.relative_to(repo_root)
            if excluded_parts & set(relative.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line_number, line in enumerate(text.splitlines(), start=1):
                match = combined.search(line)
                if match:
                    symbol_offenders.append(f"{relative}:{line_number}: {match.group(0)}")

    assert missing_path_offenders == [], (
        "Legacy Create VM IaC readiness modules must stay removed: "
        + repr(missing_path_offenders)
    )
    assert symbol_offenders == [], (
        "Legacy Create VM IaC readiness symbols remain active: "
        + repr(symbol_offenders)
    )


def test_env_example_does_not_advertise_legacy_integrations():
    backend_root = Path(__file__).resolve().parents[2]
    repo_root = backend_root.parent
    env_example = repo_root / ".env.example"

    forbidden = [
        "".join(parts)
        for parts in [
            ("GJALLAR_", "TF_STATE_ROOT"),
            ("ANSIBLE", "_"),
            ("GEMINI", "_"),
            ("GITLAB", "_"),
            ("PLATFORM_", "PUBLIC_BASE_URL"),
            ("Terraform", " VM creation"),
        ]
    ]
    text = env_example.read_text(encoding="utf-8")
    offenders = [item for item in forbidden if item in text]

    assert offenders == [], f"Legacy env example keys or labels remain: {offenders}"


def test_removed_state_metadata_symbols_are_absent_from_active_tree():
    backend_root = Path(__file__).resolve().parents[2]
    repo_root = backend_root.parent
    active_roots = [
        backend_root / "app",
        backend_root / "tests",
        repo_root / "frontend/src",
        repo_root / "frontend/tests",
        repo_root / "project-docs",
        repo_root / "README.md",
        repo_root / "backend/README.md",
        repo_root / "frontend/README.md",
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


def test_project_docs_are_the_only_active_documentation_tree():
    backend_root = Path(__file__).resolve().parents[2]
    repo_root = backend_root.parent
    docs_root = repo_root / "docs"
    project_docs_root = repo_root / "project-docs"
    required_paths = [
        project_docs_root / "project-profile.md",
        project_docs_root / "specifications/project-specification.md",
        project_docs_root / "architecture/overview.md",
        project_docs_root / "decisions/adr-001-proxmox-gjallar-authority-boundary.md",
        project_docs_root / "decisions/adr-002-modular-monolith-domain-boundaries.md",
        project_docs_root / "domains/domain-map.md",
        project_docs_root / "flows/verified-operation-lifecycle.md",
        project_docs_root / "api/current-api-v1.md",
        project_docs_root / "database/current-schema-and-ownership.md",
        project_docs_root / "operations/runbook.md",
    ]
    missing = [str(path.relative_to(repo_root)) for path in required_paths if not path.is_file()]

    assert not docs_root.exists(), "Legacy docs/ tree must stay removed after the project-docs reset"
    assert missing == [], "Required project-docs files are missing: " + repr(missing)


def _markdown_link_targets(text: str) -> list[str]:
    pattern = re.compile(r"!?\[[^\]]+\]\(([^)\n]+)\)")
    targets: list[str] = []
    for match in pattern.finditer(text):
        raw_target = match.group(1).strip()
        if not raw_target:
            continue
        if raw_target.startswith("<"):
            end = raw_target.find(">")
            if end == -1:
                targets.append(raw_target)
                continue
            targets.append(raw_target[1:end].strip())
            continue
        targets.append(raw_target.split()[0])
    return targets


def _is_external_link(target: str) -> bool:
    lowered = target.lower()
    return lowered.startswith(
        (
            "http://",
            "https://",
            "mailto:",
            "tel:",
            "data:",
            "javascript:",
        )
    )


def _heading_slugs(markdown: str) -> set[str]:
    slugs: set[str] = set()
    counts: dict[str, int] = {}
    for line in markdown.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if not match:
            continue
        title = re.sub(r"\s+#+\s*$", "", match.group(2)).strip()
        title = re.sub(r"`([^`]*)`", r"\1", title)
        slug = title.lower()
        slug = re.sub(r"[^\w\s가-힣ㄱ-ㅎㅏ-ㅣ.-]", "", slug)
        slug = re.sub(r"\s+", "-", slug).strip("-")
        if not slug:
            continue
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        slugs.add(slug if count == 0 else f"{slug}-{count}")
    return slugs


def test_active_readmes_point_to_project_docs_instead_of_legacy_docs():
    backend_root = Path(__file__).resolve().parents[2]
    repo_root = backend_root.parent
    readmes = [
        repo_root / "README.md",
        repo_root / "backend/README.md",
        repo_root / "frontend/README.md",
    ]
    offenders: list[str] = []

    for path in readmes:
        text = path.read_text(encoding="utf-8")
        if "project-docs/" not in text and "../project-docs/" not in text:
            offenders.append(str(path.relative_to(repo_root)))

    assert offenders == [], "Active READMEs must point readers to project-docs: " + repr(offenders)


def test_active_project_docs_relative_markdown_links_resolve_locally():
    backend_root = Path(__file__).resolve().parents[2]
    repo_root = backend_root.parent
    project_docs_root = repo_root / "project-docs"
    evidence_root = project_docs_root / "evidence"
    pages = [
        path
        for path in sorted(project_docs_root.rglob("*.md"))
        if evidence_root not in path.parents or path == evidence_root / "legacy-live-smoke/README.md"
    ]
    pages.extend(
        [
            repo_root / "README.md",
            repo_root / "backend/README.md",
            repo_root / "frontend/README.md",
        ]
    )

    missing: list[str] = []
    bad_anchors: list[str] = []
    outside_repo: list[str] = []

    for path in pages:
        text = path.read_text(encoding="utf-8")
        for target in _markdown_link_targets(text):
            if _is_external_link(target):
                continue
            href, has_fragment, fragment = target.partition("#")
            href = unquote(href)
            if not href:
                resolved = path
            elif href.startswith("/"):
                resolved = repo_root / href.lstrip("/")
            else:
                resolved = (path.parent / href).resolve()

            try:
                relative = resolved.relative_to(repo_root)
            except ValueError:
                outside_repo.append(f"{path.relative_to(repo_root)} -> {target}")
                continue

            if not resolved.exists():
                missing.append(f"{path.relative_to(repo_root)} -> {target} ({relative})")
                continue

            if has_fragment and fragment and resolved.is_file() and resolved.suffix == ".md":
                slugs = _heading_slugs(resolved.read_text(encoding="utf-8"))
                if unquote(fragment).lower() not in slugs:
                    bad_anchors.append(f"{path.relative_to(repo_root)} -> {target}")

    assert outside_repo == [], "Active docs relative links must stay in repo: " + repr(outside_repo)
    assert missing == [], "Active docs relative links must resolve: " + repr(missing)
    assert bad_anchors == [], "Active docs markdown anchors must resolve: " + repr(bad_anchors)
