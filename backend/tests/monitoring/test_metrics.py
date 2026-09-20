from datetime import datetime, timezone
import pytest
from app.monitoring.domain import Target, MonitoringError, current_metrics, history_metrics
from app.monitoring.application import MonitoringService
from app.monitoring.proxmox import MonitoringClient
from app.proxmox.client import ProxmoxMutationClient, ProxmoxMutationError
from app.setup_integration.contracts import SetupError

NOW = datetime(2026, 9, 19, tzinfo=timezone.utc)


def history(rows, kind='vm'):
    return history_metrics(kind, rows, received_at=NOW.isoformat(), now=NOW.timestamp())


def test_history_units_zeros_and_missing_are_distinct():
    result = history([{'time': NOW.timestamp()-120, 'cpu': 0, 'mem': 1024, 'netin': 12},
                      {'time': NOW.timestamp()-60, 'cpu': 0.5, 'mem': None, 'diskread': 3}])
    assert result['resolution_seconds'] == 60
    assert result['points'][0]['values']['cpu_percent'] == 0
    assert result['points'][1]['values']['cpu_percent'] == 50
    assert result['points'][1]['values']['memory_used_bytes'] is None
    assert result['points'][0]['values']['network_in_bytes_per_second'] == 12
    assert result['metrics']['memory_used_bytes']['missing_points'] == 1
    assert not result['metrics']['cpu_percent']['stale']
    assert result['metrics']['network_out_bytes_per_second']['stale']


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1, True, '0.5', 10**1000, {}, []])
def test_invalid_metric_is_missing_not_zero(value):
    assert history([{'time': NOW.timestamp()-60, 'cpu': value}])['points'][0]['values']['cpu_percent'] is None


@pytest.mark.parametrize('rows', [None, {}, [None], [{}], [{'time': True}], [{'time': 2}, {'time': 2}],
    [{'time': 3}, {'time': 2}], [{'time': 1.5}], [{'time': NOW.timestamp()+301}], [{}]*10001])
def test_invalid_time_and_unbounded_series_are_rejected(rows):
    with pytest.raises(MonitoringError): history(rows)


def test_no_data_irregular_resolution_and_old_metrics():
    assert history([])['state'] == 'no_data'
    result = history([{'time': 1, 'cpu': 0.1}, {'time': 61}, {'time': 181}])
    assert result['resolution_seconds'] is None and result['observed_steps_seconds'] == [60, 120]
    assert result['metrics']['cpu_percent']['stale']


def test_current_counters_are_not_rates_and_stopped_is_not_zero():
    current = current_metrics('vm', {'status': 'stopped', 'cpu': 0, 'mem': 0, 'maxmem': 2048, 'netin': 9000}, received_at='now')
    assert current['values']['cpu_percent'] is None and current['values']['memory_used_bytes'] is None
    assert current['values']['memory_total_bytes'] == 2048
    assert current['values']['network_in_bytes_per_second'] is None
    assert current_metrics('node', {'cpu': 0.2, 'memory': {'used': 30, 'total': 100}}, received_at='now')['values']['cpu_percent'] == 20
    assert current_metrics('storage', {'used': 0, 'total': 100, 'active': 1}, received_at='now')['values']['used_bytes'] == 0


@pytest.mark.parametrize('target', [('node', '../node', None, None), ('vm', 'node1', True, None),
    ('storage', 'node1', None, '../store'), ('node', 'node1', 100, None), ('bad', 'node1', None, None)])
def test_target_input_is_narrow(target):
    with pytest.raises(MonitoringError): Target(*target)


def test_partial_outage_still_returns_available_history():
    class Client:
        def current(self, target): raise MonitoringError('UNAVAILABLE', '조회 불가')
        def history(self, target, timeframe): return [{'time': NOW.timestamp()-60, 'used': 0, 'total': 100}]
    report = MonitoringService(Client(), clock=lambda: NOW).query(Target('storage', 'node1', storage_id='store1'))
    assert report['partial'] and not report['current']['available'] and report['history']['available']
    assert 'values' not in report['current']


def test_adapter_uses_get_only_and_preserves_permission_denial():
    calls = []
    def request(method, path, **kwargs):
        calls.append((method, path))
        if len(calls) > 2: raise SetupError('SETUP_TARGET_NOT_SELECTED', '범위 밖', 403)
        return {}
    client = MonitoringClient(ProxmoxMutationClient(api_url='https://fixture', token_id='fixture', token_secret='fixture', request=request))
    client.current(Target('vm', 'node1', vmid=40000))
    client.history(Target('storage', 'node1', storage_id='store1'), 'day')
    assert calls == [('GET', '/nodes/node1/qemu/40000/status/current'), ('GET', '/nodes/node1/storage/store1/rrddata?timeframe=day&cf=AVERAGE')]
    with pytest.raises(MonitoringError) as error: client.current(Target('node', 'other'))
    assert error.value.status_code == 403


def test_raw_transport_errors_are_not_exposed():
    class Client:
        def get_monitoring_data(self, **kwargs):
            raise ProxmoxMutationError('sensitive raw message', details={'token': 'sensitive'})
    with pytest.raises(MonitoringError) as error: MonitoringClient(Client()).current(Target('node', 'node1'))
    assert 'sensitive' not in str(error.value)
