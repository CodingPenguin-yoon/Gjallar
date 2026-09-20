"""Bounded metrics with explicit missing values and source timestamps."""
from dataclasses import dataclass
from datetime import datetime, timezone
import math
import re

TIMEFRAMES = ('hour', 'day', 'week', 'month', 'year')
METRICS = {
    'node': [('cpu_percent', 'CPU', '%', 'cpu', 100), ('memory_used_bytes', '메모리 사용', 'bytes', 'memused', 1),
             ('memory_total_bytes', '메모리 전체', 'bytes', 'memtotal', 1),
             ('network_in_bytes_per_second', '네트워크 수신', 'bytes/s', 'netin', 1), ('network_out_bytes_per_second', '네트워크 송신', 'bytes/s', 'netout', 1)],
    'vm': [('cpu_percent', 'CPU', '%', 'cpu', 100), ('memory_used_bytes', '게스트 메모리 사용', 'bytes', 'mem', 1),
           ('memory_total_bytes', '메모리 한도', 'bytes', 'maxmem', 1),
           ('network_in_bytes_per_second', '네트워크 수신', 'bytes/s', 'netin', 1), ('network_out_bytes_per_second', '네트워크 송신', 'bytes/s', 'netout', 1),
           ('disk_read_bytes_per_second', '디스크 읽기', 'bytes/s', 'diskread', 1), ('disk_write_bytes_per_second', '디스크 쓰기', 'bytes/s', 'diskwrite', 1)],
    'storage': [('used_bytes', '공간 사용', 'bytes', 'used', 1), ('total_bytes', '공간 전체', 'bytes', 'total', 1)],
}


class MonitoringError(RuntimeError):
    def __init__(self, code, message, status_code=502):
        self.code, self.message, self.status_code = code, message, status_code
        super().__init__(message)


@dataclass(frozen=True)
class Target:
    kind: str
    node_id: str
    vmid: int | None = None
    storage_id: str | None = None

    def __post_init__(self):
        identifier = r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}'
        if self.kind not in METRICS or not re.fullmatch(identifier, self.node_id):
            raise MonitoringError('MONITORING_TARGET_INVALID', '조회할 자원 종류와 노드를 확인하세요.', 422)
        if ((self.kind == 'vm' and (type(self.vmid) is not int or not 100 <= self.vmid <= 999999999))
                or (self.kind != 'vm' and self.vmid is not None)
                or (self.kind == 'storage' and (not isinstance(self.storage_id, str) or not re.fullmatch(identifier, self.storage_id)))
                or (self.kind != 'storage' and self.storage_id is not None)):
            raise MonitoringError('MONITORING_TARGET_INVALID', '선택 자원의 정확한 식별자를 확인하세요.', 422)

    def to_dict(self):
        return {key: value for key, value in vars(self).items() if value is not None}


def number(value):
    if type(value) not in (float, int): return None
    try:
        return float(value) if math.isfinite(value) and value >= 0 else None
    except OverflowError:
        return None


def values(kind, row):
    result = {}
    for key, _label, _unit, source, multiplier in METRICS[kind]:
        value = number(row.get(source))
        result[key] = value * multiplier if value is not None and (source != 'cpu' or value <= 1) else None
    return result


def descriptors(kind):
    return [{'key': key, 'label': label, 'unit': unit} for key, label, unit, _, _ in METRICS[kind]]


def current_metrics(kind, row, *, received_at):
    if not isinstance(row, dict) or not row:
        raise MonitoringError('MONITORING_CURRENT_INVALID', '현재 상태 응답을 확인할 수 없습니다.')
    if kind == 'node':
        memory = row.get('memory') if isinstance(row.get('memory'), dict) else {}
        source = {'cpu': row.get('cpu'), 'memused': memory.get('used'), 'memtotal': memory.get('total')}
    elif kind == 'vm':
        source = {key: row.get(key) for key in ('cpu', 'mem', 'maxmem')}
        if row.get('status') != 'running': source.update(cpu=None, mem=None)
    else:
        source = row if row.get('active') == 1 else {}
    data = values(kind, source)
    return {'available': True, 'received_at': received_at, 'source': 'pve_status',
            'status': row.get('status') if kind == 'vm' else 'active' if kind == 'storage' and row.get('active') == 1 else None,
            'values': data, 'missing_metrics': [key for key, value in data.items() if value is None],
            'limitation': '수신 시점의 상태입니다. 현재 IO 누적 카운터를 초당 속도로 표시하지 않습니다.'}


def history_metrics(kind, rows, *, received_at, now):
    if not isinstance(rows, list) or len(rows) > 10000:
        raise MonitoringError('MONITORING_HISTORY_INVALID', 'PVE 이력 응답 형식·크기 제한을 확인하세요.')
    points = []
    previous = -1
    for row in rows:
        stamp = number(row.get('time')) if isinstance(row, dict) else None
        if stamp is None or stamp != int(stamp) or stamp <= previous or stamp > now + 300:
            raise MonitoringError('MONITORING_HISTORY_INVALID', 'PVE 이력 시각이 누락·중복되었거나 올바르지 않습니다.')
        previous = stamp
        points.append({'timestamp': int(stamp), 'values': values(kind, row)})
    steps = sorted({right['timestamp'] - left['timestamp'] for left, right in zip(points, points[1:])})
    resolution = steps[0] if len(steps) == 1 else None
    summary = {}
    for metric in descriptors(kind):
        observed = [row for row in points if row['values'][metric['key']] is not None]
        last = observed[-1]['timestamp'] if observed else None
        summary[metric['key']] = {'observed_points': len(observed), 'missing_points': len(points) - len(observed),
                                  'latest_value_at': last,
                                  'stale': last is None or resolution is None or now - last > resolution * 2 + 60}
    return {'available': True, 'source': 'pve_rrd', 'received_at': received_at, 'aggregation': 'AVERAGE',
            'start': points[0]['timestamp'] if points else None, 'end': points[-1]['timestamp'] if points else None,
            'resolution_seconds': resolution, 'observed_steps_seconds': steps, 'points': points, 'metrics': summary,
            'state': 'observed' if any(row['observed_points'] for row in summary.values()) else 'no_data'}


def now_utc():
    return datetime.now(timezone.utc)
