"""Read the same bounded metrics report as the web interface."""
from urllib.parse import urlencode
from .errors import ClientError
from .workflows import identifier, segment


def show(app, *, kind, node, resource=None, timeframe='hour'):
    identifier(node)
    if kind not in {'node', 'vm', 'storage'} or timeframe not in {'hour', 'day', 'week', 'month', 'year'}:
        raise ClientError('METRICS_INPUT_INVALID', '지원 자원 종류·기간을 선택하세요.', 2)
    path = f'monitoring/nodes/{segment(node)}'
    if kind == 'vm':
        if type(resource) is not int or not 100 <= resource <= 999999999:
            raise ClientError('METRICS_INPUT_INVALID', 'VMID를 확인하세요.', 2)
        path += f'/vms/{resource}'
    elif kind == 'storage':
        identifier(resource)
        path += f'/storage/{segment(resource)}'
    return app.request(path + '?' + urlencode({'timeframe': timeframe}))
