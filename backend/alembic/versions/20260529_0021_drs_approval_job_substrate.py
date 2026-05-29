"""Add DRS approval packet and migration job substrate.

Revision ID: 20260529_0021
Revises: 20260528_0020
Create Date: 2026-05-29 10:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260529_0021"
down_revision = "20260528_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "drs_approval_packets",
        sa.Column("approval_packet_id", sa.String(length=100), nullable=False),
        sa.Column("packet_status", sa.String(length=40), nullable=False),
        sa.Column("job_id", sa.String(length=160), nullable=False),
        sa.Column("recommendation_id", sa.String(length=240), nullable=False),
        sa.Column("cluster_id", sa.String(length=120), nullable=False),
        sa.Column("vm_identity_id", sa.String(length=80), nullable=False),
        sa.Column("vmid", sa.Integer(), nullable=False),
        sa.Column("vm_name", sa.String(length=240), nullable=False),
        sa.Column("source_node_id", sa.String(length=120), nullable=False),
        sa.Column("target_node_id", sa.String(length=120), nullable=False),
        sa.Column("actor_user_id", sa.String(length=80), nullable=False),
        sa.Column("actor_username", sa.String(length=80), nullable=False),
        sa.Column("actor_role", sa.String(length=40), nullable=False),
        sa.Column("warning_acknowledged", sa.Boolean(), nullable=False),
        sa.Column("warning_codes", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("recommendation_checksum", sa.String(length=80), nullable=False),
        sa.Column("final_precheck_checksum", sa.String(length=80), nullable=False),
        sa.Column("approval_packet_checksum", sa.String(length=80), nullable=False),
        sa.Column("recommendation_artifact_id", sa.String(length=240), nullable=False),
        sa.Column("final_precheck_artifact_id", sa.String(length=240), nullable=False),
        sa.Column("approval_artifact_id", sa.String(length=240), nullable=False),
        sa.Column("final_precheck_summary", sa.JSON(), nullable=False),
        sa.Column("lock_evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "packet_status in ('approved', 'blocked')",
            name="ck_drs_approval_packets_packet_status",
        ),
        sa.ForeignKeyConstraint(["vm_identity_id"], ["vm_identities.vm_identity_id"]),
        sa.PrimaryKeyConstraint("approval_packet_id"),
        sa.UniqueConstraint("job_id", name="uq_drs_approval_packets_job_id"),
    )
    op.create_index(
        "ix_drs_approval_packets_recommendation",
        "drs_approval_packets",
        ["recommendation_id", "created_at"],
    )
    op.create_index(
        "ix_drs_approval_packets_identity",
        "drs_approval_packets",
        ["vm_identity_id", "created_at"],
    )
    op.create_index(
        "ix_drs_approval_packets_route",
        "drs_approval_packets",
        ["cluster_id", "source_node_id", "target_node_id", "created_at"],
    )
    op.create_index("ix_drs_approval_packets_vm_identity_id", "drs_approval_packets", ["vm_identity_id"])

    op.create_table(
        "drs_migration_jobs",
        sa.Column("job_id", sa.String(length=160), nullable=False),
        sa.Column("approval_packet_id", sa.String(length=100), nullable=False),
        sa.Column("recommendation_id", sa.String(length=240), nullable=False),
        sa.Column("cluster_id", sa.String(length=120), nullable=False),
        sa.Column("vm_identity_id", sa.String(length=80), nullable=False),
        sa.Column("vmid", sa.Integer(), nullable=False),
        sa.Column("source_node_id", sa.String(length=120), nullable=False),
        sa.Column("target_node_id", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("runnable", sa.Boolean(), nullable=False),
        sa.Column("proxmox_mutation_enabled", sa.Boolean(), nullable=False),
        sa.Column("side_effects", sa.JSON(), nullable=False),
        sa.Column("runnable_blockers", sa.JSON(), nullable=False),
        sa.Column("final_precheck_summary", sa.JSON(), nullable=False),
        sa.Column("lock_evidence", sa.JSON(), nullable=False),
        sa.Column("approved_actor", sa.JSON(), nullable=False),
        sa.Column("job_intent_artifact_id", sa.String(length=240), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status in ('pending', 'blocked', 'cancelled')",
            name="ck_drs_migration_jobs_status",
        ),
        sa.ForeignKeyConstraint(["approval_packet_id"], ["drs_approval_packets.approval_packet_id"]),
        sa.ForeignKeyConstraint(["vm_identity_id"], ["vm_identities.vm_identity_id"]),
        sa.PrimaryKeyConstraint("job_id"),
        sa.UniqueConstraint("approval_packet_id", name="uq_drs_migration_jobs_approval_packet_id"),
    )
    op.create_index(
        "ix_drs_migration_jobs_recommendation",
        "drs_migration_jobs",
        ["recommendation_id", "created_at"],
    )
    op.create_index(
        "ix_drs_migration_jobs_identity_status",
        "drs_migration_jobs",
        ["vm_identity_id", "status"],
    )
    op.create_index(
        "ix_drs_migration_jobs_route_status",
        "drs_migration_jobs",
        ["cluster_id", "source_node_id", "target_node_id", "status"],
    )
    op.create_index("ix_drs_migration_jobs_approval_packet_id", "drs_migration_jobs", ["approval_packet_id"])
    op.create_index("ix_drs_migration_jobs_vm_identity_id", "drs_migration_jobs", ["vm_identity_id"])


def downgrade() -> None:
    op.drop_index("ix_drs_migration_jobs_vm_identity_id", table_name="drs_migration_jobs")
    op.drop_index("ix_drs_migration_jobs_approval_packet_id", table_name="drs_migration_jobs")
    op.drop_index("ix_drs_migration_jobs_route_status", table_name="drs_migration_jobs")
    op.drop_index("ix_drs_migration_jobs_identity_status", table_name="drs_migration_jobs")
    op.drop_index("ix_drs_migration_jobs_recommendation", table_name="drs_migration_jobs")
    op.drop_table("drs_migration_jobs")
    op.drop_index("ix_drs_approval_packets_vm_identity_id", table_name="drs_approval_packets")
    op.drop_index("ix_drs_approval_packets_route", table_name="drs_approval_packets")
    op.drop_index("ix_drs_approval_packets_identity", table_name="drs_approval_packets")
    op.drop_index("ix_drs_approval_packets_recommendation", table_name="drs_approval_packets")
    op.drop_table("drs_approval_packets")
