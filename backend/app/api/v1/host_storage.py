"""Admin review and execution of cluster directory storage configuration."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from app.api.v1.responses import success_response
from app.auth.dependencies import require_admin
from app.auth.roles import AuthenticatedUser, actor_evidence
from app.operations.core.domain import OperationIntentConflict
from app.operations.locks.domain import DurableTargetLockBusy
from app.operations.recovery.domain import RecoveryLeaseLost, RecoveryOperationConflict
from app.operations.host_storage.domain import StorageChange, StorageRequest, StorageError
from app.operations.host_storage.facade import storage_service

router = APIRouter()


def _invoke(action, **kwargs):
    try:
        return getattr(storage_service(),action)(**kwargs)
    except StorageError as exc:
        raise HTTPException(exc.status_code,detail=exc.to_detail()) from None
    except OperationIntentConflict:
        raise HTTPException(409,detail={'code':'HOST_STORAGE_IDEMPOTENCY_CONFLICT','message':'요청 ID가 다른 변경에 사용됐습니다.'}) from None
    except DurableTargetLockBusy as exc:
        reason = exc.existing.get('reason','HOST_CONFIGURATION_TARGET_BUSY')
        raise HTTPException(403 if reason in {'SETUP_FEATURE_NOT_SELECTED','SETUP_TARGET_NOT_SELECTED'} else 409,
            detail={'code':reason,'message':'연결 권한과 진행 중인 VM·호스트 작업을 확인하세요.'}) from None
    except (SQLAlchemyError,RecoveryLeaseLost,RecoveryOperationConflict):
        raise HTTPException(503,detail={'code':'HOST_STORAGE_PERSISTENCE_UNAVAILABLE',
            'message':'작업 기록·잠금을 확인하지 못했습니다. 같은 요청 ID의 Operation을 확인하세요.'}) from None


@router.post('/nodes/{node_id}/host-storage/{storage_id}/review')
async def review_storage(node_id: str, storage_id: str, payload: StorageChange,
                         actor: AuthenticatedUser = Depends(require_admin)):
    return success_response(await run_in_threadpool(_invoke,'review',node_id=node_id,storage_id=storage_id,change=payload))


@router.post('/nodes/{node_id}/host-storage/{storage_id}/actions/configure')
async def configure_storage(node_id: str, storage_id: str, payload: StorageRequest,
                             actor: AuthenticatedUser = Depends(require_admin)):
    return success_response(await run_in_threadpool(_invoke,'execute',node_id=node_id,storage_id=storage_id,
        request=payload,actor=actor_evidence(actor)))
