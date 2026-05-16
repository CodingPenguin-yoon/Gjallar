"""Add DB-backed jobs, artifacts, and VM records.

Revision ID: 20260516_0017
Revises: 20260515_0016
Create Date: 2026-05-16 14:45:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260516_0017"
down_revision = "20260515_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_runs",
        sa.Column("job_id", sa.String(length=160), nullable=False),
        sa.Column("job_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.String(length=240), nullable=False),
        sa.Column("risk_level", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.String(length=80), nullable=False),
        sa.Column("finished_at", sa.String(length=80), nullable=True),
        sa.Column("current_stage", sa.String(length=80), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("risks", sa.JSON(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("artifact_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("risk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index("ix_job_runs_updated_at", "job_runs", ["updated_at"])

    op.create_table(
        "job_artifacts",
        sa.Column("artifact_id", sa.String(length=240), nullable=False),
        sa.Column("job_id", sa.String(length=160), nullable=False),
        sa.Column("type", sa.String(length=120), nullable=False),
        sa.Column("path", sa.String(length=320), nullable=False),
        sa.Column("checksum", sa.String(length=80), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_backend", sa.String(length=40), nullable=False, server_default="db"),
        sa.Column("created_at", sa.String(length=80), nullable=False),
        sa.Column("updated_at", sa.String(length=80), nullable=False),
        sa.PrimaryKeyConstraint("artifact_id"),
    )
    op.create_index("ix_job_artifacts_job_id", "job_artifacts", ["job_id"])

    op.create_table(
        "vm_create_requests",
        sa.Column("request_id", sa.String(length=160), nullable=False),
        sa.Column("draft_id", sa.String(length=160), nullable=False),
        sa.Column("manifest_id", sa.String(length=160), nullable=False),
        sa.Column("operator_id", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("target_node_id", sa.String(length=120), nullable=False),
        sa.Column("vmid", sa.Integer(), nullable=False),
        sa.Column("vm_name", sa.String(length=240), nullable=False),
        sa.Column("profile_id", sa.String(length=120), nullable=False),
        sa.Column("template_id", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("storage_id", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("approval", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(length=80), nullable=False),
        sa.Column("updated_at", sa.String(length=80), nullable=False),
        sa.PrimaryKeyConstraint("request_id"),
    )

    op.create_table(
        "vm_instances",
        sa.Column("vm_instance_id", sa.String(length=200), nullable=False),
        sa.Column("node_id", sa.String(length=120), nullable=False),
        sa.Column("vmid", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("profile_id", sa.String(length=120), nullable=False),
        sa.Column("template_id", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("storage_id", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("cpu", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("memory_mb", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("disk_gb", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("network", sa.JSON(), nullable=False),
        sa.Column("access", sa.JSON(), nullable=False),
        sa.Column("observed_after", sa.JSON(), nullable=False),
        sa.Column("create_job_id", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(length=80), nullable=False),
        sa.Column("updated_at", sa.String(length=80), nullable=False),
        sa.PrimaryKeyConstraint("vm_instance_id"),
        sa.UniqueConstraint("node_id", "vmid", name="uq_vm_instances_node_vmid"),
    )


def downgrade() -> None:
    op.drop_table("vm_instances")
    op.drop_table("vm_create_requests")
    op.drop_index("ix_job_artifacts_job_id", table_name="job_artifacts")
    op.drop_table("job_artifacts")
    op.drop_index("ix_job_runs_updated_at", table_name="job_runs")
    op.drop_table("job_runs")
