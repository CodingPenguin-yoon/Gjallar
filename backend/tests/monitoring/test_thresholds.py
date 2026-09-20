import pytest
from app.monitoring.domain import Target
from app.monitoring.thresholds import threshold_report, classify, RULES
from app.monitoring.operation_alerts import project_failures, operation_alerts


def thresholds(values, **kwargs):
    target = kwargs.pop('target', Target('vm', 'node1', vmid=40000))
    history = {'available': True, 'resolution_seconds': 60,
        'points': [{'timestamp': i * 60, 'values': {'cpu_percent': value}} for i, value in enumerate(values)],
        'metrics': {'cpu_percent': {'stale': kwargs.pop('stale', False)}}}
    return threshold_report(target, {'available': True, 'values': {'cpu_percent': values[-1] if values else None}}, history, **kwargs)


@pytest.mark.parametrize('value,state', [(69.99, 'normal'), (70, 'warning'), (84.99, 'warning'), (85, 'critical'), (None, 'unknown')])
def test_threshold_boundaries(value, state):
    assert classify({'cpu_percent': value}, RULES['cpu'])[0] == state


def test_memory_storage_ratios_and_missing_denominator():
    assert classify({'memory_used_bytes': 85, 'memory_total_bytes': 100}, RULES['memory'])[0] == 'critical'
    assert classify({'used_bytes': 80, 'total_bytes': 100}, RULES['storage'])[0] == 'warning'
    assert classify({'used_bytes': 90, 'total_bytes': 100}, RULES['storage'])[0] == 'critical'
    for total in (0, None, '100', float('nan')):
        assert classify({'used_bytes': 90, 'total_bytes': total}, RULES['storage'])[0] == 'unknown'
    assert classify({'used_bytes': 1e308, 'total_bytes': 1e-308}, RULES['storage'])[0] == 'unknown'


def test_contiguous_samples_merge_and_severity_change_is_not_new_occurrence():
    report = thresholds([10, 70, 70, 90, 80, 10])
    interval, = report['intervals']
    assert interval['onset_confirmed'] and interval['first_observed_at'] == 60
    assert interval['state'] == 'cleared' and interval['cleared_observed_at'] == 300
    assert interval['maximum_severity'] == 'critical'
    assert len(interval['severity_changes']) == 2
    assert report['rules'][0]['history_state'] == 'normal'


def test_unknown_does_not_clear_and_first_high_onset_is_uncertain():
    report = thresholds([90, None, 90, None])
    interval, = report['intervals']
    assert not interval['onset_confirmed'] and interval['has_observation_gaps']
    assert interval['state'] == 'unknown' and interval['cleared_observed_at'] is None
    assert report['rules'][0]['current_state'] == 'unknown'
    cleared = thresholds([90, None, 10])['intervals'][0]
    assert cleared['cleared_observed_at'] == 120 and cleared['has_observation_gaps']


def test_stale_never_claims_current_history_status_and_ids_are_stable_per_target():
    first = thresholds([10, 90], stale=True)
    assert first['rules'][0]['history_state'] == 'unknown' and first['intervals'][0]['state'] == 'unknown'
    assert first['intervals'][0]['id'] == thresholds([10, 90])['intervals'][0]['id']
    assert first['intervals'][0]['id'] != thresholds([10, 90], target=Target('vm', 'node1', vmid=40001))['intervals'][0]['id']


def test_bounded_intervals_and_severity_changes():
    report = thresholds([10, 90]*120, limit=100)
    assert report['truncated'] and len(report['intervals']) == 100 and report['interval_count'] == 120
    interval, = thresholds([75, 90]*40)['intervals']
    assert interval['severity_changes_truncated'] and len(interval['severity_changes']) == 20


def detail(statuses, **extra):
    return {'operation': {'operation_id': 'operation-one', 'operation_type': 'vm_compute', 'status': statuses[-1],
                         'target_type': 'proxmox_vm', 'target_id': 'vmid:40000'},
            'events': [{'sequence': i+1, 'created_at': f'2026-09-19T00:00:0{i}Z', 'to_status': status,
                        'payload': {'secret': 'never-expose'}} for i, status in enumerate(statuses)], **extra}


def test_operation_failure_then_recovery_and_duplicate_events():
    alerts = project_failures(detail(['planned', 'dispatching', 'needs_reconciliation', 'needs_reconciliation', 'succeeded']))
    assert len(alerts) == 1 and alerts[0]['state'] == 'cleared'
    assert alerts[0]['first_observed_at'].endswith('02Z') and alerts[0]['cleared_observed_at'].endswith('04Z')
    assert 'never-expose' not in repr(alerts)
    assert project_failures(detail(['planned', 'blocked'])) == []
    assert project_failures(detail(['needs_reconciliation'], coordination_incomplete=True))[0]['state'] == 'needs_observation'


def test_operation_query_limit_and_mismatched_detail_are_explicit():
    report = operation_alerts(1, list_fn=lambda **_: [{'operation_id': 'other'}], get_fn=lambda _: detail(['failed']))
    assert report['possibly_truncated'] and report['unavailable_operations'] == ['other'] and report['alerts'] == []


def test_operation_alerts_cap_intervals_and_preserve_partial_failures():
    from sqlalchemy.exc import SQLAlchemyError
    def read(operation_id):
        if operation_id == 'unavailable': raise SQLAlchemyError('secret database error')
        return detail(['failed', 'succeeded'] * 110)
    report = operation_alerts(2, list_fn=lambda **_: [{'operation_id': 'operation-one'}, {'operation_id': 'unavailable'}], get_fn=read)
    assert report['alerts_truncated'] and report['alert_count'] == 110 and len(report['alerts']) == 100
    assert report['unavailable_operations'] == ['unavailable']
    assert 'secret' not in repr(report)
