"""Add project-level staging environment selection key."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260425_0008"
down_revision = "20260403_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "gitlab_project_settings" not in existing_tables:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("gitlab_project_settings")}
    if "staging_environment_key" in existing_columns:
        return

    op.add_column(
        "gitlab_project_settings",
        sa.Column(
            "staging_environment_key",
            sa.String(length=64),
            nullable=False,
            server_default="dedicated_vm",
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "gitlab_project_settings" not in existing_tables:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("gitlab_project_settings")}
    if "staging_environment_key" in existing_columns:
        op.drop_column("gitlab_project_settings", "staging_environment_key")
