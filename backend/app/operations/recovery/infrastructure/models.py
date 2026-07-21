"""SQLAlchemy model owned by Operations recovery."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OperationRecoveryItemRecord(Base):
    """Durable due work and fenced observer lease for one Operation."""

    __tablename__ = "operation_recovery_items"
    __table_args__ = (
        CheckConstraint(
            "status in ('pending', 'leased', 'retry_wait', 'paused', 'completed')",
            name="ck_operation_recovery_items_status",
        ),
        Index("ix_operation_recovery_items_due", "status", "available_at"),
        Index("ix_operation_recovery_items_lease", "status", "lease_expires_at"),
    )

    operation_id: Mapped[str] = mapped_column(
        ForeignKey("operations.operation_id"),
        primary_key=True,
    )
    recovery_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(160), nullable=True)
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
