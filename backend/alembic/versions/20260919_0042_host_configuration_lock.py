"""Add explicit host configuration scopes without rewriting VM lock history."""
from alembic import op
import sqlalchemy as sa

revision = '20260919_0042'
down_revision = '20260919_0041'
branch_labels = None
depends_on = None
VM_TYPES = "'vm_start', 'vm_create', 'guided_qm_vm_unlock', 'vm_shutdown', 'vm_compute', 'vm_disk_resize', 'vm_network', 'vm_clone', 'vm_delete', 'vm_template', 'vm_image_build', 'vm_image_cleanup', 'vm_backup', 'vm_restore', 'vm_migrate'"
HOST_TYPES = "'host_storage', 'host_network'"
HOST_OPEN = "scope_type = 'proxmox_configuration' and status in ('active', 'stale', 'reconciliation_required')"


def upgrade():
    with op.batch_alter_table('operation_locks') as batch:
        batch.drop_constraint('ck_operation_locks_operation_type', type_='check')
        batch.drop_constraint('ck_operation_locks_scope_type', type_='check')
        batch.create_check_constraint('ck_operation_locks_operation_type', 'operation_type in (' + VM_TYPES + ', ' + HOST_TYPES + ')')
        batch.create_check_constraint('ck_operation_locks_scope_type', "scope_type in ('proxmox_locator', 'proxmox_configuration')")
        batch.create_check_constraint('ck_operation_locks_host_binding',
            "(scope_type = 'proxmox_configuration' and operation_type in (" + HOST_TYPES + ") and vmid is null) "
            "or (scope_type = 'proxmox_locator' and operation_type not in (" + HOST_TYPES + '))')
    op.create_index('uq_operation_locks_open_configuration', 'operation_locks', ['scope_type', 'scope_key'], unique=True,
        sqlite_where=sa.text(HOST_OPEN), postgresql_where=sa.text(HOST_OPEN))


def downgrade():
    count = op.get_bind().scalar(sa.text("select count(*) from operation_locks where scope_type = 'proxmox_configuration' or operation_type in (" + HOST_TYPES + ')'))
    if count:
        raise RuntimeError('host configuration lock history exists; preserve records and use roll-forward recovery')
    op.drop_index('uq_operation_locks_open_configuration', table_name='operation_locks')
    with op.batch_alter_table('operation_locks') as batch:
        batch.drop_constraint('ck_operation_locks_host_binding', type_='check')
        batch.drop_constraint('ck_operation_locks_operation_type', type_='check')
        batch.drop_constraint('ck_operation_locks_scope_type', type_='check')
        batch.create_check_constraint('ck_operation_locks_operation_type', 'operation_type in (' + VM_TYPES + ')')
        batch.create_check_constraint('ck_operation_locks_scope_type', "scope_type = 'proxmox_locator'")
