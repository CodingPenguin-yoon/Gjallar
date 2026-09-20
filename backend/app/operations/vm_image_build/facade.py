import os

from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.vm_admission import VmMutationAdmission
from app.operations.vm_image_build.application import ImageBuildService
from app.operations.vm_image_build.infrastructure import ImageBuildClient


def image_build_service():
    return ImageBuildService(client=ImageBuildClient(), admission=VmMutationAdmission(recovery_kind='vm_image_build_observation'),
        operations=SqlAlchemyOperationStore(), recovery=SqlAlchemyRecoveryStore(),
        cluster_id=str(os.getenv('GJALLAR_CLUSTER_ID') or 'gjallar-mvp').strip())
