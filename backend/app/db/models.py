"""SQLAlchemy models for Gjallar DB-backed runtime state."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CreateVmProfile(Base):
    """DB row for a Create VM profile preset."""

    __tablename__ = "create_vm_profiles"

    profile_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name_ko: Mapped[str] = mapped_column(String(160), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    cpu_default: Mapped[int] = mapped_column(Integer, nullable=False)
    cpu_min: Mapped[int] = mapped_column(Integer, nullable=False)
    cpu_max: Mapped[int] = mapped_column(Integer, nullable=False)
    memory_mb_default: Mapped[int] = mapped_column(Integer, nullable=False)
    memory_mb_min: Mapped[int] = mapped_column(Integer, nullable=False)
    memory_mb_max: Mapped[int] = mapped_column(Integer, nullable=False)
    disk_gb_default: Mapped[int] = mapped_column(Integer, nullable=False)
    disk_gb_min: Mapped[int] = mapped_column(Integer, nullable=False)
    disk_gb_max: Mapped[int] = mapped_column(Integer, nullable=False)

    default_user: Mapped[str] = mapped_column(String(80), nullable=False)
    require_ssh_key: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_password_login: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_user_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ssh_key_source: Mapped[str] = mapped_column(String(120), nullable=False)

    require_cloud_init: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    require_qemu_guest_agent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    source: Mapped[str] = mapped_column(String(80), nullable=False, default="db_seed")
    management: Mapped[str] = mapped_column(String(80), nullable=False, default="read_only")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserRecord(Base):
    """Local Gjallar user for session-backed console authentication."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("username", name="uq_users_username"),)

    user_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    username: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SessionRecord(Base):
    """Server-side session record keyed by a hash of the opaque cookie token."""

    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), nullable=False, index=True)
    session_token_hash: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)


class AccountAuditEventRecord(Base):
    """Sanitized local audit evidence for account and session operations."""

    __tablename__ = "account_audit_events"
    __table_args__ = (
        Index("ix_account_audit_events_actor_created", "actor_user_id", "created_at"),
        Index("ix_account_audit_events_target_user_created", "target_user_id", "created_at"),
        Index("ix_account_audit_events_target_session_created", "target_session_id", "created_at"),
        Index("ix_account_audit_events_operation_created", "operation", "created_at"),
    )

    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    actor_username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_user_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target_username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target_session_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class JobRunRecord(Base):
    """DB-backed latest state for operator-visible jobs."""

    __tablename__ = "job_runs"

    job_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str] = mapped_column(String(240), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False)
    started_at: Mapped[str] = mapped_column(String(80), nullable=False)
    finished_at: Mapped[str | None] = mapped_column(String(80), nullable=True)
    current_stage: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    risks: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    artifact_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class JobArtifactRecord(Base):
    """DB-backed artifact payload and metadata for one job."""

    __tablename__ = "job_artifacts"

    artifact_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(120), nullable=False)
    path: Mapped[str] = mapped_column(String(320), nullable=False)
    checksum: Mapped[str] = mapped_column(String(80), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_backend: Mapped[str] = mapped_column(String(40), nullable=False, default="db")
    created_at: Mapped[str] = mapped_column(String(80), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(80), nullable=False)


class VmCreateRequestRecord(Base):
    """DB record for a Create VM request and its final result summary."""

    __tablename__ = "vm_create_requests"

    request_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    draft_id: Mapped[str] = mapped_column(String(160), nullable=False)
    manifest_id: Mapped[str] = mapped_column(String(160), nullable=False)
    operator_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(80), nullable=False)
    target_node_id: Mapped[str] = mapped_column(String(120), nullable=False)
    vmid: Mapped[int] = mapped_column(Integer, nullable=False)
    vm_name: Mapped[str] = mapped_column(String(240), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(120), nullable=False)
    template_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    storage_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    actor_user_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    actor_username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(40), nullable=True)
    request_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    approval: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[str] = mapped_column(String(80), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(80), nullable=False)


class VmInstanceRecord(Base):
    """DB-backed Gjallar view of a VM created through Create VM."""

    __tablename__ = "vm_instances"
    __table_args__ = (UniqueConstraint("node_id", "vmid", name="uq_vm_instances_node_vmid"),)

    vm_instance_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(120), nullable=False)
    vmid: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(80), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(120), nullable=False)
    template_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    storage_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    cpu: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    memory_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    disk_gb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    network: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    access: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    observed_after: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    create_job_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    created_at: Mapped[str] = mapped_column(String(80), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(80), nullable=False)


class OperationLockRecord(Base):
    """Durable target coordination state for verified operations."""

    __tablename__ = "operation_locks"
    __table_args__ = (
        CheckConstraint(
            "operation_type in ('vm_start', 'vm_create', 'guided_qm_vm_unlock', 'vm_shutdown', 'vm_compute', 'vm_disk_resize', 'vm_network', 'vm_clone', 'vm_delete', 'vm_template', 'vm_image_build', 'vm_image_cleanup', 'vm_backup', 'vm_restore', 'vm_migrate', 'host_storage', 'host_network')",
            name="ck_operation_locks_operation_type",
        ),
        CheckConstraint(
            "scope_type in ('proxmox_locator', 'proxmox_configuration')",
            name="ck_operation_locks_scope_type",
        ),
        CheckConstraint(
            "status in ('active', 'released', 'stale', 'reconciliation_required')",
            name="ck_operation_locks_status",
        ),
        CheckConstraint(
            "(scope_type = 'proxmox_configuration' and operation_type in ('host_storage', 'host_network') and vmid is null) "
            "or (scope_type = 'proxmox_locator' and operation_type not in ('host_storage', 'host_network'))",
            name="ck_operation_locks_host_binding",
        ),
        Index(
            "uq_operation_locks_open_configuration", "scope_type", "scope_key", unique=True,
            sqlite_where=text("scope_type = 'proxmox_configuration' and status in ('active', 'stale', 'reconciliation_required')"),
            postgresql_where=text("scope_type = 'proxmox_configuration' and status in ('active', 'stale', 'reconciliation_required')"),
        ),
        Index("ix_operation_locks_scope_status", "operation_type", "scope_type", "scope_key", "status"),
        Index("ix_operation_locks_expires_at", "expires_at"),
        Index(
            "uq_operation_locks_open_locator",
            "scope_type",
            "scope_key",
            unique=True,
            sqlite_where=text(
                "scope_type = 'proxmox_locator' and status in ('active', 'stale', 'reconciliation_required')"
            ),
            postgresql_where=text(
                "scope_type = 'proxmox_locator' and status in ('active', 'stale', 'reconciliation_required')"
            ),
        ),
    )

    operation_lock_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    operation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(40), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    cluster_id: Mapped[str] = mapped_column(String(120), nullable=False)
    vmid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
