"""Dataclass models for Set 6 VM create draft/preflight/plan flow."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.jobs.models import ArtifactRecord


@dataclass(frozen=True)
class DraftHardware:
    cpu: int
    memory_mb: int
    disk_gb: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DraftAccess:
    cloud_init_user: str
    ssh_key_source: str
    password_login: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DraftNetwork:
    network_id: str
    ip_mode: str
    static_ip: str | None = None
    prefix: int | str | None = None
    gateway: str | None = None
    bridge_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VmCreateDraft:
    draft_id: str
    job_id: str
    operator_id: str
    profile_id: str
    manifest_id: str
    vm_name: str
    proposed_vmid: int
    target_node_id: str
    storage_id: str | None
    template_family: str
    template_id: str | None
    template_vmid: int | None
    template_node_id: str | None
    hardware: DraftHardware
    network: DraftNetwork
    access: DraftAccess
    terraform_state_path: str
    first_power_on_included: bool = False
    side_effects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "job_id": self.job_id,
            "operator_id": self.operator_id,
            "profile_id": self.profile_id,
            "manifest_id": self.manifest_id,
            "vm_name": self.vm_name,
            "proposed_vmid": self.proposed_vmid,
            "target_node_id": self.target_node_id,
            "storage_id": self.storage_id,
            "template_family": self.template_family,
            "template_id": self.template_id,
            "template_vmid": self.template_vmid,
            "template_node_id": self.template_node_id,
            "hardware": self.hardware.to_dict(),
            "network": self.network.to_dict(),
            "access": self.access.to_dict(),
            "terraform_state_path": self.terraform_state_path,
            "first_power_on_included": self.first_power_on_included,
            "side_effects": list(self.side_effects),
        }


@dataclass(frozen=True)
class CreateProfileOption:
    profile_id: str
    display_name: str
    create_enabled: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RiskItem:
    level: str
    code: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PreflightCheck:
    code: str
    status: str
    level: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PreflightResult:
    draft_id: str
    inventory_source: str
    risk_level: str
    checks: list[PreflightCheck]
    risks: list[RiskItem]
    selected_storage_id: str | None
    selected_template_id: str | None
    selected_template_vmid: int | None
    selected_template_node_id: str | None
    selected_bridge_id: str | None
    iac_root: str
    terraform_state_root: str
    iac_ready_for_plan: bool
    iac_ready_for_execute: bool
    side_effects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "inventory_source": self.inventory_source,
            "risk_level": self.risk_level,
            "checks": [check.to_dict() for check in self.checks],
            "risks": [risk.to_dict() for risk in self.risks],
            "selected_storage_id": self.selected_storage_id,
            "selected_template_id": self.selected_template_id,
            "selected_template_vmid": self.selected_template_vmid,
            "selected_template_node_id": self.selected_template_node_id,
            "selected_bridge_id": self.selected_bridge_id,
            "iac_root": self.iac_root,
            "terraform_state_root": self.terraform_state_root,
            "iac_ready_for_plan": self.iac_ready_for_plan,
            "iac_ready_for_execute": self.iac_ready_for_execute,
            "side_effects": list(self.side_effects),
        }


@dataclass(frozen=True)
class IacReadinessResult:
    shared_root: str
    iac_root: str
    terraform_state_root: str
    risk_level: str
    ready_for_plan: bool
    ready_for_execute: bool
    checks: list[PreflightCheck]
    risks: list[RiskItem]
    side_effects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "shared_root": self.shared_root,
            "iac_root": self.iac_root,
            "terraform_state_root": self.terraform_state_root,
            "risk_level": self.risk_level,
            "ready_for_plan": self.ready_for_plan,
            "ready_for_execute": self.ready_for_execute,
            "checks": [check.to_dict() for check in self.checks],
            "risks": [risk.to_dict() for risk in self.risks],
            "side_effects": list(self.side_effects),
        }


@dataclass(frozen=True)
class VmCreatePlan:
    draft_id: str
    job_id: str
    manifest_id: str
    execution_intent: str
    vm_name: str
    vmid: int
    target_node_id: str
    storage_id: str
    template_id: str
    hardware: dict[str, int]
    network: dict[str, Any]
    terraform_state_path: str
    first_power_on_included: bool
    smoke_timeout_summary: dict[str, int]
    risk_summary: dict[str, Any]
    review_confirm: dict[str, Any]
    artifacts: list[ArtifactRecord]
    side_effects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "job_id": self.job_id,
            "manifest_id": self.manifest_id,
            "execution_intent": self.execution_intent,
            "vm_name": self.vm_name,
            "vmid": self.vmid,
            "target_node_id": self.target_node_id,
            "storage_id": self.storage_id,
            "template_id": self.template_id,
            "hardware": dict(self.hardware),
            "network": dict(self.network),
            "terraform_state_path": self.terraform_state_path,
            "first_power_on_included": self.first_power_on_included,
            "smoke_timeout_summary": dict(self.smoke_timeout_summary),
            "risk_summary": dict(self.risk_summary),
            "review_confirm": dict(self.review_confirm),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "side_effects": list(self.side_effects),
        }


@dataclass(frozen=True)
class GitOpsCommitResult:
    job_id: str
    manifest_id: str
    execution_intent: str
    iac_root: str
    manifest_path: str
    commit_sha: str
    apply_enabled: bool
    next_stage: str
    side_effects: list[str] = field(default_factory=list)
    manifest_status: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TerraformWorkspaceResult:
    job_id: str
    manifest_id: str
    workspace_dir: str
    terraform_dir: str
    backend_config_path: str
    tfvars_path: str
    plan_path: str
    state_path: str
    side_effects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
