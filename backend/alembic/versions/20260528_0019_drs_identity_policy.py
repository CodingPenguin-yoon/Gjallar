"""Add DRS VM identities, observations, and migration policies.

Revision ID: 20260528_0019
Revises: 20260527_0018
Create Date: 2026-05-28 09:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260528_0019"
down_revision = "20260527_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vm_identities",
        sa.Column("vm_identity_id", sa.String(length=80), nullable=False),
        sa.Column("cluster_id", sa.String(length=120), nullable=False),
        sa.Column("stable_fingerprint", sa.String(length=96), nullable=False),
        sa.Column("identity_status", sa.String(length=20), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "identity_status in ('active', 'uncertain', 'retired')",
            name="ck_vm_identities_identity_status",
        ),
        sa.PrimaryKeyConstraint("vm_identity_id"),
        sa.UniqueConstraint("cluster_id", "stable_fingerprint", name="uq_vm_identities_cluster_fingerprint"),
    )
    op.create_index("ix_vm_identities_cluster_id", "vm_identities", ["cluster_id"])

    op.create_table(
        "vm_identity_observations",
        sa.Column("observation_id", sa.String(length=100), nullable=False),
        sa.Column("vm_identity_id", sa.String(length=80), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cluster_id", sa.String(length=120), nullable=False),
        sa.Column("node_id", sa.String(length=120), nullable=False),
        sa.Column("vmid", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("power_state", sa.String(length=80), nullable=False),
        sa.Column("template", sa.Boolean(), nullable=False),
        sa.Column("fingerprint_hash", sa.String(length=96), nullable=False),
        sa.Column("fingerprint_components", sa.JSON(), nullable=False),
        sa.Column("match_confidence", sa.String(length=20), nullable=False),
        sa.Column("match_reason", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.CheckConstraint(
            "match_confidence in ('high', 'medium', 'low', 'unknown')",
            name="ck_vm_identity_observations_match_confidence",
        ),
        sa.ForeignKeyConstraint(["vm_identity_id"], ["vm_identities.vm_identity_id"]),
        sa.PrimaryKeyConstraint("observation_id"),
    )
    op.create_index("ix_vm_identity_observations_vm_identity_id", "vm_identity_observations", ["vm_identity_id"])
    op.create_index(
        "ix_vm_identity_observations_identity_seen",
        "vm_identity_observations",
        ["vm_identity_id", "observed_at"],
    )
    op.create_index(
        "ix_vm_identity_observations_locator",
        "vm_identity_observations",
        ["cluster_id", "node_id", "vmid"],
    )
    op.create_index(
        "ix_vm_identity_observations_fingerprint",
        "vm_identity_observations",
        ["cluster_id", "fingerprint_hash"],
    )

    op.create_table(
        "vm_migration_policies",
        sa.Column("policy_id", sa.String(length=100), nullable=False),
        sa.Column("vm_identity_id", sa.String(length=80), nullable=False),
        sa.Column("policy", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("updated_by", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "policy in ('unknown', 'allowed', 'restricted', 'blocked')",
            name="ck_vm_migration_policies_policy",
        ),
        sa.CheckConstraint(
            "source in ('default', 'manual', 'tag', 'imported')",
            name="ck_vm_migration_policies_source",
        ),
        sa.ForeignKeyConstraint(["vm_identity_id"], ["vm_identities.vm_identity_id"]),
        sa.PrimaryKeyConstraint("policy_id"),
        sa.UniqueConstraint("vm_identity_id", name="uq_vm_migration_policies_vm_identity_id"),
    )
    op.create_index("ix_vm_migration_policies_vm_identity_id", "vm_migration_policies", ["vm_identity_id"])


def downgrade() -> None:
    op.drop_index("ix_vm_migration_policies_vm_identity_id", table_name="vm_migration_policies")
    op.drop_table("vm_migration_policies")
    op.drop_index("ix_vm_identity_observations_fingerprint", table_name="vm_identity_observations")
    op.drop_index("ix_vm_identity_observations_locator", table_name="vm_identity_observations")
    op.drop_index("ix_vm_identity_observations_identity_seen", table_name="vm_identity_observations")
    op.drop_index("ix_vm_identity_observations_vm_identity_id", table_name="vm_identity_observations")
    op.drop_table("vm_identity_observations")
    op.drop_index("ix_vm_identities_cluster_id", table_name="vm_identities")
    op.drop_table("vm_identities")
