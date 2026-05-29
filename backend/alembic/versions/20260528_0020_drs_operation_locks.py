"""Add DRS operation locks.

Revision ID: 20260528_0020
Revises: 20260528_0019
Create Date: 2026-05-28 10:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260528_0020"
down_revision = "20260528_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operation_locks",
        sa.Column("operation_lock_id", sa.String(length=100), nullable=False),
        sa.Column("operation_type", sa.String(length=40), nullable=False),
        sa.Column("scope_type", sa.String(length=40), nullable=False),
        sa.Column("scope_key", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("cluster_id", sa.String(length=120), nullable=False),
        sa.Column("vm_identity_id", sa.String(length=80), nullable=True),
        sa.Column("vmid", sa.Integer(), nullable=True),
        sa.Column("source_node_id", sa.String(length=120), nullable=True),
        sa.Column("target_node_id", sa.String(length=120), nullable=True),
        sa.Column("owner_id", sa.String(length=160), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "operation_type in ('drs_migration')",
            name="ck_operation_locks_operation_type",
        ),
        sa.CheckConstraint(
            "scope_type in ('vm_identity', 'proxmox_locator', 'route')",
            name="ck_operation_locks_scope_type",
        ),
        sa.CheckConstraint(
            "status in ('active', 'released', 'stale', 'reconciliation_required')",
            name="ck_operation_locks_status",
        ),
        sa.ForeignKeyConstraint(["vm_identity_id"], ["vm_identities.vm_identity_id"]),
        sa.PrimaryKeyConstraint("operation_lock_id"),
    )
    op.create_index(
        "ix_operation_locks_scope_status",
        "operation_locks",
        ["operation_type", "scope_type", "scope_key", "status"],
    )
    op.create_index(
        "ix_operation_locks_cluster_identity_status",
        "operation_locks",
        ["cluster_id", "vm_identity_id", "status"],
    )
    op.create_index(
        "ix_operation_locks_locator_status",
        "operation_locks",
        ["cluster_id", "source_node_id", "vmid", "status"],
    )
    op.create_index(
        "ix_operation_locks_route_status",
        "operation_locks",
        ["cluster_id", "source_node_id", "target_node_id", "status"],
    )
    op.create_index("ix_operation_locks_expires_at", "operation_locks", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_operation_locks_expires_at", table_name="operation_locks")
    op.drop_index("ix_operation_locks_route_status", table_name="operation_locks")
    op.drop_index("ix_operation_locks_locator_status", table_name="operation_locks")
    op.drop_index("ix_operation_locks_cluster_identity_status", table_name="operation_locks")
    op.drop_index("ix_operation_locks_scope_status", table_name="operation_locks")
    op.drop_table("operation_locks")
