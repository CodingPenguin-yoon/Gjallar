"""operational risk thresholds

Revision ID: 20260503_0012
Revises: 20260503_0011
Create Date: 2026-05-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260503_0012"
down_revision = "20260503_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operational_risk_thresholds",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("thresholds_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("operational_risk_thresholds")
