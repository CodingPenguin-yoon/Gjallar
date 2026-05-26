"""Add auth users, sessions, and Create VM actor evidence.

Revision ID: 20260527_0018
Revises: 20260516_0017
Create Date: 2026-05-27 09:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260527_0018"
down_revision = "20260516_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(length=80), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_index("ix_users_username", "users", ["username"])

    op.create_table(
        "sessions",
        sa.Column("session_id", sa.String(length=80), nullable=False),
        sa.Column("user_id", sa.String(length=80), nullable=False),
        sa.Column("session_token_hash", sa.String(length=96), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent_hash", sa.String(length=80), nullable=True),
        sa.Column("ip_hash", sa.String(length=80), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"]),
        sa.PrimaryKeyConstraint("session_id"),
        sa.UniqueConstraint("session_token_hash"),
    )
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])
    op.create_index("ix_sessions_session_token_hash", "sessions", ["session_token_hash"])
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    with op.batch_alter_table("vm_create_requests") as batch_op:
        batch_op.add_column(sa.Column("actor_user_id", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("actor_username", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("actor_role", sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("vm_create_requests") as batch_op:
        batch_op.drop_column("actor_role")
        batch_op.drop_column("actor_username")
        batch_op.drop_column("actor_user_id")

    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_index("ix_sessions_session_token_hash", table_name="sessions")
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
