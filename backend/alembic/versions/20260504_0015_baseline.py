"""Baseline for restored Alembic source tracking.

Revision ID: 20260504_0015
Revises:
Create Date: 2026-05-04 00:15:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "20260504_0015"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op baseline for existing deployments."""
    op.execute("SELECT 1")


def downgrade() -> None:
    """No-op baseline downgrade."""
    op.execute("SELECT 1")
