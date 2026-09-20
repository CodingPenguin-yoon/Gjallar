import os

from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.vm_admission import VmMutationAdmission
from app.operations.vm_restore.application import RestoreService
from app.backups.domain import BackupError
from app.operations.vm_restore.infrastructure import RestoreClient
from app.proxmox.client import ProxmoxMutationError, get_default_proxmox_mutation_client
from app.setup_integration.contracts import SetupError


def restore_service():
    try:
        client = get_default_proxmox_mutation_client()
    except (ProxmoxMutationError, SetupError):
        raise BackupError("VM_RESTORE_CONNECTION_UNAVAILABLE", "Proxmox 연결·인증정보를 확인하세요.", 503) from None
    return RestoreService(client=RestoreClient(client), admission=VmMutationAdmission(recovery_kind="vm_restore_observation"),
        operations=SqlAlchemyOperationStore(), recovery=SqlAlchemyRecoveryStore(),
        cluster_id=str(os.getenv("GJALLAR_CLUSTER_ID") or "gjallar-mvp").strip())


def restore_report(operation_id):
    from app.operations.facade import get_operation
    from app.operations.vm_restore.report import restore_report as build_report
    return build_report(get_operation(operation_id), restore_service().client)
