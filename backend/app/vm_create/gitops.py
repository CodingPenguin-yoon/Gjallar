"""Approval-gated GitOps writes for Create VM manifests."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from app.vm_create.manifest import vm_instance_manifest_path
from app.vm_create.models import GitOpsCommitResult, VmCreatePlan


class GitOpsCommitError(RuntimeError):
    """Raised when an approved plan cannot be committed safely."""


ACTIVE_PHASES = {"pending", "planned", "applying", "apply_failed", "applied", "needs_reconciliation", "archived"}


def _run_git(iac_root: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": os.getenv("GJALLAR_GIT_AUTHOR_NAME", "Gjallar"),
        "GIT_AUTHOR_EMAIL": os.getenv("GJALLAR_GIT_AUTHOR_EMAIL", "gjallar@localhost"),
        "GIT_COMMITTER_NAME": os.getenv("GJALLAR_GIT_COMMITTER_NAME", "Gjallar"),
        "GIT_COMMITTER_EMAIL": os.getenv("GJALLAR_GIT_COMMITTER_EMAIL", "gjallar@localhost"),
    }
    completed = subprocess.run(
        ["git", "-C", str(iac_root), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "git command failed").strip()
        raise GitOpsCommitError(message)
    return completed.stdout.strip()


def _ensure_clean_repo(iac_root: Path) -> None:
    status = _run_git(iac_root, "status", "--porcelain")
    if status.strip():
        raise GitOpsCommitError("IaC repository has uncommitted changes; refresh and review before execution")


def _read_manifest_artifact(plan: VmCreatePlan) -> str:
    artifact = next((item for item in plan.artifacts if item.type == "vm_instance_manifest"), None)
    if artifact is None:
        raise GitOpsCommitError("plan is missing vm_instance_manifest artifact")
    path = Path(artifact.path).resolve()
    if not path.is_file():
        raise GitOpsCommitError("vm_instance_manifest artifact file is missing")
    return path.read_text(encoding="utf-8")


def _load_manifest_yaml(text: str) -> dict[str, Any]:
    loaded = yaml.safe_load(text) or {}
    if not isinstance(loaded, dict):
        raise GitOpsCommitError("VMInstance manifest is not a YAML mapping")
    return loaded


def _manifest_without_status(text: str) -> dict[str, Any]:
    manifest = _load_manifest_yaml(text)
    manifest.pop("status", None)
    return manifest


def _manifest_matches_desired_state(existing: str, expected: str) -> bool:
    return _manifest_without_status(existing) == _manifest_without_status(expected)


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _manifest_status(manifest: dict[str, Any]) -> dict[str, Any]:
    status = manifest.get("status")
    return dict(status) if isinstance(status, dict) else {}


def _resolve_manifest_target(iac_root: Path, manifest_id: str) -> tuple[str, Path]:
    relative_path = vm_instance_manifest_path(manifest_id)
    target = (iac_root / relative_path).resolve()
    root = iac_root.resolve()
    if not target.is_relative_to(root):
        raise GitOpsCommitError("manifest path escaped IaC root")
    if not relative_path.startswith("manifests/vms/"):
        raise GitOpsCommitError("manifest path is outside Gjallar write allowlist")
    return relative_path, target


def _iac_root_from_plan(plan: VmCreatePlan) -> Path:
    review = dict(plan.review_confirm)
    iac_root = Path(str(review.get("iac_root") or "")).expanduser()
    if not iac_root:
        raise GitOpsCommitError("plan review is missing iac_root")
    if not (iac_root / ".git").exists():
        raise GitOpsCommitError("IaC root is not a Git checkout")
    return iac_root


def _validate_vm_manifest(plan: VmCreatePlan, manifest: dict[str, Any]) -> None:
    if manifest.get("kind") != "VMInstance":
        raise GitOpsCommitError("manifest is not a VMInstance")
    metadata = manifest.get("metadata") if isinstance(manifest.get("metadata"), dict) else {}
    if metadata.get("id") != plan.manifest_id:
        raise GitOpsCommitError("manifest id does not match this plan")


def commit_plan_manifest(plan: VmCreatePlan) -> GitOpsCommitResult:
    """Write the approved VMInstance manifest and create a local IaC commit.

    This function deliberately does not push, run Terraform, call Proxmox, or
    power on anything. It is the first state-changing GitOps step after approval.
    """
    iac_root = _iac_root_from_plan(plan)
    if dict(plan.review_confirm).get("iac_ready_for_execute") is not True:
        raise GitOpsCommitError("IaC root is not ready for execution")

    relative_path, target = _resolve_manifest_target(iac_root, plan.manifest_id)
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        expected = _read_manifest_artifact(plan)
        if _manifest_matches_desired_state(existing, expected):
            existing_manifest = _load_manifest_yaml(existing)
            commit_sha = _run_git(iac_root, "log", "-n", "1", "--format=%H", "--", relative_path)
            return GitOpsCommitResult(
                job_id=plan.job_id,
                manifest_id=plan.manifest_id,
                execution_intent="gitops_commit_only",
                iac_root=str(iac_root),
                manifest_path=relative_path,
                commit_sha=commit_sha,
                apply_enabled=False,
                next_stage="proxmox_create_pending",
                side_effects=["iac_manifest_already_present"],
                manifest_status=_manifest_status(existing_manifest),
            )
        raise GitOpsCommitError(f"VMInstance manifest already exists with different content: {relative_path}")

    _ensure_clean_repo(iac_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_read_manifest_artifact(plan), encoding="utf-8")

    _run_git(iac_root, "add", "--", relative_path)
    _run_git(
        iac_root,
        "commit",
        "-m",
        f"feat: add VM manifest {plan.manifest_id}",
        "-m",
        f"job_id: {plan.job_id}",
    )
    commit_sha = _run_git(iac_root, "rev-parse", "HEAD")
    return GitOpsCommitResult(
        job_id=plan.job_id,
        manifest_id=plan.manifest_id,
        execution_intent="gitops_commit_only",
        iac_root=str(iac_root),
        manifest_path=relative_path,
        commit_sha=commit_sha,
        apply_enabled=False,
        next_stage="proxmox_create_pending",
        side_effects=["iac_manifest_written", "iac_git_commit_created"],
        manifest_status={"phase": "pending", "last_error": "", "updated_at": ""},
    )


def update_plan_manifest_status(plan: VmCreatePlan, phase: str, *, last_error: str = "") -> GitOpsCommitResult:
    """Update the committed VMInstance status and commit the status change."""
    phase = str(phase or "").strip()
    if phase not in ACTIVE_PHASES:
        raise GitOpsCommitError(f"unsupported VMInstance status phase: {phase}")

    iac_root = _iac_root_from_plan(plan)
    relative_path, target = _resolve_manifest_target(iac_root, plan.manifest_id)
    if not target.is_file():
        raise GitOpsCommitError(f"VMInstance manifest is missing: {relative_path}")

    manifest = _load_manifest_yaml(target.read_text(encoding="utf-8"))
    _validate_vm_manifest(plan, manifest)
    current_status = _manifest_status(manifest)
    normalized_error = str(last_error or "").strip()
    if current_status.get("phase") == phase and str(current_status.get("last_error") or "") == normalized_error:
        commit_sha = _run_git(iac_root, "log", "-n", "1", "--format=%H", "--", relative_path)
        return GitOpsCommitResult(
            job_id=plan.job_id,
            manifest_id=plan.manifest_id,
            execution_intent="gitops_status_update",
            iac_root=str(iac_root),
            manifest_path=relative_path,
            commit_sha=commit_sha,
            apply_enabled=False,
            next_stage=phase,
            side_effects=[f"iac_manifest_status_already_{phase}"],
            manifest_status=current_status,
        )

    _ensure_clean_repo(iac_root)
    manifest["status"] = {
        **current_status,
        "phase": phase,
        "last_error": normalized_error,
        "updated_at": _now_utc(),
    }
    target.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")
    _run_git(iac_root, "add", "--", relative_path)
    _run_git(
        iac_root,
        "commit",
        "-m",
        f"chore: mark VM manifest {plan.manifest_id} {phase}",
        "-m",
        f"job_id: {plan.job_id}",
    )
    commit_sha = _run_git(iac_root, "rev-parse", "HEAD")
    return GitOpsCommitResult(
        job_id=plan.job_id,
        manifest_id=plan.manifest_id,
        execution_intent="gitops_status_update",
        iac_root=str(iac_root),
        manifest_path=relative_path,
        commit_sha=commit_sha,
        apply_enabled=False,
        next_stage=phase,
        side_effects=[f"iac_manifest_status_{phase}", "iac_git_commit_created"],
        manifest_status=_manifest_status(manifest),
    )


def archive_plan_manifest(plan: VmCreatePlan, *, reason: str = "", operator_id: str = "") -> GitOpsCommitResult:
    """Move an unapplied VMInstance manifest out of the active desired-state folder."""
    iac_root = _iac_root_from_plan(plan)
    active_relative_path, active_target = _resolve_manifest_target(iac_root, plan.manifest_id)
    if not active_target.is_file():
        raise GitOpsCommitError(f"VMInstance manifest is missing: {active_relative_path}")

    archive_relative_path = f"manifests/archive/vms/{plan.manifest_id}.yaml"
    archive_target = (iac_root / archive_relative_path).resolve()
    root = iac_root.resolve()
    if not archive_target.is_relative_to(root):
        raise GitOpsCommitError("archive path escaped IaC root")
    if archive_target.exists():
        raise GitOpsCommitError(f"archived VMInstance manifest already exists: {archive_relative_path}")

    manifest = _load_manifest_yaml(active_target.read_text(encoding="utf-8"))
    _validate_vm_manifest(plan, manifest)
    current_status = _manifest_status(manifest)
    if current_status.get("phase") == "applied":
        raise GitOpsCommitError("applied VMInstance manifests cannot be archived from this flow")

    _ensure_clean_repo(iac_root)
    now = _now_utc()
    manifest["status"] = {
        **current_status,
        "phase": "archived",
        "last_error": str(reason or "").strip(),
        "updated_at": now,
        "archived_at": now,
        "archived_by": str(operator_id or plan.job_id).strip(),
    }
    archive_target.parent.mkdir(parents=True, exist_ok=True)
    archive_target.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")
    active_target.unlink()
    _run_git(iac_root, "add", "--", active_relative_path, archive_relative_path)
    _run_git(
        iac_root,
        "commit",
        "-m",
        f"chore: archive VM manifest {plan.manifest_id}",
        "-m",
        f"job_id: {plan.job_id}",
    )
    commit_sha = _run_git(iac_root, "rev-parse", "HEAD")
    return GitOpsCommitResult(
        job_id=plan.job_id,
        manifest_id=plan.manifest_id,
        execution_intent="gitops_archive_only",
        iac_root=str(iac_root),
        manifest_path=archive_relative_path,
        commit_sha=commit_sha,
        apply_enabled=False,
        next_stage="archived",
        side_effects=["iac_manifest_archived", "iac_git_commit_created"],
        manifest_status=_manifest_status(manifest),
    )


def verify_plan_manifest_commit(plan: VmCreatePlan, commit_sha: str) -> str:
    """Verify that an IaC commit contains this plan's VMInstance manifest."""
    commit_sha = str(commit_sha or "").strip()
    if not commit_sha:
        raise GitOpsCommitError("manifest_commit_sha is required before native Proxmox create")

    iac_root = _iac_root_from_plan(plan)

    relative_path, _target = _resolve_manifest_target(iac_root, plan.manifest_id)
    _run_git(iac_root, "cat-file", "-e", f"{commit_sha}^{{commit}}")
    listed = _run_git(iac_root, "ls-tree", "-r", "--name-only", commit_sha, "--", relative_path)
    if relative_path not in listed.splitlines():
        raise GitOpsCommitError(f"commit does not contain expected VMInstance manifest: {relative_path}")
    return relative_path
