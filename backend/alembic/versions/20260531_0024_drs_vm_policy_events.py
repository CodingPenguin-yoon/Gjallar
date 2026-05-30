"""Add DRS VM migration policy audit events.

Revision ID: 20260531_0024
Revises: 20260530_0023
Create Date: 2026-05-31 09:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260531_0024"
down_revision = "20260530_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vm_migration_policy_events",
        sa.Column("event_id", sa.String(length=100), nullable=False),
        sa.Column("vm_identity_id", sa.String(length=80), nullable=False),
        sa.Column("policy_id", sa.String(length=100), nullable=True),
        sa.Column("old_policy", sa.String(length=20), nullable=False),
        sa.Column("new_policy", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=40), nullable=False, server_default="manual"),
        sa.Column("actor_user_id", sa.String(length=80), nullable=True),
        sa.Column("actor_username", sa.String(length=80), nullable=True),
        sa.Column("actor_role", sa.String(length=40), nullable=True),
        sa.Column("request_id", sa.String(length=160), nullable=True),
        sa.Column("cluster_id", sa.String(length=120), nullable=False),
        sa.Column("node_id", sa.String(length=120), nullable=False),
        sa.Column("vmid", sa.Integer(), nullable=False),
        sa.Column("fingerprint_hash", sa.String(length=96), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_observation", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("current_observation", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("validation_result", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "old_policy in ('unknown', 'allowed', 'restricted', 'blocked')",
            name="ck_vm_migration_policy_events_old_policy",
        ),
        sa.CheckConstraint(
            "new_policy in ('unknown', 'allowed', 'restricted', 'blocked')",
            name="ck_vm_migration_policy_events_new_policy",
        ),
        sa.CheckConstraint("source in ('manual')", name="ck_vm_migration_policy_events_source"),
        sa.ForeignKeyConstraint(["policy_id"], ["vm_migration_policies.policy_id"]),
        sa.ForeignKeyConstraint(["vm_identity_id"], ["vm_identities.vm_identity_id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_vm_migration_policy_events_vm_identity_id", "vm_migration_policy_events", ["vm_identity_id"])
    op.create_index("ix_vm_migration_policy_events_policy_id", "vm_migration_policy_events", ["policy_id"])
    op.create_index(
        "ix_vm_migration_policy_events_identity_created",
        "vm_migration_policy_events",
        ["vm_identity_id", "created_at"],
    )
    op.create_index(
        "ix_vm_migration_policy_events_policy_created",
        "vm_migration_policy_events",
        ["policy_id", "created_at"],
    )
    op.create_index(
        "ix_vm_migration_policy_events_actor_created",
        "vm_migration_policy_events",
        ["actor_user_id", "created_at"],
    )
    op.create_index(
        "ix_vm_migration_policy_events_locator_created",
        "vm_migration_policy_events",
        ["cluster_id", "node_id", "vmid", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_vm_migration_policy_events_locator_created", table_name="vm_migration_policy_events")
    op.drop_index("ix_vm_migration_policy_events_actor_created", table_name="vm_migration_policy_events")
    op.drop_index("ix_vm_migration_policy_events_policy_created", table_name="vm_migration_policy_events")
    op.drop_index("ix_vm_migration_policy_events_identity_created", table_name="vm_migration_policy_events")
    op.drop_index("ix_vm_migration_policy_events_policy_id", table_name="vm_migration_policy_events")
    op.drop_index("ix_vm_migration_policy_events_vm_identity_id", table_name="vm_migration_policy_events")
    op.drop_table("vm_migration_policy_events")
