"""Create DB-backed Create VM profiles table.

Revision ID: 20260515_0016
Revises: 20260504_0015
Create Date: 2026-05-15 00:16:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260515_0016"
down_revision = "20260504_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "create_vm_profiles",
        sa.Column("profile_id", sa.String(length=80), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("display_name_ko", sa.String(length=160), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("cpu_default", sa.Integer(), nullable=False),
        sa.Column("cpu_min", sa.Integer(), nullable=False),
        sa.Column("cpu_max", sa.Integer(), nullable=False),
        sa.Column("memory_mb_default", sa.Integer(), nullable=False),
        sa.Column("memory_mb_min", sa.Integer(), nullable=False),
        sa.Column("memory_mb_max", sa.Integer(), nullable=False),
        sa.Column("disk_gb_default", sa.Integer(), nullable=False),
        sa.Column("disk_gb_min", sa.Integer(), nullable=False),
        sa.Column("disk_gb_max", sa.Integer(), nullable=False),
        sa.Column("default_user", sa.String(length=80), nullable=False),
        sa.Column("require_ssh_key", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allow_password_login", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("allow_user_override", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ssh_key_source", sa.String(length=120), nullable=False),
        sa.Column("require_cloud_init", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("require_qemu_guest_agent", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source", sa.String(length=80), nullable=False, server_default="db_seed"),
        sa.Column("management", sa.String(length=80), nullable=False, server_default="read_only"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("profile_id"),
    )
    op.create_index(
        "ix_create_vm_profiles_active_order",
        "create_vm_profiles",
        ["enabled", "disabled_at", "archived_at", "sort_order"],
    )


def downgrade() -> None:
    op.drop_index("ix_create_vm_profiles_active_order", table_name="create_vm_profiles")
    op.drop_table("create_vm_profiles")
