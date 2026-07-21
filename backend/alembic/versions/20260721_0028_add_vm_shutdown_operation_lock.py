"""Allow graceful VM Shutdown to use durable target locks.

Revision ID: 20260721_0028
Revises: 20260721_0027
Create Date: 2026-07-21 20:00:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "20260721_0028"
down_revision = "20260721_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("operation_locks") as batch_op:
        batch_op.drop_constraint("ck_operation_locks_operation_type", type_="check")
        batch_op.create_check_constraint(
            "ck_operation_locks_operation_type",
            "operation_type in ('drs_migration', 'vm_start', 'vm_create', "
            "'guided_qm_vm_unlock', 'vm_shutdown')",
        )


def downgrade() -> None:
    with op.batch_alter_table("operation_locks") as batch_op:
        batch_op.drop_constraint("ck_operation_locks_operation_type", type_="check")
        batch_op.create_check_constraint(
            "ck_operation_locks_operation_type",
            "operation_type in ('drs_migration', 'vm_start', 'vm_create', 'guided_qm_vm_unlock')",
        )
