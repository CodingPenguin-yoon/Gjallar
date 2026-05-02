"""Add staging host registry table."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260425_0009"
down_revision = "20260425_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "staging_hosts" in existing_tables:
        return

    op.create_table(
        "staging_hosts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("node", sa.String(length=255), nullable=False),
        sa.Column("vmid", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("host_ip", sa.String(length=64), nullable=False),
        sa.Column("pool_key", sa.String(length=64), nullable=False, server_default="default"),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="shared"),
        sa.Column("bootstrap_status", sa.String(length=32), nullable=False, server_default="ready"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("drain_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_task_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("node", "vmid", name="uq_staging_hosts_node_vmid"),
        sa.UniqueConstraint("host_ip", name="uq_staging_hosts_host_ip"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "staging_hosts" in existing_tables:
        op.drop_table("staging_hosts")
