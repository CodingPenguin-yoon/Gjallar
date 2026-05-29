"""SQLAlchemy models for Gjallar DB-backed runtime state."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for Alembic metadata discovery."""


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


class VmIdentityRecord(Base):
    """Long-lived DRS identity for one observed Proxmox VM."""

    __tablename__ = "vm_identities"
    __table_args__ = (
        UniqueConstraint("cluster_id", "stable_fingerprint", name="uq_vm_identities_cluster_fingerprint"),
        CheckConstraint(
            "identity_status in ('active', 'uncertain', 'retired')",
            name="ck_vm_identities_identity_status",
        ),
    )

    vm_identity_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    cluster_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    stable_fingerprint: Mapped[str] = mapped_column(String(96), nullable=False)
    identity_status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class VmIdentityObservationRecord(Base):
    """Compact read-only Proxmox VM identity observation."""

    __tablename__ = "vm_identity_observations"
    __table_args__ = (
        CheckConstraint(
            "match_confidence in ('high', 'medium', 'low', 'unknown')",
            name="ck_vm_identity_observations_match_confidence",
        ),
        Index("ix_vm_identity_observations_identity_seen", "vm_identity_id", "observed_at"),
        Index("ix_vm_identity_observations_locator", "cluster_id", "node_id", "vmid"),
        Index("ix_vm_identity_observations_fingerprint", "cluster_id", "fingerprint_hash"),
    )

    observation_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    vm_identity_id: Mapped[str] = mapped_column(ForeignKey("vm_identities.vm_identity_id"), nullable=False, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cluster_id: Mapped[str] = mapped_column(String(120), nullable=False)
    node_id: Mapped[str] = mapped_column(String(120), nullable=False)
    vmid: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    power_state: Mapped[str] = mapped_column(String(80), nullable=False)
    template: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fingerprint_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    fingerprint_components: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    match_confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    match_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(80), nullable=False)


class VmMigrationPolicyRecord(Base):
    """Operator DRS migration policy for one VM identity."""

    __tablename__ = "vm_migration_policies"
    __table_args__ = (
        UniqueConstraint("vm_identity_id", name="uq_vm_migration_policies_vm_identity_id"),
        CheckConstraint(
            "policy in ('unknown', 'allowed', 'restricted', 'blocked')",
            name="ck_vm_migration_policies_policy",
        ),
        CheckConstraint(
            "source in ('default', 'manual', 'tag', 'imported')",
            name="ck_vm_migration_policies_source",
        ),
    )

    policy_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    vm_identity_id: Mapped[str] = mapped_column(ForeignKey("vm_identities.vm_identity_id"), nullable=False, index=True)
    policy: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="default")
    updated_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class OperationLockRecord(Base):
    """Local DRS operation lock state for future migration execution gates."""

    __tablename__ = "operation_locks"
    __table_args__ = (
        CheckConstraint(
            "operation_type in ('drs_migration')",
            name="ck_operation_locks_operation_type",
        ),
        CheckConstraint(
            "scope_type in ('vm_identity', 'proxmox_locator', 'route')",
            name="ck_operation_locks_scope_type",
        ),
        CheckConstraint(
            "status in ('active', 'released', 'stale', 'reconciliation_required')",
            name="ck_operation_locks_status",
        ),
        Index("ix_operation_locks_scope_status", "operation_type", "scope_type", "scope_key", "status"),
        Index("ix_operation_locks_cluster_identity_status", "cluster_id", "vm_identity_id", "status"),
        Index("ix_operation_locks_locator_status", "cluster_id", "source_node_id", "vmid", "status"),
        Index("ix_operation_locks_route_status", "cluster_id", "source_node_id", "target_node_id", "status"),
        Index("ix_operation_locks_expires_at", "expires_at"),
    )

    operation_lock_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    operation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(40), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    cluster_id: Mapped[str] = mapped_column(String(120), nullable=False)
    vm_identity_id: Mapped[str | None] = mapped_column(ForeignKey("vm_identities.vm_identity_id"), nullable=True)
    vmid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_node_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    target_node_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
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


class DrsApprovalPacketRecord(Base):
    """Local DRS approval packet bound to recommendation and pre-check evidence."""

    __tablename__ = "drs_approval_packets"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_drs_approval_packets_job_id"),
        CheckConstraint(
            "packet_status in ('approved', 'blocked')",
            name="ck_drs_approval_packets_packet_status",
        ),
        Index("ix_drs_approval_packets_recommendation", "recommendation_id", "created_at"),
        Index("ix_drs_approval_packets_identity", "vm_identity_id", "created_at"),
        Index("ix_drs_approval_packets_route", "cluster_id", "source_node_id", "target_node_id", "created_at"),
    )

    approval_packet_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    packet_status: Mapped[str] = mapped_column(String(40), nullable=False)
    job_id: Mapped[str] = mapped_column(String(160), nullable=False)
    recommendation_id: Mapped[str] = mapped_column(String(240), nullable=False)
    cluster_id: Mapped[str] = mapped_column(String(120), nullable=False)
    vm_identity_id: Mapped[str] = mapped_column(ForeignKey("vm_identities.vm_identity_id"), nullable=False, index=True)
    vmid: Mapped[int] = mapped_column(Integer, nullable=False)
    vm_name: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    source_node_id: Mapped[str] = mapped_column(String(120), nullable=False)
    target_node_id: Mapped[str] = mapped_column(String(120), nullable=False)
    actor_user_id: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_username: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(40), nullable=False)
    warning_acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    warning_codes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    recommendation_checksum: Mapped[str] = mapped_column(String(80), nullable=False)
    final_precheck_checksum: Mapped[str] = mapped_column(String(80), nullable=False)
    approval_packet_checksum: Mapped[str] = mapped_column(String(80), nullable=False)
    recommendation_artifact_id: Mapped[str] = mapped_column(String(240), nullable=False)
    final_precheck_artifact_id: Mapped[str] = mapped_column(String(240), nullable=False)
    approval_artifact_id: Mapped[str] = mapped_column(String(240), nullable=False)
    final_precheck_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    lock_evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class DrsMigrationJobRecord(Base):
    """Local non-runnable DRS migration job intent substrate."""

    __tablename__ = "drs_migration_jobs"
    __table_args__ = (
        UniqueConstraint("approval_packet_id", name="uq_drs_migration_jobs_approval_packet_id"),
        CheckConstraint(
            "status in ('pending', 'blocked', 'cancelled')",
            name="ck_drs_migration_jobs_status",
        ),
        Index("ix_drs_migration_jobs_recommendation", "recommendation_id", "created_at"),
        Index("ix_drs_migration_jobs_identity_status", "vm_identity_id", "status"),
        Index("ix_drs_migration_jobs_route_status", "cluster_id", "source_node_id", "target_node_id", "status"),
    )

    job_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    approval_packet_id: Mapped[str] = mapped_column(
        ForeignKey("drs_approval_packets.approval_packet_id"),
        nullable=False,
        index=True,
    )
    recommendation_id: Mapped[str] = mapped_column(String(240), nullable=False)
    cluster_id: Mapped[str] = mapped_column(String(120), nullable=False)
    vm_identity_id: Mapped[str] = mapped_column(ForeignKey("vm_identities.vm_identity_id"), nullable=False, index=True)
    vmid: Mapped[int] = mapped_column(Integer, nullable=False)
    source_node_id: Mapped[str] = mapped_column(String(120), nullable=False)
    target_node_id: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    runnable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    proxmox_mutation_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    side_effects: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    runnable_blockers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    final_precheck_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    lock_evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    approved_actor: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    job_intent_artifact_id: Mapped[str] = mapped_column(String(240), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
