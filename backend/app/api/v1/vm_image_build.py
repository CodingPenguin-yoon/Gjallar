"""Review a future VM target and build a pinned official cloud-image template."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.api.v1.responses import success_response
from app.auth.dependencies import require_operator
from app.auth.roles import AuthenticatedUser, actor_evidence
from app.cloud_images.catalog import CATALOG, ImageError
from app.cloud_images.contracts import BuildInput, BuildRequest
from app.operations.core.domain import OperationIntentConflict
from app.operations.locks.domain import DurableTargetLockBusy
from app.operations.recovery.domain import RecoveryLeaseLost
from app.operations.vm_image_build.facade import image_build_service

router = APIRouter()


def invoke(action, **kwargs):
    try:
        return getattr(image_build_service(), action)(**kwargs)
    except ImageError as exc:
        raise HTTPException(exc.status_code, detail=exc.to_detail()) from None
    except OperationIntentConflict:
        raise HTTPException(409, detail={'code': 'IMAGE_BUILD_IDEMPOTENCY_CONFLICT', 'message': '요청 ID가 다른 제작에 사용됐습니다.'}) from None
    except DurableTargetLockBusy as exc:
        reason = exc.existing.get('reason', 'IMAGE_BUILD_TARGET_BUSY')
        raise HTTPException(403 if reason == 'SETUP_FEATURE_NOT_SELECTED' else 409,
            detail={'code': reason, 'message': '연결 권한 또는 진행 중인 대상 작업을 확인하세요.'}) from None
    except (SQLAlchemyError, RecoveryLeaseLost):
        raise HTTPException(503, detail={'code': 'IMAGE_BUILD_PERSISTENCE_UNAVAILABLE',
            'message': '작업 기록·잠금을 확인하지 못했습니다. 원래 요청 ID의 Operation을 확인하고 다시 실행하지 마세요.'}) from None


@router.get('/templates/cloud-images')
async def cloud_image_catalog(actor: AuthenticatedUser = Depends(require_operator)):
    return success_response({'images': [image.public() for image in CATALOG.values()]})


@router.get('/nodes/{node_id}/vms/{vmid}/image-build')
async def review_image_build(node_id: str, vmid: int, image_id: str, name: str, storage_id: str,
                             staging_storage_id: str, bridge_id: str, actor: AuthenticatedUser = Depends(require_operator)):
    try:
        request = BuildInput(image_id=image_id, name=name, storage_id=storage_id, staging_storage_id=staging_storage_id, bridge_id=bridge_id)
    except ValidationError:
        raise HTTPException(422, detail={'code': 'IMAGE_BUILD_INVALID_INPUT', 'message': '공식 이미지·이름·storage·bridge 입력을 확인하세요.'}) from None
    return success_response(await run_in_threadpool(invoke, 'review', node_id=node_id, vmid=vmid, request=request))


@router.post('/nodes/{node_id}/vms/{vmid}/actions/image-build')
async def execute_image_build(node_id: str, vmid: int, payload: BuildRequest, actor: AuthenticatedUser = Depends(require_operator)):
    return success_response(await run_in_threadpool(invoke, 'execute', node_id=node_id, vmid=vmid,
                                                   request=payload, actor=actor_evidence(actor)))
