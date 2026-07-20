"""Add common Operation projection and append-only event tables.

Revision ID: 20260720_0026
Revises: 20260601_0025
Create Date: 2026-07-20 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260720_0026"
down_revision = "20260601_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operations",
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("operation_type", sa.String(length=80), nullable=False),
        sa.Column("execution_mode", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.String(length=240), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("intent_digest", sa.String(length=80), nullable=False),
        sa.Column("plan_digest", sa.String(length=80), nullable=False),
        sa.Column("current_stage", sa.String(length=80), nullable=False),
        sa.Column("actor_user_id", sa.String(length=80), nullable=True),
        sa.Column("actor_username", sa.String(length=80), nullable=True),
        sa.Column("actor_role", sa.String(length=40), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("last_event_checksum", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "execution_mode in ('managed_api', 'guided_manual', 'observe_only')",
            name="ck_operations_execution_mode",
        ),
        sa.CheckConstraint(
            "status in ('draft', 'planned', 'awaiting_approval', 'approved', 'dispatching', 'running', "
            "'awaiting_operator', 'awaiting_verification', 'verifying', 'succeeded', 'blocked', 'rejected', "
            "'expired', 'failed', 'needs_reconciliation', 'cancelled')",
            name="ck_operations_status",
        ),
        sa.PrimaryKeyConstraint("operation_id"),
        sa.UniqueConstraint(
            "operation_type",
            "target_type",
            "target_id",
            "idempotency_key",
            name="uq_operations_scoped_idempotency",
        ),
    )
    op.create_index("ix_operations_status_updated", "operations", ["status", "updated_at"])
    op.create_index("ix_operations_target_status", "operations", ["target_type", "target_id", "status"])
    op.create_index("ix_operations_actor_created", "operations", ["actor_user_id", "created_at"])

    op.create_table(
        "operation_events",
        sa.Column("event_id", sa.String(length=160), nullable=False),
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("from_status", sa.String(length=40), nullable=True),
        sa.Column("to_status", sa.String(length=40), nullable=False),
        sa.Column("stage", sa.String(length=80), nullable=False),
        sa.Column("actor_user_id", sa.String(length=80), nullable=True),
        sa.Column("actor_username", sa.String(length=80), nullable=True),
        sa.Column("actor_role", sa.String(length=40), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("previous_checksum", sa.String(length=80), nullable=False),
        sa.Column("checksum", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["operation_id"], ["operations.operation_id"]),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("operation_id", "sequence", name="uq_operation_events_operation_sequence"),
    )
    op.create_index(
        "ix_operation_events_operation_created",
        "operation_events",
        ["operation_id", "created_at"],
    )
    op.create_index("ix_operation_events_type_created", "operation_events", ["event_type", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_operation_events_type_created", table_name="operation_events")
    op.drop_index("ix_operation_events_operation_created", table_name="operation_events")
    op.drop_table("operation_events")
    op.drop_index("ix_operations_actor_created", table_name="operations")
    op.drop_index("ix_operations_target_status", table_name="operations")
    op.drop_index("ix_operations_status_updated", table_name="operations")
    op.drop_table("operations")
