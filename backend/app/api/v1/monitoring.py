"""Read-only resource metrics under authenticated viewer access."""
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from app.api.v1.responses import success_response
from app.monitoring.domain import MonitoringError, Target
from app.monitoring.proxmox import monitoring_service
from app.monitoring.operation_alerts import operation_alerts

router = APIRouter()
Timeframe = Literal['hour', 'day', 'week', 'month', 'year']


@router.get('/monitoring/operation-alerts')
def get_operation_alerts(limit: int = Query(default=20, ge=1, le=50)):
    try:
        return success_response(operation_alerts(limit))
    except MonitoringError as exc:
        raise HTTPException(exc.status_code, detail={'code': exc.code, 'message': exc.message}) from None


def query(kind, node_id, timeframe, **kwargs):
    try:
        target = Target(kind, node_id, **kwargs)
        return success_response(monitoring_service().query(target, timeframe))
    except MonitoringError as exc:
        raise HTTPException(exc.status_code, detail={'code': exc.code, 'message': exc.message}) from None


@router.get('/monitoring/nodes/{node_id}')
def node_metrics(node_id: str, timeframe: Timeframe = 'hour'):
    return query('node', node_id, timeframe)


@router.get('/monitoring/nodes/{node_id}/vms/{vmid}')
def vm_metrics(node_id: str, vmid: int, timeframe: Timeframe = 'hour'):
    return query('vm', node_id, timeframe, vmid=vmid)


@router.get('/monitoring/nodes/{node_id}/storage/{storage_id}')
def storage_metrics(node_id: str, storage_id: str, timeframe: Timeframe = 'hour'):
    return query('storage', node_id, timeframe, storage_id=storage_id)
