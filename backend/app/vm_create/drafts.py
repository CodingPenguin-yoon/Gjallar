"""Create-VM draft helpers for the static Create VM profiles."""

from __future__ import annotations

import re

from app.manifests.loader import load_builtin_profiles
from app.vm_create.models import (
    CreateProfileOption,
    DraftAccess,
    DraftHardware,
    DraftNetwork,
    VmCreateDraft,
)
from app.vm_create.paths import terraform_state_path

DEFAULT_PROFILE_ID = "general-vm"


def _safe_identifier(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
    return safe or "draft"


def _optional_int(value: object) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(value)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_prefix(value: object) -> int | str | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    try:
        return int(text)
    except ValueError:
        return text


def _hardware_value(overrides: dict, key: str, default: int) -> int:
    aliases = {"memory_mb": "memoryMb", "disk_gb": "diskGb"}
    raw_value = overrides.get(key)
    if raw_value is None and key in aliases:
        raw_value = overrides.get(aliases[key])
    value = _optional_int(raw_value)
    return value if value is not None else default


def _profiles_by_id():
    profiles = {profile.profile_id: profile for profile in load_builtin_profiles()}
    return profiles


def _load_general_profile():
    profiles = _profiles_by_id()
    profile = profiles.get(DEFAULT_PROFILE_ID)
    if profile is None or not profile.create_enabled:
        raise ValueError("general-vm profile must exist and be create-enabled")
    return profile


def _profile_for_draft_defaults(profile_id: str | None):
    requested_profile_id = _optional_text(profile_id) or DEFAULT_PROFILE_ID
    profiles = _profiles_by_id()
    return requested_profile_id, profiles.get(requested_profile_id) or _load_general_profile()


def list_create_profile_options() -> list[CreateProfileOption]:
    """Return the read-only profile list visible to the Create VM wizard."""
    return [CreateProfileOption(**profile.to_dict()) for profile in load_builtin_profiles()]


def build_default_vm_draft(
    *,
    operator_id: str,
    job_id: str = "job-draft-preview",
    profile_id: str | None = None,
    target_node_id: str | None = None,
    storage_id: str | None = None,
    network_id: str | None = None,
    bridge_id: str | None = None,
    static_ip: str | None = None,
    prefix: object | None = None,
    gateway: str | None = None,
    ip_mode: str | None = None,
    proposed_vmid: int | None = None,
    template_id: str | None = None,
    template_vmid: int | None = None,
    template_node_id: str | None = None,
    hardware_overrides: dict | None = None,
) -> VmCreateDraft:
    """Build a non-mutating default draft for the Create VM flow."""
    requested_profile_id, profile = _profile_for_draft_defaults(profile_id)
    hardware_override_values = dict(hardware_overrides or {})
    chosen_node = target_node_id or profile.target_node_candidates[0]
    selected_bridge_id = _optional_text(bridge_id)
    requested_ip_mode = ip_mode or profile.default_ip_mode
    if requested_ip_mode not in {"static", "dhcp"}:
        raise ValueError("ip_mode must be either 'static' or 'dhcp'")
    resolved_static_ip = None if requested_ip_mode == "dhcp" else _optional_text(static_ip)
    resolved_prefix = None if requested_ip_mode == "dhcp" else _optional_prefix(prefix)
    resolved_gateway = None if requested_ip_mode == "dhcp" else _optional_text(gateway)
    suffix = _safe_identifier(job_id)
    manifest_id = f"vm-{suffix}"
    draft_id = f"draft-{suffix}"
    return VmCreateDraft(
        draft_id=draft_id,
        job_id=job_id,
        operator_id=operator_id,
        profile_id=requested_profile_id,
        manifest_id=manifest_id,
        vm_name=f"gjallar-vm-{suffix}",
        proposed_vmid=int(proposed_vmid or 102),
        target_node_id=chosen_node,
        storage_id=str(storage_id).strip() if storage_id else None,
        template_family=profile.template_family,
        template_id=template_id,
        template_vmid=_optional_int(template_vmid),
        template_node_id=template_node_id,
        hardware=DraftHardware(
            cpu=_hardware_value(hardware_override_values, "cpu", profile.hardware.cpu.default),
            memory_mb=_hardware_value(
                hardware_override_values,
                "memory_mb",
                profile.hardware.memory_mb.default,
            ),
            disk_gb=_hardware_value(hardware_override_values, "disk_gb", profile.hardware.disk_gb.default),
        ),
        network=DraftNetwork(
            ip_mode=requested_ip_mode,
            static_ip=resolved_static_ip,
            prefix=resolved_prefix,
            gateway=resolved_gateway,
            bridge_id=selected_bridge_id,
        ),
        access=DraftAccess(
            cloud_init_user=profile.access.cloud_init_user,
            ssh_key_source=profile.access.ssh_key_source,
            password_login=profile.access.password_login,
        ),
        terraform_state_path=terraform_state_path(manifest_id),
        first_power_on_included=False,
    )
