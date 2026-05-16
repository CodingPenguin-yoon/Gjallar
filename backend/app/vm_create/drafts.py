"""Create-VM draft helpers for DB-backed Create VM profiles."""

from __future__ import annotations

import re

from app.db.create_vm_profiles import get_active_create_vm_profiles_by_id, list_active_create_vm_profiles
from app.vm_create.access import resolve_ssh_public_key
from app.vm_create.models import (
    CreateProfileOption,
    DraftAccess,
    DraftHardware,
    DraftNetwork,
    VmCreateDraft,
)

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


def _optional_bool(value: object) -> bool | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return bool(value)


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


def _alias_value(values: dict, *keys: str):
    for key in keys:
        if key in values:
            return values.get(key)
    return None


def _profiles_by_id():
    return get_active_create_vm_profiles_by_id()


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
    """Return the active profile list visible to the Create VM wizard."""
    return [CreateProfileOption(**profile.to_dict()) for profile in list_active_create_vm_profiles()]


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
    access_overrides: dict | None = None,
    cloud_init_user: str | None = None,
    username: str | None = None,
    ssh_public_key: str | None = None,
    password_login: object | None = None,
) -> VmCreateDraft:
    """Build a non-mutating default draft for the Create VM flow."""
    requested_profile_id, profile = _profile_for_draft_defaults(profile_id)
    hardware_override_values = dict(hardware_overrides or {})
    access_override_values = dict(access_overrides or {})
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
    requested_user = (
        _optional_text(_alias_value(access_override_values, "cloud_init_user", "cloudInitUser", "username", "user"))
        or _optional_text(cloud_init_user)
        or _optional_text(username)
        or profile.access.cloud_init_user
    )
    requested_password_login = _optional_bool(
        _alias_value(access_override_values, "password_login", "passwordLogin")
    )
    if requested_password_login is None:
        requested_password_login = _optional_bool(password_login)
    if requested_password_login is None:
        requested_password_login = profile.access.password_login
    resolved_password_login = bool(requested_password_login) if profile.access.allow_password_login else False
    requested_ssh_public_key = (
        _optional_text(_alias_value(access_override_values, "ssh_public_key", "sshPublicKey", "public_key", "publicKey"))
        or _optional_text(ssh_public_key)
    )
    resolved_ssh_key = resolve_ssh_public_key(requested_ssh_public_key)
    ssh_validation = resolved_ssh_key.validation
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
            cloud_init_user=requested_user,
            ssh_key_source=resolved_ssh_key.source,
            password_login=resolved_password_login,
            ssh_key_present=ssh_validation.supplied,
            ssh_key_valid=ssh_validation.valid,
            ssh_key_fingerprint=ssh_validation.fingerprint,
            ssh_key_validation_error=ssh_validation.error_code,
            _transient_ssh_public_key=resolved_ssh_key.transient_public_key,
        ),
        first_power_on_included=False,
    )
