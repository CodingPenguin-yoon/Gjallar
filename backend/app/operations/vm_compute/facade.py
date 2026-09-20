"""Compute composition root; HTTP and recovery use the same service."""
import os

from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.vm_compute.application import ComputeService
from app.operations.vm_compute.domain import ComputeError
from app.operations.vm_compute.infrastructure import ComputeAdmission, ComputeClient
from app.proxmox.client import ProxmoxMutationError, get_default_proxmox_mutation_client
from app.setup_integration.contracts import SetupError


def compute_service():
    try:
        client = get_default_proxmox_mutation_client()
    except (ProxmoxMutationError, SetupError):
        raise ComputeError("VM_COMPUTE_CONNECTION_UNAVAILABLE", "Proxmox 연결·인증정보를 확인하세요.", 503) from None
    return ComputeService(client=ComputeClient(client), admission=ComputeAdmission(),
                          operations=SqlAlchemyOperationStore(), recovery=SqlAlchemyRecoveryStore(),
                          cluster_id=str(os.getenv("GJALLAR_CLUSTER_ID") or "gjallar-mvp").strip())
