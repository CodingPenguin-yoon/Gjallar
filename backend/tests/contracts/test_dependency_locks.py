"""Contracts for the pip source declarations and reproducible lock files."""

from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version


REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"


def _requirement_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "-r "))
    ]


def _locked_versions(path: Path) -> dict[str, Version]:
    versions: dict[str, Version] = {}
    for line in _requirement_lines(path):
        requirement = Requirement(line)
        exact = [specifier for specifier in requirement.specifier if specifier.operator == "=="]
        assert len(exact) == 1, f"lock entry must use one exact version: {line}"
        versions[canonicalize_name(requirement.name)] = Version(exact[0].version)
    return versions


def test_runtime_lock_contains_compatible_exact_versions_for_every_direct_dependency():
    locked = _locked_versions(BACKEND_ROOT / "requirements.lock")

    for line in _requirement_lines(BACKEND_ROOT / "requirements.txt"):
        requirement = Requirement(line)
        name = canonicalize_name(requirement.name)
        assert name in locked, f"runtime lock is missing direct dependency: {requirement.name}"
        assert requirement.specifier.contains(locked[name], prereleases=True), (
            f"runtime lock version {locked[name]} violates direct declaration {line}"
        )


def test_development_lock_contains_compatible_exact_versions_for_test_dependencies():
    locked = {
        **_locked_versions(BACKEND_ROOT / "requirements.lock"),
        **_locked_versions(BACKEND_ROOT / "requirements-dev.lock"),
    }

    for line in _requirement_lines(BACKEND_ROOT / "requirements-dev.txt"):
        requirement = Requirement(line)
        name = canonicalize_name(requirement.name)
        assert name in locked, f"development lock is missing direct dependency: {requirement.name}"
        assert requirement.specifier.contains(locked[name], prereleases=True), (
            f"development lock version {locked[name]} violates direct declaration {line}"
        )
