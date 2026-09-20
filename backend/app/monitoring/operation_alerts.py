"""Bounded failure/recovery history from existing exact Operation events."""
from sqlalchemy.exc import SQLAlchemyError
from app.operations.facade import get_operation, list_operations, OperationQueryNotFound
from app.monitoring.domain import MonitoringError

FAILURE_STATUSES = {'failed', 'needs_reconciliation'}


def project_failures(detail):
    operation = detail['operation']
    alerts = []
    active = None
    for event in detail.get('events', []):
        status = event.get('to_status')
        if status in FAILURE_STATUSES:
            if active is None:
                active = {'id': f"operation-alert:{operation['operation_id']}:{event['sequence']}",
                    'operation_id': operation['operation_id'], 'operation_type': operation['operation_type'],
                    'target_type': operation.get('target_type'), 'target_id': operation.get('target_id'),
                    'first_observed_at': event['created_at'], 'cleared_observed_at': None,
                    'state': 'open', 'status': status}
                alerts.append(active)
            active['status'] = status
        elif status == 'succeeded' and active is not None:
            active.update(state='cleared', cleared_observed_at=event['created_at'])
            active = None
    if active and detail.get('coordination_incomplete'):
        active['state'] = 'needs_observation'
    return alerts


def operation_alerts(limit=20, *, list_fn=list_operations, get_fn=get_operation):
    if type(limit) is not int or not 1 <= limit <= 50:
        raise MonitoringError('MONITORING_LIMIT_INVALID', '작업 조회 개수는 1~50이어야 합니다.', 422)
    try:
        operations = list_fn(limit=limit)
    except SQLAlchemyError:
        raise MonitoringError('MONITORING_OPERATIONS_UNAVAILABLE', '작업 이력을 조회하지 못했습니다.', 503) from None
    alerts, unavailable = [], []
    for operation in operations:
        operation_id = operation['operation_id']
        try:
            detail = get_fn(operation_id)
        except (SQLAlchemyError, OperationQueryNotFound):
            unavailable.append(operation_id)
            continue
        if detail.get('operation', {}).get('operation_id') != operation_id:
            unavailable.append(operation_id)
            continue
        alerts.extend(project_failures(detail))
    alerts.sort(key=lambda row: (row['first_observed_at'], row['id']), reverse=True)
    return {'alerts': alerts[:100], 'alert_count': len(alerts), 'alerts_truncated': len(alerts) > 100,
            'inspected_operations': len(operations), 'limit': limit,
            'possibly_truncated': len(operations) == limit, 'unavailable_operations': unavailable,
            'source': 'operation_events', 'read_only': True,
            'limitation': '최신 작업의 기록된 failed/needs_reconciliation과 이후 succeeded만 표시합니다. 사전 차단·미기록 외부 작업은 포함하지 않습니다.'}
