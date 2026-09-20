"""Compose only existing inventory and public backup/migration review boundaries."""
from app.maintenance.application import MaintenanceError, MaintenanceService
from app.workloads.inventory import get_default_workload_inventory_query
from app.operations.vm_migrate.facade import migrate_service
from app.operations.vm_migrate.domain import MigrateError
from app.operations.vm_backup.facade import backup_service
from app.backups.domain import BackupError


def _inventory():
    observation = get_default_workload_inventory_query().observe()
    return {'observed_at': observation.status.observed_at,
            'snapshot': observation.snapshot.to_dict() if observation.snapshot is not None else None}


def _migration_review(**kwargs):
    try:
        return migrate_service().review(**kwargs)
    except MigrateError as exc:
        raise MaintenanceError(exc.code, str(exc), exc.status_code) from None


def _backup_listing(**kwargs):
    try:
        return backup_service().listing(**kwargs)
    except BackupError as exc:
        raise MaintenanceError(exc.code, str(exc), exc.status_code) from None


def maintenance_service():
    return MaintenanceService(_inventory, _migration_review, _backup_listing)
