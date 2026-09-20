"""Read-time threshold intervals over PVE-owned averages, without persistence."""
import hashlib
import json
from app.monitoring.domain import number

RULE_VERSION = 'pve-average-threshold.v1'
RULES = {
    'cpu': {'label': 'CPU 사용률', 'value': 'cpu_percent', 'total': None, 'warning': 70, 'critical': 85},
    'memory': {'label': '메모리 사용률', 'value': 'memory_used_bytes', 'total': 'memory_total_bytes', 'warning': 70, 'critical': 85},
    'storage': {'label': 'Storage 사용률', 'value': 'used_bytes', 'total': 'total_bytes', 'warning': 80, 'critical': 90},
}


def classify(values, rule):
    value = number(values.get(rule['value']))
    if rule['total']:
        total = number(values.get(rule['total']))
        value = number(value / total * 100) if value is not None and total is not None and total > 0 else None
    state = ('unknown' if value is None else 'critical' if value >= rule['critical']
             else 'warning' if value >= rule['warning'] else 'normal')
    return state, value


def threshold_report(target, current, history, *, limit=100):
    keys = ['storage'] if target.kind == 'storage' else ['cpu', 'memory']
    resolution = history.get('resolution_seconds')
    available = history.get('available') is True and resolution is not None
    rules = []
    all_intervals = []
    for key in keys:
        rule = RULES[key]
        current_state, current_value = classify(current.get('values', {}) if current.get('available') else {}, rule)
        intervals = []
        active = None
        previous_state, previous_time = 'unknown', None
        for point in history.get('points', []) if available else []:
            state, value = classify(point['values'], rule)
            stamp = point['timestamp']
            gap = previous_time is not None and stamp - previous_time > resolution * 1.5
            if gap or state == 'unknown':
                if active: active['has_observation_gaps'] = True
            if state == 'unknown':
                previous_state, previous_time = state, stamp
                continue
            if state == 'normal':
                if active:
                    active['cleared_observed_at'] = stamp
                    active['state'] = 'cleared'
                    active = None
            else:
                if active is None:
                    identity = json.dumps([target.to_dict(), RULE_VERSION, key, stamp], sort_keys=True)
                    active = {'id': 'threshold-' + hashlib.sha256(identity.encode()).hexdigest()[:24],
                        'rule': key, 'label': rule['label'], 'first_observed_at': stamp, 'last_high_observed_at': stamp,
                        'cleared_observed_at': None, 'state': 'open', 'last_severity': state,
                        'maximum_severity': state, 'latest_percent': value,
                        'onset_confirmed': previous_state == 'normal' and not gap,
                        'has_observation_gaps': False, 'severity_changes': [], 'severity_changes_truncated': False}
                    intervals.append(active)
                elif active['last_severity'] != state:
                    active['severity_changes'].append({'observed_at': stamp, 'severity': state})
                    if len(active['severity_changes']) > 20:
                        active['severity_changes'] = active['severity_changes'][-20:]
                        active['severity_changes_truncated'] = True
                active.update(last_high_observed_at=stamp, last_severity=state, latest_percent=value)
                if state == 'critical': active['maximum_severity'] = 'critical'
            previous_state, previous_time = state, stamp
        source_keys = [rule['value']] + ([rule['total']] if rule['total'] else [])
        latest_unknown = previous_state == 'unknown' or any(history.get('metrics', {}).get(metric, {}).get('stale', True) for metric in source_keys)
        if active and latest_unknown: active['state'] = 'unknown'
        rules.append({'key': key, 'label': rule['label'], 'warning_percent': rule['warning'],
                      'critical_percent': rule['critical'], 'current_state': current_state, 'current_percent': current_value,
                      'history_state': 'unknown' if not available or latest_unknown else previous_state})
        all_intervals.extend(intervals)
    all_intervals.sort(key=lambda row: (row['first_observed_at'], row['rule']), reverse=True)
    return {'rule_version': RULE_VERSION, 'rules': rules, 'history_available': available,
            'intervals': all_intervals[:limit], 'interval_count': len(all_intervals), 'truncated': len(all_intervals) > limit,
            'retention': 'PVE가 현재 제공하는 선택 기간의 평균 이력만 사용합니다. 별도 알림 이력을 저장하지 않습니다.',
            'limitation': '표본 사이의 순간 초과·정확한 발생/해제 시각은 알 수 없습니다. 결측은 정상/해제로 처리하지 않습니다.'}
