"""Add durable operation recovery items and cross-operation locator locks.

Revision ID: 20260721_0027
Revises: 20260720_0026
Create Date: 2026-07-21 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260721_0027"
down_revision = "20260720_0026"
branch_labels = None
depends_on = None

OPEN_LOCATOR_PREDICATE = (
    "scope_type = 'proxmox_locator' and "
    "status in ('active', 'stale', 'reconciliation_required')"
)


def upgrade() -> None:
    with op.batch_alter_table("operation_locks") as batch_op:
        batch_op.drop_constraint("ck_operation_locks_operation_type", type_="check")
        batch_op.create_check_constraint(
            "ck_operation_locks_operation_type",
            "operation_type in ('drs_migration', 'vm_start', 'vm_create', 'guided_qm_vm_unlock')",
        )

    op.create_index(
        "uq_operation_locks_open_locator",
        "operation_locks",
        ["scope_type", "scope_key"],
        unique=True,
        sqlite_where=sa.text(OPEN_LOCATOR_PREDICATE),
        postgresql_where=sa.text(OPEN_LOCATOR_PREDICATE),
    )

    op.create_table(
        "operation_recovery_items",
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("recovery_kind", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=160), nullable=True),
        sa.Column("lease_token", sa.String(length=160), nullable=True),
        sa.Column("lease_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.String(length=120), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('pending', 'leased', 'retry_wait', 'paused', 'completed')",
            name="ck_operation_recovery_items_status",
        ),
        sa.ForeignKeyConstraint(["operation_id"], ["operations.operation_id"]),
        sa.PrimaryKeyConstraint("operation_id"),
    )
    op.create_index(
        "ix_operation_recovery_items_due",
        "operation_recovery_items",
        ["status", "available_at"],
    )
    op.create_index(
        "ix_operation_recovery_items_lease",
        "operation_recovery_items",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_operation_recovery_items_lease", table_name="operation_recovery_items")
    op.drop_index("ix_operation_recovery_items_due", table_name="operation_recovery_items")
    op.drop_table("operation_recovery_items")
    op.drop_index("uq_operation_locks_open_locator", table_name="operation_locks")

    with op.batch_alter_table("operation_locks") as batch_op:
        batch_op.drop_constraint("ck_operation_locks_operation_type", type_="check")
        batch_op.create_check_constraint(
            "ck_operation_locks_operation_type",
            "operation_type in ('drs_migration')",
        )
