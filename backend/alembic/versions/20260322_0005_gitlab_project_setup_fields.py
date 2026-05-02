"""Add GitLab project setup fields."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260322_0005"
down_revision = "20260322_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "gitlab_project_settings" not in existing_tables:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("gitlab_project_settings")}

    if "database_required" not in existing_columns:
        op.add_column(
            "gitlab_project_settings",
            sa.Column("database_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "database_engine" not in existing_columns:
        op.add_column(
            "gitlab_project_settings",
            sa.Column("database_engine", sa.String(length=32), nullable=True),
        )
    if "database_mode" not in existing_columns:
        op.add_column(
            "gitlab_project_settings",
            sa.Column("database_mode", sa.String(length=64), nullable=True),
        )
    if "migration_command" not in existing_columns:
        op.add_column(
            "gitlab_project_settings",
            sa.Column("migration_command", sa.Text(), nullable=True),
        )
    if "deploy_branch" not in existing_columns:
        op.add_column(
            "gitlab_project_settings",
            sa.Column("deploy_branch", sa.String(length=255), nullable=False, server_default="main"),
        )
    if "bootstrap_strategy" not in existing_columns:
        op.add_column(
            "gitlab_project_settings",
            sa.Column("bootstrap_strategy", sa.String(length=32), nullable=False, server_default="merge_request"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "gitlab_project_settings" not in existing_tables:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("gitlab_project_settings")}

    for column_name in (
        "bootstrap_strategy",
        "deploy_branch",
        "migration_command",
        "database_mode",
        "database_engine",
        "database_required",
    ):
        if column_name in existing_columns:
            op.drop_column("gitlab_project_settings", column_name)
