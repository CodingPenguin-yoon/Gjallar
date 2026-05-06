"""operational restore drill records

Revision ID: 20260504_0015
Revises: 20260503_0014
Create Date: 2026-05-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260504_0015"
down_revision = "20260503_0014"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    bind = op.get_bind()
    inspector = inspect(bind)
    return set(inspector.get_table_names())


def _index_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    if "operational_restore_drills" in _table_names():
        return
    op.create_table(
        "operational_restore_drills",
        sa.Column("drill_id", sa.String(length=64), primary_key=True),
        sa.Column("resource_type", sa.String(length=32), nullable=False, server_default="qemu"),
        sa.Column("node", sa.String(length=128), nullable=False),
        sa.Column("vmid", sa.Integer(), nullable=False),
        sa.Column("vm_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("datastore", sa.Text(), nullable=False, server_default=""),
        sa.Column("snapshot", sa.Text(), nullable=False, server_default=""),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("drilled_at", sa.Float(), nullable=False),
        sa.Column("recorded_at", sa.Float(), nullable=False),
        sa.Column("recorded_by", sa.Text(), nullable=False, server_default="local"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence_json", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_operational_restore_drills_node_vmid_drilled_at",
        "operational_restore_drills",
        ["node", "vmid", "drilled_at"],
    )
    op.create_index(
        "ix_operational_restore_drills_outcome_drilled_at",
        "operational_restore_drills",
        ["outcome", "drilled_at"],
    )


def downgrade() -> None:
    if "operational_restore_drills" not in _table_names():
        return
    indexes = _index_names("operational_restore_drills")
    if "ix_operational_restore_drills_outcome_drilled_at" in indexes:
        op.drop_index("ix_operational_restore_drills_outcome_drilled_at", table_name="operational_restore_drills")
    if "ix_operational_restore_drills_node_vmid_drilled_at" in indexes:
        op.drop_index("ix_operational_restore_drills_node_vmid_drilled_at", table_name="operational_restore_drills")
    op.drop_table("operational_restore_drills")
