"""Historical template deployment report; no Proxmox calls or mutation."""
from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.responses import success_response
from app.operations.facade import OperationQueryNotFound
from app.vm_actions.post_create_readiness import PostCreateReadinessError
from app.vm_actions.template_test import template_test_report

router = APIRouter()


@router.get('/operations/{operation_id}/template-test')
def get_template_test_report(operation_id: str):
    try:
        return success_response(template_test_report(operation_id))
    except PostCreateReadinessError as exc:
        raise HTTPException(exc.status_code, detail=exc.to_detail()) from None
    except OperationQueryNotFound:
        raise HTTPException(404, detail={'code': 'OPERATION_NOT_FOUND', 'message': '생성 작업을 찾을 수 없습니다.'}) from None
    except SQLAlchemyError:
        raise HTTPException(503, detail={'code': 'TEMPLATE_TEST_PERSISTENCE_UNAVAILABLE', 'message': '배포 검사 기록을 읽을 수 없습니다.'}) from None
