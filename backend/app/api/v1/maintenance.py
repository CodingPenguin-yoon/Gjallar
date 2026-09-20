"""Operator preparation report; GET-only and never a node shutdown authorization."""
from fastapi import APIRouter, Depends, HTTPException, Query
from app.api.v1.responses import success_response
from app.auth.dependencies import require_operator
from app.maintenance.application import MaintenanceError
from app.maintenance.facade import maintenance_service

router = APIRouter()


@router.get('/maintenance/nodes/{node_id}', dependencies=[Depends(require_operator)])
def node_maintenance(node_id: str, destination_node: str | None = None, backup_storage: str | None = None,
                     backup_max_age_hours: int = Query(default=24, ge=1, le=720), check_limit: int = Query(default=10, ge=1, le=20)):
    try:
        return success_response(maintenance_service().report(node_id=node_id, destination_node=destination_node,
            backup_storage=backup_storage, backup_max_age_hours=backup_max_age_hours, check_limit=check_limit))
    except MaintenanceError as exc:
        raise HTTPException(exc.status_code, detail={'code': exc.code, 'message': str(exc)}) from None
