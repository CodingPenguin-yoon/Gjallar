"""SQLAlchemy persistence models owned by Operations and Evidence/Audit."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OperationRecord(Base):
    """Current projection for one managed, manual, or observe-only operation."""

    __tablename__ = "operations"
    __table_args__ = (
        UniqueConstraint(
            "operation_type",
            "target_type",
            "target_id",
            "idempotency_key",
            name="uq_operations_scoped_idempotency",
        ),
        CheckConstraint(
            "execution_mode in ('managed_api', 'guided_manual', 'observe_only')",
            name="ck_operations_execution_mode",
        ),
        CheckConstraint(
            "status in ('draft', 'planned', 'awaiting_approval', 'approved', 'dispatching', 'running', "
            "'awaiting_operator', 'awaiting_verification', 'verifying', 'succeeded', 'blocked', 'rejected', "
            "'expired', 'failed', 'needs_reconciliation', 'cancelled')",
            name="ck_operations_status",
        ),
        Index("ix_operations_status_updated", "status", "updated_at"),
        Index("ix_operations_target_status", "target_type", "target_id", "status"),
        Index("ix_operations_actor_created", "actor_user_id", "created_at"),
    )

    operation_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    operation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str] = mapped_column(String(240), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    intent_digest: Mapped[str] = mapped_column(String(80), nullable=False)
    plan_digest: Mapped[str] = mapped_column(String(80), nullable=False)
    current_stage: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    actor_username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(40), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_event_checksum: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class OperationEventRecord(Base):
    """Append-only, checksum-linked evidence event for an operation."""

    __tablename__ = "operation_events"
    __table_args__ = (
        UniqueConstraint("operation_id", "sequence", name="uq_operation_events_operation_sequence"),
        Index("ix_operation_events_operation_created", "operation_id", "created_at"),
        Index("ix_operation_events_type_created", "event_type", "created_at"),
    )

    event_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    operation_id: Mapped[str] = mapped_column(ForeignKey("operations.operation_id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_status: Mapped[str] = mapped_column(String(40), nullable=False)
    stage: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    actor_username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    previous_checksum: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    checksum: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
