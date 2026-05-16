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
    pages = sorted(path for path in ko_docs_root.rglob("*.md") if path.name != "README.md")

    assert pages, "Expected Korean reader-facing docs under docs/ko"

    offenders = [
        str(path.relative_to(repo_root))
        for path in pages
        if "기준 문서:" not in path.read_text(encoding="utf-8")
    ]

    assert offenders == [], "Korean docs must declare 기준 문서: " + repr(offenders)


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


def _contains_nested_docs_ko(path: Path) -> bool:
    parts = path.parts
    for index in range(len(parts) - 3):
        if parts[index : index + 4] == ("docs", "ko", "docs", "ko"):
            return True
    return False


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


def test_korean_docs_do_not_nest_docs_ko_paths_or_links():
    backend_root = Path(__file__).resolve().parents[2]
    repo_root = backend_root.parent
    ko_docs_root = repo_root / "docs/ko"

    nested_paths = [
        str(path.relative_to(repo_root))
        for path in ko_docs_root.rglob("*")
        if _contains_nested_docs_ko(path.relative_to(repo_root))
    ]

    assert nested_paths == [], "Korean docs must not contain nested docs/ko paths: " + repr(nested_paths)

    nested_links: list[str] = []
    for path in sorted(ko_docs_root.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        for target in _markdown_link_targets(text):
            if _is_external_link(target) or target.startswith("#"):
                continue
            href, _, _fragment = target.partition("#")
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
                continue
            if _contains_nested_docs_ko(relative):
                nested_links.append(f"{path.relative_to(repo_root)} -> {target}")

    assert nested_links == [], "Korean docs must not link to nested docs/ko paths: " + repr(nested_links)


def test_korean_docs_relative_markdown_links_resolve_locally():
    backend_root = Path(__file__).resolve().parents[2]
    repo_root = backend_root.parent
    ko_docs_root = repo_root / "docs/ko"

    missing: list[str] = []
    bad_anchors: list[str] = []
    outside_repo: list[str] = []

    for path in sorted(ko_docs_root.rglob("*.md")):
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

    assert outside_repo == [], "Korean docs relative links must stay in repo: " + repr(outside_repo)
    assert missing == [], "Korean docs relative links must resolve: " + repr(missing)
    assert bad_anchors == [], "Korean docs markdown anchors must resolve: " + repr(bad_anchors)
