"""Create-VM draft helpers for the PRD-locked general-vm MVP profile."""

from __future__ import annotations

import re

from app.manifests.loader import load_builtin_network_profiles, load_builtin_profiles
from app.vm_create.models import (
    CreateProfileOption,
    DraftAccess,
    DraftHardware,
    DraftNetwork,
    VmCreateDraft,
)
from app.vm_create.paths import terraform_state_path


def _safe_identifier(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
    return safe or "draft"


def _load_general_profile():
    profiles = {profile.profile_id: profile for profile in load_builtin_profiles()}
    profile = profiles.get("general-vm")
    if profile is None or not profile.create_enabled:
        raise ValueError("general-vm profile must exist and be create-enabled for the MVP")
    return profile


def _load_network(network_id: str):
    networks = {network.network_id: network for network in load_builtin_network_profiles()}
    try:
        return networks[network_id]
    except KeyError as exc:
        raise ValueError(f"NetworkProfile {network_id!r} is not available") from exc


def list_create_profile_options() -> list[CreateProfileOption]:
    """Return profiles visible to the Create VM wizard.

    Only general-vm is create-enabled in the first MVP. Future profile candidates
    can be displayed/read but cannot be executed.
    """
    return [
        CreateProfileOption(
            profile_id=profile.profile_id,
            display_name=profile.display_name,
            create_enabled=profile.create_enabled,
        )
        for profile in load_builtin_profiles()
    ]


def build_default_vm_draft(
    *,
    operator_id: str,
    job_id: str = "job-draft-preview",
    target_node_id: str | None = None,
    static_ip: str | None = None,
    ip_mode: str | None = None,
) -> VmCreateDraft:
    """Build a non-mutating default draft for the first MVP Create VM flow."""
    profile = _load_general_profile()
    network_profile = _load_network(profile.network.network_profile)
    chosen_node = target_node_id or profile.target_node_candidates[0]
    bridge_id = network_profile.node_bridges.get(chosen_node)
    requested_ip_mode = ip_mode or profile.network.default_ip_mode
    if requested_ip_mode not in {"static", "dhcp"}:
        raise ValueError("ip_mode must be either 'static' or 'dhcp'")
    resolved_static_ip = None if requested_ip_mode == "dhcp" else static_ip or "192.168.2.142"
    suffix = _safe_identifier(job_id)
    manifest_id = f"vm-{suffix}"
    draft_id = f"draft-{suffix}"
    return VmCreateDraft(
        draft_id=draft_id,
        job_id=job_id,
        operator_id=operator_id,
        profile_id=profile.profile_id,
        manifest_id=manifest_id,
        vm_name=f"gjallar-vm-{suffix}",
        proposed_vmid=102,
        target_node_id=chosen_node,
        template_family=profile.template_family,
        hardware=DraftHardware(
            cpu=profile.hardware.cpu,
            memory_mb=profile.hardware.memory_mb,
            disk_gb=profile.hardware.disk_gb,
        ),
        network=DraftNetwork(
            network_id=network_profile.network_id,
            ip_mode=requested_ip_mode,
            static_ip=resolved_static_ip,
            bridge_id=bridge_id,
        ),
        access=DraftAccess(
            cloud_init_user=profile.access.cloud_init_user,
            ssh_key_source=profile.access.ssh_key_source,
            password_login=profile.access.password_login,
        ),
        terraform_state_path=terraform_state_path(manifest_id),
        first_power_on_included=True,
    )
