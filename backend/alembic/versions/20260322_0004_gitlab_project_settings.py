"""Add GitLab project settings table."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260322_0004"
down_revision = "20260322_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "gitlab_project_settings" not in existing_tables:
        op.create_table(
            "gitlab_project_settings",
            sa.Column("gitlab_project_id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("staging_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("ready_for_bootstrap", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.Text(), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "gitlab_project_settings" in existing_tables:
        op.drop_table("gitlab_project_settings")
