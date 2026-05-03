"""Track operational VM state lifecycle and cleanup metadata.

Revision ID: 20260503_0013
Revises: 20260503_0012
Create Date: 2026-05-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260503_0013"
down_revision = "20260503_0012"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = inspect(bind)
    if table_name not in set(inspector.get_table_names()):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    existing_columns = _column_names("operational_vm_state")
    if not existing_columns:
        return

    with op.batch_alter_table("operational_vm_state") as batch_op:
        if "active" not in existing_columns:
            batch_op.add_column(
                sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true())
            )
        if "missing_since_at" not in existing_columns:
            batch_op.add_column(sa.Column("missing_since_at", sa.Float(), nullable=True))
        if "lifecycle_generation" not in existing_columns:
            batch_op.add_column(
                sa.Column("lifecycle_generation", sa.Integer(), nullable=False, server_default=sa.text("1"))
            )


def downgrade() -> None:
    existing_columns = _column_names("operational_vm_state")
    if not existing_columns:
        return

    with op.batch_alter_table("operational_vm_state") as batch_op:
        if "lifecycle_generation" in existing_columns:
            batch_op.drop_column("lifecycle_generation")
        if "missing_since_at" in existing_columns:
            batch_op.drop_column("missing_since_at")
        if "active" in existing_columns:
            batch_op.drop_column("active")
