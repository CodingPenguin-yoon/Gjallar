"""Request a bounded read-only preparation report; never dispatch any action."""
from urllib.parse import urlencode
from .errors import ClientError
from .workflows import identifier, segment


def show(app, *, node, destination=None, backup_storage=None, backup_max_age_hours=24, check_limit=10):
    identifier(node)
    for value in (destination, backup_storage):
        if value is not None:
            identifier(value)
    if (node == destination or type(backup_max_age_hours) is not int or not 1 <= backup_max_age_hours <= 720
            or type(check_limit) is not int or not 1 <= check_limit <= 20):
        raise ClientError('MAINTENANCE_INPUT_INVALID', '서로 다른 node·최근 백업 시간·검사 개수를 확인하세요.', 2)
    query = {'backup_max_age_hours': backup_max_age_hours, 'check_limit': check_limit}
    if destination is not None: query['destination_node'] = destination
    if backup_storage is not None: query['backup_storage'] = backup_storage
    result = app.request(f'maintenance/nodes/{segment(node)}?' + urlencode(query), operator=True)
    report = result['data']
    if (report.get('node_id') != node or report.get('destination_node') != destination or report.get('backup_storage') != backup_storage
            or report.get('backup_max_age_hours') != backup_max_age_hours or report.get('check_limit') != check_limit
            or report.get('read_only') is not True or report.get('node_shutdown_safe') is not False):
        raise ClientError('MAINTENANCE_REPORT_UNCONFIRMED', '요청한 대상·조회 범위의 준비 보고서인지 확인할 수 없습니다.', 8)
    return result
