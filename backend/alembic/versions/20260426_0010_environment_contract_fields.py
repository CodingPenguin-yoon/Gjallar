"""Add environment-contract fields to project settings and host registry."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260426_0010"
down_revision = "20260425_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "gitlab_project_settings" in existing_tables:
        existing_columns = {
            column["name"] for column in inspector.get_columns("gitlab_project_settings")
        }
        if "deployment_environment" not in existing_columns:
            op.add_column(
                "gitlab_project_settings",
                sa.Column(
                    "deployment_environment",
                    sa.String(length=32),
                    nullable=False,
                    server_default="staging",
                ),
            )
        if "deployment_pool_key" not in existing_columns:
            op.add_column(
                "gitlab_project_settings",
                sa.Column("deployment_pool_key", sa.String(length=64), nullable=True),
            )
        if "requested_app_port" not in existing_columns:
            op.add_column(
                "gitlab_project_settings",
                sa.Column("requested_app_port", sa.Integer(), nullable=True),
            )

    if "staging_hosts" in existing_tables:
        existing_columns = {column["name"] for column in inspector.get_columns("staging_hosts")}
        if "environment" not in existing_columns:
            op.add_column(
                "staging_hosts",
                sa.Column(
                    "environment",
                    sa.String(length=32),
                    nullable=False,
                    server_default="staging",
                ),
            )
        if "host_user" not in existing_columns:
            op.add_column(
                "staging_hosts",
                sa.Column("host_user", sa.String(length=255), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "staging_hosts" in existing_tables:
        existing_columns = {column["name"] for column in inspector.get_columns("staging_hosts")}
        if "host_user" in existing_columns:
            op.drop_column("staging_hosts", "host_user")
        if "environment" in existing_columns:
            op.drop_column("staging_hosts", "environment")

    if "gitlab_project_settings" in existing_tables:
        existing_columns = {
            column["name"] for column in inspector.get_columns("gitlab_project_settings")
        }
        if "requested_app_port" in existing_columns:
            op.drop_column("gitlab_project_settings", "requested_app_port")
        if "deployment_pool_key" in existing_columns:
            op.drop_column("gitlab_project_settings", "deployment_pool_key")
        if "deployment_environment" in existing_columns:
            op.drop_column("gitlab_project_settings", "deployment_environment")
