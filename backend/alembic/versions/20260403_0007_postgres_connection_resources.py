"""Add Postgres connection resource metadata table."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260403_0007"
down_revision = "20260403_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "postgres_connection_resources" in existing_tables:
        return

    op.create_table(
        "postgres_connection_resources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("gitlab_project_id", sa.Integer(), nullable=False),
        sa.Column("environment", sa.String(length=32), nullable=False, server_default="staging"),
        sa.Column("resource_kind", sa.String(length=32), nullable=False, server_default="database"),
        sa.Column("database_name", sa.String(length=255), nullable=True),
        sa.Column("schema_name", sa.String(length=255), nullable=True),
        sa.Column("connection_env", sa.String(length=128), nullable=False, server_default="DATABASE_URL"),
        sa.Column("provision_status", sa.String(length=32), nullable=False, server_default="planned"),
        sa.Column("provisioning_task_id", sa.String(length=64), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["gitlab_project_id"], ["gitlab_projects.gitlab_project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "gitlab_project_id",
            "environment",
            name="uq_postgres_connection_resources_project_environment",
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "postgres_connection_resources" in existing_tables:
        op.drop_table("postgres_connection_resources")
