"""Add GitLab project staging infra profile fields."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260403_0006"
down_revision = "20260322_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "gitlab_project_settings" not in existing_tables:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("gitlab_project_settings")}

    if "staging_server_name" not in existing_columns:
        op.add_column(
            "gitlab_project_settings",
            sa.Column("staging_server_name", sa.String(length=255), nullable=True),
        )
    if "staging_server_id" not in existing_columns:
        op.add_column(
            "gitlab_project_settings",
            sa.Column("staging_server_id", sa.String(length=255), nullable=True),
        )
    if "staging_template_id" not in existing_columns:
        op.add_column(
            "gitlab_project_settings",
            sa.Column("staging_template_id", sa.String(length=255), nullable=True),
        )
    if "staging_storage_id" not in existing_columns:
        op.add_column(
            "gitlab_project_settings",
            sa.Column("staging_storage_id", sa.String(length=255), nullable=True),
        )
    if "staging_network_ids" not in existing_columns:
        op.add_column(
            "gitlab_project_settings",
            sa.Column("staging_network_ids", sa.JSON(), nullable=False, server_default="[]"),
        )
    if "staging_cpu_cores" not in existing_columns:
        op.add_column(
            "gitlab_project_settings",
            sa.Column("staging_cpu_cores", sa.Integer(), nullable=True),
        )
    if "staging_memory_gb" not in existing_columns:
        op.add_column(
            "gitlab_project_settings",
            sa.Column("staging_memory_gb", sa.Integer(), nullable=True),
        )
    if "staging_disk_size_gb" not in existing_columns:
        op.add_column(
            "gitlab_project_settings",
            sa.Column("staging_disk_size_gb", sa.Integer(), nullable=True),
        )
    if "staging_vm_ip" not in existing_columns:
        op.add_column(
            "gitlab_project_settings",
            sa.Column("staging_vm_ip", sa.String(length=64), nullable=True),
        )
    if "staging_vm_gateway" not in existing_columns:
        op.add_column(
            "gitlab_project_settings",
            sa.Column("staging_vm_gateway", sa.String(length=64), nullable=True),
        )
    if "staging_ansible_packages" not in existing_columns:
        op.add_column(
            "gitlab_project_settings",
            sa.Column("staging_ansible_packages", sa.JSON(), nullable=False, server_default="[]"),
        )
    if "staging_ansible_roles" not in existing_columns:
        op.add_column(
            "gitlab_project_settings",
            sa.Column("staging_ansible_roles", sa.JSON(), nullable=False, server_default="[]"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "gitlab_project_settings" not in existing_tables:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("gitlab_project_settings")}

    for column_name in (
        "staging_ansible_roles",
        "staging_ansible_packages",
        "staging_vm_gateway",
        "staging_vm_ip",
        "staging_disk_size_gb",
        "staging_memory_gb",
        "staging_cpu_cores",
        "staging_network_ids",
        "staging_storage_id",
        "staging_template_id",
        "staging_server_id",
        "staging_server_name",
    ):
        if column_name in existing_columns:
            op.drop_column("gitlab_project_settings", column_name)
