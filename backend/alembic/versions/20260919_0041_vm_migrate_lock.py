"""Allow explicit stopped VM migration without altering historical locks."""
from alembic import op
import sqlalchemy as sa

revision = "20260919_0041"
down_revision = "20260919_0040"
branch_labels = None
depends_on = None

PREVIOUS = "'vm_start', 'vm_create', 'guided_qm_vm_unlock', 'vm_shutdown', 'vm_compute', 'vm_disk_resize', 'vm_network', 'vm_clone', 'vm_delete', 'vm_template', 'vm_image_build', 'vm_image_cleanup', 'vm_backup', 'vm_restore'"


def _replace(actions):
    with op.batch_alter_table("operation_locks") as batch:
        batch.drop_constraint("ck_operation_locks_operation_type", type_="check")
        batch.create_check_constraint("ck_operation_locks_operation_type", "operation_type in (" + actions + ")")


def upgrade():
    _replace(PREVIOUS + ", 'vm_migrate'")


def downgrade():
    if op.get_bind().scalar(sa.text("select count(*) from operation_locks where operation_type = 'vm_migrate'")):
        raise RuntimeError("vm_migrate lock history exists; preserve records and use roll-forward recovery")
    _replace(PREVIOUS)
