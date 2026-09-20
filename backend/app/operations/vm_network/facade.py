"""Network composition root; HTTP and recovery use the same service."""
import os

from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.vm_network.application import NetworkService
from app.operations.vm_network.domain import NetworkError
from app.operations.vm_network.infrastructure import NetworkAdmission, NetworkClient
from app.proxmox.client import ProxmoxMutationError, get_default_proxmox_mutation_client
from app.setup_integration.contracts import SetupError


def network_service():
    try:
        client = get_default_proxmox_mutation_client()
    except (ProxmoxMutationError, SetupError):
        raise NetworkError("VM_NETWORK_CONNECTION_UNAVAILABLE", "Proxmox 연결·인증정보를 확인하세요.", 503) from None
    return NetworkService(client=NetworkClient(client), admission=NetworkAdmission(),
                          operations=SqlAlchemyOperationStore(), recovery=SqlAlchemyRecoveryStore(),
                          cluster_id=str(os.getenv("GJALLAR_CLUSTER_ID") or "gjallar-mvp").strip())
