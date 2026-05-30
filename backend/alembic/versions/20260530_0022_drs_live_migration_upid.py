"""Add DRS live migration UPID execution state.

Revision ID: 20260530_0022
Revises: 20260529_0021
Create Date: 2026-05-30 10:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260530_0022"
down_revision = "20260529_0021"
branch_labels = None
depends_on = None

NEW_STATUS_CHECK = (
    "status in ('pending', 'blocked', 'cancelled', 'accepted', 'running', "
    "'failed', 'timed_out', 'ambiguous', 'needs_reconciliation')"
)
OLD_STATUS_CHECK = "status in ('pending', 'blocked', 'cancelled')"


def upgrade() -> None:
    op.create_index(
        "uq_operation_locks_open_scope",
        "operation_locks",
        ["operation_type", "scope_type", "scope_key"],
        unique=True,
        sqlite_where=sa.text("status in ('active', 'stale', 'reconciliation_required')"),
        postgresql_where=sa.text("status in ('active', 'stale', 'reconciliation_required')"),
    )

    with op.batch_alter_table("drs_migration_jobs") as batch_op:
        batch_op.drop_constraint("ck_drs_migration_jobs_status", type_="check")
        batch_op.add_column(sa.Column("proxmox_upid", sa.String(length=320), nullable=True))
        batch_op.add_column(sa.Column("proxmox_task_node", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("migration_started_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("migration_finished_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("task_status", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("task_exitstatus", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("task_result", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("task_metadata", sa.JSON(), nullable=False, server_default="{}"))
        batch_op.add_column(sa.Column("task_log_excerpt", sa.JSON(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("execution_evidence", sa.JSON(), nullable=False, server_default="{}"))
        batch_op.add_column(sa.Column("operation_lock_ids", sa.JSON(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("reconciliation_reason", sa.Text(), nullable=True))
        batch_op.create_check_constraint("ck_drs_migration_jobs_status", NEW_STATUS_CHECK)


def downgrade() -> None:
    with op.batch_alter_table("drs_migration_jobs") as batch_op:
        batch_op.drop_constraint("ck_drs_migration_jobs_status", type_="check")
        batch_op.drop_column("reconciliation_reason")
        batch_op.drop_column("operation_lock_ids")
        batch_op.drop_column("execution_evidence")
        batch_op.drop_column("task_log_excerpt")
        batch_op.drop_column("task_metadata")
        batch_op.drop_column("task_result")
        batch_op.drop_column("task_exitstatus")
        batch_op.drop_column("task_status")
        batch_op.drop_column("migration_finished_at")
        batch_op.drop_column("migration_started_at")
        batch_op.drop_column("proxmox_task_node")
        batch_op.drop_column("proxmox_upid")
        batch_op.create_check_constraint("ck_drs_migration_jobs_status", OLD_STATUS_CHECK)

    op.drop_index("uq_operation_locks_open_scope", table_name="operation_locks")
