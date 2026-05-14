"""Read-only readiness checks for the Create VM IaC workspace."""

from __future__ import annotations

import os
from pathlib import Path

from app.vm_create.models import IacReadinessResult, PreflightCheck, RiskItem
from app.vm_create.paths import iac_path_context


def _risk_level(risks: list[RiskItem]) -> str:
    levels = {risk.level for risk in risks}
    if "red" in levels:
        return "red"
    if "yellow" in levels:
        return "yellow"
    return "green"


def _check(
    checks: list[PreflightCheck],
    risks: list[RiskItem],
    *,
    code: str,
    ok: bool,
    message: str,
    fail_code: str | None = None,
    fail_level: str = "red",
    detail: dict | None = None,
) -> None:
    level = "green" if ok else fail_level
    status = "pass" if ok else "fail"
    detail = dict(detail or {})
    checks.append(PreflightCheck(code=code, status=status, level=level, message=message, detail=detail))
    if not ok:
        risks.append(RiskItem(level=fail_level, code=fail_code or code, message=message, detail=detail))


def _is_accessible_directory(path: Path) -> bool:
    return path.exists() and path.is_dir() and os.access(path, os.R_OK | os.X_OK)


def _is_writable_directory(path: Path) -> bool:
    return _is_accessible_directory(path) and os.access(path, os.W_OK)


def run_iac_readiness() -> IacReadinessResult:
    """Inspect IaC roots without creating, committing, pushing, or applying anything."""
    context = iac_path_context()
    shared_root = Path(context["shared_root"])
    iac_root = Path(context["iac_root"])
    checks: list[PreflightCheck] = []
    risks: list[RiskItem] = []

    _check(
        checks,
        risks,
        code="shared_root_available",
        ok=_is_accessible_directory(shared_root),
        message="shared root is present and readable",
        fail_code="shared_root_missing",
        detail={"shared_root": str(shared_root)},
    )
    _check(
        checks,
        risks,
        code="iac_root_available",
        ok=_is_accessible_directory(iac_root),
        message="IaC root is present and readable",
        fail_code="iac_root_missing",
        detail={"iac_root": str(iac_root)},
    )
    _check(
        checks,
        risks,
        code="iac_root_writable",
        ok=_is_writable_directory(iac_root),
        message="IaC root is writable for manifest/generated changes",
        fail_code="iac_root_not_writable",
        detail={"iac_root": str(iac_root)},
    )
    git_marker = iac_root / ".git"
    git_ready = git_marker.exists()
    _check(
        checks,
        risks,
        code="iac_git_repo_available",
        ok=git_ready,
        message="IaC root is a Git checkout",
        fail_code="iac_git_repo_missing",
        fail_level="yellow",
        detail={"iac_root": str(iac_root), "git_marker": str(git_marker)},
    )

    manifests_vms = iac_root / "manifests" / "vms"
    generated = iac_root / "generated"
    allowlist_ready = _is_accessible_directory(manifests_vms) and _is_accessible_directory(generated)
    _check(
        checks,
        risks,
        code="iac_write_allowlist_ready",
        ok=allowlist_ready,
        message="IaC write allowlist folders are present",
        fail_code="iac_write_allowlist_missing",
        fail_level="yellow",
        detail={"required_paths": [str(manifests_vms), str(generated)]},
    )

    risk_level = _risk_level(risks)
    ready_for_plan = not any(risk.level == "red" for risk in risks)
    ready_for_execute = ready_for_plan and git_ready and allowlist_ready
    return IacReadinessResult(
        shared_root=str(shared_root),
        iac_root=str(iac_root),
        risk_level=risk_level,
        ready_for_plan=ready_for_plan,
        ready_for_execute=ready_for_execute,
        checks=checks,
        risks=risks,
        side_effects=[],
    )
