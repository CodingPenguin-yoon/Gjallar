import os
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.vm_admission import VmMutationAdmission
from app.operations.vm_image_cleanup.application import ImageCleanupService
from app.operations.vm_image_cleanup.infrastructure import ImageCleanupClient


def image_cleanup_service():
    return ImageCleanupService(client=ImageCleanupClient(), admission=VmMutationAdmission(recovery_kind='vm_image_cleanup_observation'),
        operations=SqlAlchemyOperationStore(), recovery=SqlAlchemyRecoveryStore(),
        cluster_id=str(os.getenv('GJALLAR_CLUSTER_ID') or 'gjallar-mvp').strip())
