"""DB-backed repository for Create VM profile presets."""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.db.models import CreateVmProfile
from app.db.session import session_scope
from app.manifests.models import (
    AccessDefaults,
    HardwareLimit,
    ProfileHardware,
    TemplateRequirements,
    VmProfile,
)

_MVP_TARGET_NODES = ("yoonmanserver2", "yoonmanserver3")
_TRANSITIONAL_TEMPLATE_FAMILY = "ubuntu"
_TRANSITIONAL_DEFAULT_IP_MODE = "static"


def _active_profiles_statement() -> Select[tuple[CreateVmProfile]]:
    return (
        select(CreateVmProfile)
        .where(
            CreateVmProfile.enabled.is_(True),
            CreateVmProfile.disabled_at.is_(None),
            CreateVmProfile.archived_at.is_(None),
        )
        .order_by(CreateVmProfile.sort_order.asc(), CreateVmProfile.profile_id.asc())
    )


def _profile_from_row(row: CreateVmProfile) -> VmProfile:
    return VmProfile(
        profile_id=row.profile_id,
        display_name=row.display_name,
        display_name_ko=row.display_name_ko,
        enabled=bool(row.enabled),
        hardware=ProfileHardware(
            cpu=HardwareLimit(default=row.cpu_default, min=row.cpu_min, max=row.cpu_max),
            memory_mb=HardwareLimit(
                default=row.memory_mb_default,
                min=row.memory_mb_min,
                max=row.memory_mb_max,
            ),
            disk_gb=HardwareLimit(default=row.disk_gb_default, min=row.disk_gb_min, max=row.disk_gb_max),
        ),
        access=AccessDefaults(
            default_user=row.default_user,
            require_ssh_key=bool(row.require_ssh_key),
            allow_password_login=bool(row.allow_password_login),
            allow_user_override=bool(row.allow_user_override),
            ssh_key_source=row.ssh_key_source,
        ),
        template_requirements=TemplateRequirements(
            require_cloud_init=bool(row.require_cloud_init),
            require_qemu_guest_agent=bool(row.require_qemu_guest_agent),
        ),
        source=row.source,
        management=row.management,
        target_node_candidates=_MVP_TARGET_NODES,
        template_family=_TRANSITIONAL_TEMPLATE_FAMILY,
        default_ip_mode=_TRANSITIONAL_DEFAULT_IP_MODE,
    )


def _list_active_with_session(session: Session) -> list[VmProfile]:
    rows = session.scalars(_active_profiles_statement()).all()
    return [_profile_from_row(row) for row in rows]


def list_active_create_vm_profiles(session: Session | None = None) -> list[VmProfile]:
    """Return active Create VM profiles visible to draft/preflight/API flows."""
    if session is not None:
        return _list_active_with_session(session)
    with session_scope() as scoped_session:
        return _list_active_with_session(scoped_session)


def get_active_create_vm_profiles_by_id(session: Session | None = None) -> dict[str, VmProfile]:
    """Return active Create VM profiles keyed by profile id."""
    return {profile.profile_id: profile for profile in list_active_create_vm_profiles(session)}


def count_create_vm_profiles(session: Session | None = None) -> int:
    """Return the total number of profile rows, including disabled/archived rows."""
    if session is not None:
        return int(session.scalar(select(func.count()).select_from(CreateVmProfile)) or 0)
    with session_scope() as scoped_session:
        return count_create_vm_profiles(scoped_session)


def profile_rows_from_seed_definitions(profiles: Iterable[VmProfile]) -> list[CreateVmProfile]:
    """Convert seed definition dataclasses into DB rows."""
    rows: list[CreateVmProfile] = []
    for index, profile in enumerate(profiles, start=1):
        rows.append(
            CreateVmProfile(
                profile_id=profile.profile_id,
                sort_order=index * 10,
                display_name=profile.display_name,
                display_name_ko=profile.display_name_ko,
                enabled=bool(profile.enabled),
                cpu_default=profile.hardware.cpu.default,
                cpu_min=profile.hardware.cpu.min,
                cpu_max=profile.hardware.cpu.max,
                memory_mb_default=profile.hardware.memory_mb.default,
                memory_mb_min=profile.hardware.memory_mb.min,
                memory_mb_max=profile.hardware.memory_mb.max,
                disk_gb_default=profile.hardware.disk_gb.default,
                disk_gb_min=profile.hardware.disk_gb.min,
                disk_gb_max=profile.hardware.disk_gb.max,
                default_user=profile.access.default_user,
                require_ssh_key=profile.access.require_ssh_key,
                allow_password_login=profile.access.allow_password_login,
                allow_user_override=profile.access.allow_user_override,
                ssh_key_source=profile.access.ssh_key_source,
                require_cloud_init=profile.template_requirements.require_cloud_init,
                require_qemu_guest_agent=profile.template_requirements.require_qemu_guest_agent,
                source="db_seed",
                management=profile.management,
            )
        )
    return rows
