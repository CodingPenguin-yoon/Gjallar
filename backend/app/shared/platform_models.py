"""SQLAlchemy models for platform-state persistence."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.platform_db import Base


class PlatformMetadata(Base):
    """Key/value metadata for platform-state migrations and markers."""

    __tablename__ = "platform_metadata"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


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


class OperationalVMState(Base):
    """Latest observed VM state used by read-only operational risk checks."""

    __tablename__ = "operational_vm_state"

    resource_key: Mapped[str] = mapped_column(String(96), primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False, default="qemu")
    node: Mapped[str] = mapped_column(String(128), nullable=False)
    vmid: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    first_seen_at: Mapped[float] = mapped_column(Float, nullable=False)
    last_seen_at: Mapped[float] = mapped_column(Float, nullable=False)
    status_since_at: Mapped[float] = mapped_column(Float, nullable=False)
    last_running_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_observed_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
