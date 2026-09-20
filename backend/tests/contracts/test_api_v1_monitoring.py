from fastapi.testclient import TestClient
from app.api.v1 import monitoring
from app.auth.users import create_user
from app.main import app
from app.monitoring.domain import MonitoringError


def test_monitoring_routes_are_viewer_reads_with_bounded_targets(monkeypatch):
    monkeypatch.setenv('GJALLAR_PASSWORD_HASH_ITERATIONS', '1200')
    calls = []
    class Service:
        def query(self, target, timeframe):
            calls.append((target, timeframe))
            if target.node_id == 'unselected': raise MonitoringError('SETUP_TARGET_NOT_SELECTED', '범위 밖', 403)
            return {'target': target.to_dict(), 'timeframe': timeframe, 'read_only': True, 'partial': True,
                    'current': {'available': False}, 'history': {'available': True, 'points': []}}
    monkeypatch.setattr(monitoring, 'monitoring_service', lambda: Service())
    create_user(username='viewer', password='synthetic-password', role='viewer')
    with TestClient(app) as client:
        base = '/api/v1/monitoring/nodes/node1'
        assert client.get(base).status_code == 401 and not calls
        client.post('/api/v1/auth/login', json={'username': 'viewer', 'password': 'synthetic-password'})
        for suffix, kind in [('', 'node'), ('/vms/40000', 'vm'), ('/storage/store1', 'storage')]:
            result = client.get(base+suffix, params={'timeframe': 'week'})
            assert result.status_code == 200 and result.json()['data']['target']['kind'] == kind
            assert result.json()['data']['partial']
        assert len(calls) == 3
        assert client.get(base, params={'timeframe': 'decade'}).status_code == 422
        assert client.get(base+'/vms/1').status_code == 422
        assert client.get(base+'/storage/bad space').status_code == 422
        assert len(calls) == 3
        assert client.get('/api/v1/monitoring/nodes/unselected').status_code == 403
        assert client.post(base, json={}).status_code == 405


def test_operation_alerts_are_authenticated_bounded_read_only(monkeypatch):
    monkeypatch.setenv('GJALLAR_PASSWORD_HASH_ITERATIONS', '1200')
    calls = []
    def read(limit):
        calls.append(limit)
        if limit == 49:
            raise MonitoringError('MONITORING_OPERATIONS_UNAVAILABLE', '작업 이력을 조회하지 못했습니다.', 503)
        return {'alerts': [], 'unavailable_operations': [], 'read_only': True}
    monkeypatch.setattr(monitoring, 'operation_alerts', read)
    create_user(username='viewer', password='synthetic-password', role='viewer')
    with TestClient(app) as client:
        path = '/api/v1/monitoring/operation-alerts'
        assert client.get(path).status_code == 401 and not calls
        client.post('/api/v1/auth/login', json={'username': 'viewer', 'password': 'synthetic-password'})
        assert client.get(path).json()['data']['read_only']
        assert client.get(path, params={'limit': 50}).status_code == 200
        for limit in (0, 51, 'bad'):
            assert client.get(path, params={'limit': limit}).status_code == 422
        assert calls == [20, 50]
        assert client.get(path, params={'limit': 49}).status_code == 503
        assert client.post(path, json={}).status_code == 405
