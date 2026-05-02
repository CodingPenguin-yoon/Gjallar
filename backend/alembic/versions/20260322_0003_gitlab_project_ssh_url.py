"""Add ssh clone URL to GitLab projects."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260322_0003"
down_revision = "20260322_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "gitlab_projects" not in existing_tables:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("gitlab_projects")}
    if "ssh_url_to_repo" not in existing_columns:
        op.add_column("gitlab_projects", sa.Column("ssh_url_to_repo", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "gitlab_projects" not in existing_tables:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("gitlab_projects")}
    if "ssh_url_to_repo" in existing_columns:
        op.drop_column("gitlab_projects", "ssh_url_to_repo")
