"""Composition shared by administrator API and observation-only recovery."""
import os

from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.host_config.admission import HostConfigurationAdmission
from app.operations.host_network.application import BridgeService
from app.operations.host_network.domain import BridgeError
from app.operations.host_network.infrastructure import BridgeClient
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.proxmox.client import ProxmoxMutationError, get_default_proxmox_mutation_client
from app.setup_integration.contracts import SetupError


def bridge_service():
    try:
        client = get_default_proxmox_mutation_client()
    except (ProxmoxMutationError, SetupError):
        raise BridgeError('HOST_NETWORK_CONNECTION_UNAVAILABLE', 'Proxmox 연결·인증정보를 확인하세요.', 503) from None
    return BridgeService(client=BridgeClient(client), admission=HostConfigurationAdmission(),
        operations=SqlAlchemyOperationStore(), recovery=SqlAlchemyRecoveryStore(),
        cluster_id=str(os.getenv('GJALLAR_CLUSTER_ID') or 'gjallar-mvp').strip())
