"""Authenticated review and execution of stopped VM compute changes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.api.v1.responses import success_response
from app.auth.dependencies import require_operator
from app.auth.roles import AuthenticatedUser, actor_evidence
from app.operations.core.domain import OperationIntentConflict
from app.operations.locks.domain import DurableTargetLockBusy
from app.operations.recovery.domain import RecoveryLeaseLost
from app.operations.vm_compute.domain import ComputeError, ComputeRequest
from app.operations.vm_compute.facade import compute_service

router = APIRouter()


def _invoke(action, **kwargs):
    try:
        return getattr(compute_service(), action)(**kwargs)
    except ComputeError as exc:
        raise HTTPException(exc.status_code, detail=exc.to_detail()) from None
    except OperationIntentConflict:
        raise HTTPException(409, detail={"code": "VM_COMPUTE_IDEMPOTENCY_CONFLICT", "message": "요청 ID가 다른 변경에 사용됐습니다."}) from None
    except DurableTargetLockBusy as exc:
        reason = exc.existing.get("reason", "VM_COMPUTE_TARGET_BUSY")
        raise HTTPException(403 if reason == "SETUP_FEATURE_NOT_SELECTED" else 409,
                            detail={"code": reason, "message": "연결 권한 또는 대상의 진행 중 작업을 확인하세요."}) from None
    except (SQLAlchemyError, RecoveryLeaseLost):
        raise HTTPException(503, detail={"code": "VM_COMPUTE_PERSISTENCE_UNAVAILABLE",
            "message": "작업 기록·복구 권한을 확인하지 못했습니다. 같은 요청 ID의 Operation을 확인하고 자동 재실행하지 마세요."}) from None


@router.get("/nodes/{node_id}/vms/{vmid}/compute")
async def review_compute(node_id: str, vmid: int, actor: AuthenticatedUser = Depends(require_operator)):
    return success_response(await run_in_threadpool(_invoke, "review", node_id=node_id, vmid=vmid))


@router.post("/nodes/{node_id}/vms/{vmid}/actions/compute")
async def execute_compute(node_id: str, vmid: int, payload: ComputeRequest,
                          actor: AuthenticatedUser = Depends(require_operator)):
    return success_response(await run_in_threadpool(_invoke, "execute", node_id=node_id, vmid=vmid,
                                                   request=payload, actor=actor_evidence(actor)))
