"""Add operational VM state history table."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260503_0011"
down_revision = "20260426_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "operational_vm_state" not in existing_tables:
        op.create_table(
            "operational_vm_state",
            sa.Column("resource_key", sa.String(length=96), nullable=False),
            sa.Column("resource_type", sa.String(length=32), nullable=False),
            sa.Column("node", sa.String(length=128), nullable=False),
            sa.Column("vmid", sa.Integer(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("first_seen_at", sa.Float(), nullable=False),
            sa.Column("last_seen_at", sa.Float(), nullable=False),
            sa.Column("status_since_at", sa.Float(), nullable=False),
            sa.Column("last_running_at", sa.Float(), nullable=True),
            sa.Column("last_observed_payload_json", sa.JSON(), nullable=False),
            sa.PrimaryKeyConstraint("resource_key"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "operational_vm_state" in existing_tables:
        op.drop_table("operational_vm_state")
