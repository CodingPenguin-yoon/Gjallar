"""Create GitLab inventory table."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260322_0002"
down_revision = "20260322_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "gitlab_projects" not in existing_tables:
        op.create_table(
            "gitlab_projects",
            sa.Column("gitlab_project_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("path_with_namespace", sa.String(length=512), nullable=False),
            sa.Column("web_url", sa.Text(), nullable=False),
            sa.Column("http_url_to_repo", sa.Text(), nullable=False),
            sa.Column("default_branch", sa.String(length=255), nullable=True),
            sa.Column("visibility", sa.String(length=32), nullable=False),
            sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("last_activity_at", sa.Text(), nullable=True),
            sa.Column("synced_at", sa.Text(), nullable=False),
            sa.PrimaryKeyConstraint("gitlab_project_id"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "gitlab_projects" in existing_tables:
        op.drop_table("gitlab_projects")
