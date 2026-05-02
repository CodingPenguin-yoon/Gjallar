"""SQLAlchemy models for platform-state persistence."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.platform_db import Base


class PlatformMetadata(Base):
    """Key/value metadata for platform-state migrations and markers."""

    __tablename__ = "platform_metadata"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class GitLabProject(Base):
    """Persisted GitLab project inventory."""

    __tablename__ = "gitlab_projects"

    gitlab_project_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path_with_namespace: Mapped[str] = mapped_column(String(512), nullable=False)
    web_url: Mapped[str] = mapped_column(Text, nullable=False)
    http_url_to_repo: Mapped[str] = mapped_column(Text, nullable=False)
    ssh_url_to_repo: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="private")
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_activity_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[str] = mapped_column(Text, nullable=False)


class GitLabProjectSettings(Base):
    """Platform-owned per-project settings separate from sync-owned inventory rows."""

    __tablename__ = "gitlab_project_settings"

    gitlab_project_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deployment_environment: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="staging",
    )
    deployment_pool_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_app_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    staging_environment_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="dedicated_vm",
    )
    staging_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ready_for_bootstrap: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    database_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    database_engine: Mapped[str | None] = mapped_column(String(32), nullable=True)
    database_mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    migration_command: Mapped[str | None] = mapped_column(Text, nullable=True)
    deploy_branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")
    bootstrap_strategy: Mapped[str] = mapped_column(String(32), nullable=False, default="merge_request")
    staging_server_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    staging_server_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    staging_template_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    staging_storage_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    staging_network_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    staging_cpu_cores: Mapped[int | None] = mapped_column(Integer, nullable=True)
    staging_memory_gb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    staging_disk_size_gb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    staging_vm_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    staging_vm_gateway: Mapped[str | None] = mapped_column(String(64), nullable=True)
    staging_ansible_packages: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    staging_ansible_roles: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class StagingHost(Base):
    """Registered staging host inventory used for future staging pool placement."""

    __tablename__ = "staging_hosts"
    __table_args__ = (
        UniqueConstraint("node", "vmid", name="uq_staging_hosts_node_vmid"),
        UniqueConstraint("host_ip", name="uq_staging_hosts_host_ip"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    environment: Mapped[str] = mapped_column(String(32), nullable=False, default="staging")
    node: Mapped[str] = mapped_column(String(255), nullable=False)
    vmid: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    host_ip: Mapped[str] = mapped_column(String(64), nullable=False)
    host_user: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pool_key: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="shared")
    bootstrap_status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    drain_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class PostgresConnectionResource(Base):
    """Platform-side metadata for future Postgres connection provisioning."""

    __tablename__ = "postgres_connection_resources"
    __table_args__ = (
        UniqueConstraint(
            "gitlab_project_id",
            "environment",
            name="uq_postgres_connection_resources_project_environment",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gitlab_project_id: Mapped[int] = mapped_column(
        ForeignKey("gitlab_projects.gitlab_project_id", ondelete="CASCADE"),
        nullable=False,
    )
    environment: Mapped[str] = mapped_column(String(32), nullable=False, default="staging")
    resource_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="database")
    database_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    schema_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    connection_env: Mapped[str] = mapped_column(String(128), nullable=False, default="DATABASE_URL")
    provision_status: Mapped[str] = mapped_column(String(32), nullable=False, default="planned")
    provisioning_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class PlatformTask(Base):
    """Persisted task summary."""

    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    progress_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    progress_source: Mapped[str] = mapped_column(Text, nullable=False, default="")
    archived: Mapped[bool] = mapped_column(nullable=False, default=False)
    archived_at: Mapped[str | None] = mapped_column(Text, nullable=True)

    logs: Mapped[list["PlatformTaskLog"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PlatformTaskLog.line_no",
    )


class PlatformTaskLog(Base):
    """Persisted task log line."""

    __tablename__ = "task_logs"

    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.task_id", ondelete="CASCADE"),
        primary_key=True,
    )
    line_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    log_line: Mapped[str] = mapped_column(Text, nullable=False)

    task: Mapped[PlatformTask] = relationship(back_populates="logs")
