"""Review and explicitly remove completed image-build owned resources."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.api.v1.responses import success_response
from app.auth.dependencies import require_operator
from app.auth.roles import AuthenticatedUser, actor_evidence
from app.cloud_images.catalog import ImageError
from app.operations.core.domain import OperationIntentConflict
from app.operations.locks.domain import DurableTargetLockBusy
from app.operations.recovery.domain import RecoveryLeaseLost
from app.operations.vm_image_cleanup.domain import CleanupRequest
from app.operations.vm_image_cleanup.facade import image_cleanup_service

router = APIRouter()


def invoke(action, **kwargs):
    try:
        return getattr(image_cleanup_service(), action)(**kwargs)
    except ImageError as exc:
        raise HTTPException(exc.status_code, detail=exc.to_detail()) from None
    except OperationIntentConflict:
        raise HTTPException(409, detail={'code': 'IMAGE_CLEANUP_IDEMPOTENCY_CONFLICT', 'message': '요청 ID가 다른 정리에 사용됐습니다.'}) from None
    except DurableTargetLockBusy as exc:
        reason = exc.existing.get('reason', 'IMAGE_CLEANUP_TARGET_BUSY')
        raise HTTPException(403 if reason == 'SETUP_FEATURE_NOT_SELECTED' else 409,
            detail={'code': reason, 'message': '정리 권한 또는 진행 중인 대상 작업을 확인하세요.'}) from None
    except (SQLAlchemyError, RecoveryLeaseLost):
        raise HTTPException(503, detail={'code': 'IMAGE_CLEANUP_PERSISTENCE_UNAVAILABLE',
            'message': '작업 기록·잠금을 확인하지 못했습니다. 원래 요청 ID를 보존하고 새 삭제를 실행하지 마세요.'}) from None


@router.get('/nodes/{node_id}/vms/{vmid}/image-cleanup')
async def review_image_cleanup(node_id: str, vmid: int, parent_operation_id: str, resource: str,
                               actor: AuthenticatedUser = Depends(require_operator)):
    return success_response(await run_in_threadpool(invoke, 'review', node_id=node_id, vmid=vmid,
                                                   parent_operation_id=parent_operation_id, resource=resource))


@router.post('/nodes/{node_id}/vms/{vmid}/actions/image-cleanup')
async def execute_image_cleanup(node_id: str, vmid: int, payload: CleanupRequest,
                                actor: AuthenticatedUser = Depends(require_operator)):
    return success_response(await run_in_threadpool(invoke, 'execute', node_id=node_id, vmid=vmid,
                                                   request=payload, actor=actor_evidence(actor)))
