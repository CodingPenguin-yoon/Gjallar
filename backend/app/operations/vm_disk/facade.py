import os

from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.vm_admission import VmMutationAdmission
from app.operations.vm_disk.application import DiskService
from app.operations.vm_disk.domain import DiskError
from app.operations.vm_disk.infrastructure import DiskClient
from app.proxmox.client import ProxmoxMutationError, get_default_proxmox_mutation_client
from app.setup_integration.contracts import SetupError


def disk_service():
    try:
        client = get_default_proxmox_mutation_client()
    except (ProxmoxMutationError, SetupError):
        raise DiskError("VM_DISK_CONNECTION_UNAVAILABLE", "Proxmox 연결·인증정보를 확인하세요.", 503) from None
    return DiskService(client=DiskClient(client), admission=VmMutationAdmission(recovery_kind="vm_disk_observation"),
        operations=SqlAlchemyOperationStore(), recovery=SqlAlchemyRecoveryStore(),
        cluster_id=str(os.getenv("GJALLAR_CLUSTER_ID") or "gjallar-mvp").strip())
