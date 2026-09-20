"""Composition shared by HTTP and GET-only recovery."""
import os
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.host_config.admission import HostConfigurationAdmission
from app.operations.host_storage.application import StorageService
from app.operations.host_storage.domain import StorageError
from app.operations.host_storage.infrastructure import StorageClient
from app.proxmox.client import ProxmoxMutationError, get_default_proxmox_mutation_client
from app.setup_integration.contracts import SetupError


def storage_service():
    try:
        client = get_default_proxmox_mutation_client()
    except (ProxmoxMutationError,SetupError):
        raise StorageError('HOST_STORAGE_CONNECTION_UNAVAILABLE','Proxmox 연결·인증정보를 확인하세요.',503) from None
    return StorageService(client=StorageClient(client),admission=HostConfigurationAdmission(),
        operations=SqlAlchemyOperationStore(),recovery=SqlAlchemyRecoveryStore(),
        cluster_id=str(os.getenv('GJALLAR_CLUSTER_ID') or 'gjallar-mvp').strip())
