import os

from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.vm_admission import VmMutationAdmission
from app.operations.vm_delete.application import DeleteService
from app.operations.vm_delete.domain import DeleteError
from app.operations.vm_delete.infrastructure import DeleteClient
from app.proxmox.client import ProxmoxMutationError, get_default_proxmox_mutation_client
from app.setup_integration.contracts import SetupError


def delete_service():
    try:
        client = get_default_proxmox_mutation_client()
    except (ProxmoxMutationError, SetupError):
        raise DeleteError("VM_DELETE_CONNECTION_UNAVAILABLE", "Proxmox 연결·인증정보를 확인하세요.", 503) from None
    return DeleteService(client=DeleteClient(client), admission=VmMutationAdmission(recovery_kind="vm_delete_observation"),
        operations=SqlAlchemyOperationStore(), recovery=SqlAlchemyRecoveryStore(),
        cluster_id=str(os.getenv("GJALLAR_CLUSTER_ID") or "gjallar-mvp").strip())


def observe_owned_storage_volumes(client, *, node_id, vmid, storage_ids):
    return DeleteClient(client).storage_rows(node_id=node_id, vmid=vmid, storage_ids=storage_ids)


def observe_reviewed_volume_removal(client, *, node_id, vmid, before):
    return DeleteClient(client).observe_deletion(node_id=node_id, vmid=vmid, before=before)
