import os

from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.vm_admission import VmMutationAdmission
from app.operations.vm_template.application import TemplateService
from app.operations.vm_template.domain import TemplateError
from app.operations.vm_template.infrastructure import TemplateClient
from app.proxmox.client import ProxmoxMutationError, get_default_proxmox_mutation_client
from app.setup_integration.contracts import SetupError


def template_service():
    try:
        client = get_default_proxmox_mutation_client()
    except (ProxmoxMutationError, SetupError):
        raise TemplateError("VM_TEMPLATE_CONNECTION_UNAVAILABLE", "Proxmox 연결·인증정보를 확인하세요.", 503) from None
    return TemplateService(client=TemplateClient(client), admission=VmMutationAdmission(recovery_kind="vm_template_observation"),
        operations=SqlAlchemyOperationStore(), recovery=SqlAlchemyRecoveryStore(),
        cluster_id=str(os.getenv("GJALLAR_CLUSTER_ID") or "gjallar-mvp").strip())


def observe_prepared_template(client, *, node_id, vmid, converted=False):
    """Public observation contract shared with the official-image builder."""
    return TemplateClient(client).read(node_id=node_id, vmid=vmid, converted=converted)


def conversion_matches(before, after):
    return TemplateService.matches(after, {}, before)


def observe_cleanup_template(client, *, node_id, vmid):
    """Observe template volumes with storage authority that survives VM ACL deletion."""
    return TemplateClient(client).read(node_id=node_id, vmid=vmid, converted=True, storage_authority=True)
