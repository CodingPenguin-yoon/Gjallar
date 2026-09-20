"""Allow compute changes to share the existing VM target lock.

Revision ID: 20260919_0031
Revises: 20260917_0030
"""
from alembic import op
import sqlalchemy as sa

revision = "20260919_0031"
down_revision = "20260917_0030"
branch_labels = None
depends_on = None


def _replace(expression):
    with op.batch_alter_table("operation_locks") as batch:
        batch.drop_constraint("ck_operation_locks_operation_type", type_="check")
        batch.create_check_constraint("ck_operation_locks_operation_type", expression)


def upgrade():
    _replace("operation_type in ('vm_start', 'vm_create', 'guided_qm_vm_unlock', 'vm_shutdown', 'vm_compute')")


def downgrade():
    if op.get_bind().scalar(sa.text("select count(*) from operation_locks where operation_type = 'vm_compute'")):
        raise RuntimeError("vm_compute lock history exists; preserve records and use a roll-forward recovery")
    _replace("operation_type in ('vm_start', 'vm_create', 'guided_qm_vm_unlock', 'vm_shutdown')")
