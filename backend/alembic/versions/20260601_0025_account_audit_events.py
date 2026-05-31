"""Add sanitized account and session audit events.

Revision ID: 20260601_0025
Revises: 20260531_0024
Create Date: 2026-06-01 09:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260601_0025"
down_revision = "20260531_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_audit_events",
        sa.Column("event_id", sa.String(length=100), nullable=False),
        sa.Column("operation", sa.String(length=80), nullable=False),
        sa.Column("actor_user_id", sa.String(length=80), nullable=True),
        sa.Column("actor_username", sa.String(length=80), nullable=True),
        sa.Column("actor_role", sa.String(length=40), nullable=True),
        sa.Column("target_user_id", sa.String(length=80), nullable=True),
        sa.Column("target_username", sa.String(length=80), nullable=True),
        sa.Column("target_session_id", sa.String(length=80), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_account_audit_events_actor_created",
        "account_audit_events",
        ["actor_user_id", "created_at"],
    )
    op.create_index(
        "ix_account_audit_events_target_user_created",
        "account_audit_events",
        ["target_user_id", "created_at"],
    )
    op.create_index(
        "ix_account_audit_events_target_session_created",
        "account_audit_events",
        ["target_session_id", "created_at"],
    )
    op.create_index(
        "ix_account_audit_events_operation_created",
        "account_audit_events",
        ["operation", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_account_audit_events_operation_created", table_name="account_audit_events")
    op.drop_index("ix_account_audit_events_target_session_created", table_name="account_audit_events")
    op.drop_index("ix_account_audit_events_target_user_created", table_name="account_audit_events")
    op.drop_index("ix_account_audit_events_actor_created", table_name="account_audit_events")
    op.drop_table("account_audit_events")
