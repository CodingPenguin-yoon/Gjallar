"""Add DRS post-check and reconciliation event state.

Revision ID: 20260530_0023
Revises: 20260530_0022
Create Date: 2026-05-30 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260530_0023"
down_revision = "20260530_0022"
branch_labels = None
depends_on = None

NEW_STATUS_CHECK = (
    "status in ('pending', 'blocked', 'cancelled', 'accepted', 'running', "
    "'completed', 'failed', 'timed_out', 'ambiguous', 'needs_reconciliation')"
)
OLD_STATUS_CHECK = (
    "status in ('pending', 'blocked', 'cancelled', 'accepted', 'running', "
    "'failed', 'timed_out', 'ambiguous', 'needs_reconciliation')"
)


def upgrade() -> None:
    with op.batch_alter_table("drs_migration_jobs") as batch_op:
        batch_op.drop_constraint("ck_drs_migration_jobs_status", type_="check")
        batch_op.add_column(sa.Column("post_check_status", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("post_check_evidence", sa.JSON(), nullable=False, server_default="{}"))
        batch_op.add_column(sa.Column("post_check_completed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_check_constraint("ck_drs_migration_jobs_status", NEW_STATUS_CHECK)

    op.create_table(
        "drs_reconciliation_events",
        sa.Column("event_id", sa.String(length=100), nullable=False),
        sa.Column("job_id", sa.String(length=160), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="open"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["job_id"], ["drs_migration_jobs.job_id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_drs_reconciliation_events_job_id", "drs_reconciliation_events", ["job_id"])
    op.create_index(
        "ix_drs_reconciliation_events_job_created",
        "drs_reconciliation_events",
        ["job_id", "created_at"],
    )
    op.create_index(
        "ix_drs_reconciliation_events_status",
        "drs_reconciliation_events",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_drs_reconciliation_events_status", table_name="drs_reconciliation_events")
    op.drop_index("ix_drs_reconciliation_events_job_created", table_name="drs_reconciliation_events")
    op.drop_index("ix_drs_reconciliation_events_job_id", table_name="drs_reconciliation_events")
    op.drop_table("drs_reconciliation_events")

    with op.batch_alter_table("drs_migration_jobs") as batch_op:
        batch_op.drop_constraint("ck_drs_migration_jobs_status", type_="check")
        batch_op.drop_column("post_check_completed_at")
        batch_op.drop_column("post_check_evidence")
        batch_op.drop_column("post_check_status")
        batch_op.create_check_constraint("ck_drs_migration_jobs_status", OLD_STATUS_CHECK)
