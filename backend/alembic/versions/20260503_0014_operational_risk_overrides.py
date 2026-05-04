"""operational risk acknowledge and suppress overrides

Revision ID: 20260503_0014
Revises: 20260503_0013
Create Date: 2026-05-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260503_0014"
down_revision = "20260503_0013"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    bind = op.get_bind()
    inspector = inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    if "operational_risk_overrides" in _table_names():
        return
    op.create_table(
        "operational_risk_overrides",
        sa.Column("risk_id", sa.String(length=512), primary_key=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=True),
        sa.Column("updated_by", sa.Text(), nullable=False, server_default="local"),
    )


def downgrade() -> None:
    if "operational_risk_overrides" not in _table_names():
        return
    op.drop_table("operational_risk_overrides")
