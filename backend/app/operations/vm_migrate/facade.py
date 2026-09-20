import os

from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.vm_admission import VmMutationAdmission
from app.operations.vm_migrate.application import MigrateService
from app.operations.vm_migrate.domain import MigrateError
from app.operations.vm_migrate.infrastructure import MigrateClient
from app.proxmox.client import ProxmoxMutationError, get_default_proxmox_mutation_client
from app.setup_integration.contracts import SetupError


def migrate_service():
    try:
        client = get_default_proxmox_mutation_client()
    except (ProxmoxMutationError, SetupError):
        raise MigrateError("VM_MIGRATE_CONNECTION_UNAVAILABLE", "Proxmox 연결·인증정보를 확인하세요.", 503) from None
    return MigrateService(client=MigrateClient(client), admission=VmMutationAdmission(recovery_kind="vm_migrate_observation"),
        operations=SqlAlchemyOperationStore(), recovery=SqlAlchemyRecoveryStore(),
        cluster_id=str(os.getenv("GJALLAR_CLUSTER_ID") or "gjallar-mvp").strip())
