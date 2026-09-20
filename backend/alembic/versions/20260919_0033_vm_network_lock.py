"""Allow network changes to share durable VM locks without deleting history."""
from alembic import op
import sqlalchemy as sa

revision = "20260919_0033"
down_revision = "20260919_0032"
branch_labels = None
depends_on = None


def _replace(actions):
    with op.batch_alter_table("operation_locks") as batch:
        batch.drop_constraint("ck_operation_locks_operation_type", type_="check")
        batch.create_check_constraint("ck_operation_locks_operation_type", "operation_type in (" + actions + ")")


def upgrade():
    _replace("'vm_start', 'vm_create', 'guided_qm_vm_unlock', 'vm_shutdown', 'vm_compute', 'vm_disk_resize', 'vm_network'")


def downgrade():
    if op.get_bind().scalar(sa.text("select count(*) from operation_locks where operation_type = 'vm_network'")):
        raise RuntimeError("vm_network lock history exists; preserve records and use roll-forward recovery")
    _replace("'vm_start', 'vm_create', 'guided_qm_vm_unlock', 'vm_shutdown', 'vm_compute', 'vm_disk_resize'")
