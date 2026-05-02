"""Create platform task persistence tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260322_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "tasks" not in existing_tables:
        op.create_table(
            "tasks",
            sa.Column("task_id", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("progress", sa.Float(), nullable=False),
            sa.Column("progress_text", sa.Text(), nullable=False),
            sa.Column("progress_source", sa.Text(), nullable=False),
            sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("archived_at", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("task_id"),
        )

    if "task_logs" not in existing_tables:
        op.create_table(
            "task_logs",
            sa.Column("task_id", sa.String(length=64), nullable=False),
            sa.Column("line_no", sa.Integer(), nullable=False),
            sa.Column("log_line", sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("task_id", "line_no"),
        )

    if "platform_metadata" not in existing_tables:
        op.create_table(
            "platform_metadata",
            sa.Column("key", sa.String(length=128), nullable=False),
            sa.Column("value_json", sa.JSON(), nullable=False),
            sa.PrimaryKeyConstraint("key"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "platform_metadata" in existing_tables:
        op.drop_table("platform_metadata")
    if "task_logs" in existing_tables:
        op.drop_table("task_logs")
    if "tasks" in existing_tables:
        op.drop_table("tasks")
