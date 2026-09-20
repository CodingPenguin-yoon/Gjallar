from fastapi.testclient import TestClient
from app.api.v1 import maintenance
from app.auth.users import create_user
from app.main import app
from app.maintenance.application import MaintenanceError


def test_maintenance_is_operator_get_only_with_bounded_inputs(monkeypatch):
    monkeypatch.setenv('GJALLAR_PASSWORD_HASH_ITERATIONS','1200')
    calls = []
    class Service:
        def report(self, **kwargs):
            calls.append(kwargs)
            return {**kwargs, 'read_only': True, 'node_shutdown_safe': False}
    monkeypatch.setattr(maintenance, 'maintenance_service', lambda: Service())
    for role in ('viewer','operator'): create_user(username=role, password='synthetic-password', role=role)
    route = '/api/v1/maintenance/nodes/node1'
    with TestClient(app) as client:
        assert client.get(route).status_code == 401
        client.post('/api/v1/auth/login',json={'username':'viewer','password':'synthetic-password'})
        assert client.get(route).status_code == 403
        client.post('/api/v1/auth/login',json={'username':'operator','password':'synthetic-password'})
        for suffix in ('?check_limit=21','?check_limit=0','?backup_max_age_hours=0','?backup_max_age_hours=721'):
            assert client.get(route+suffix).status_code == 422
        assert not calls
        result = client.get(route+'?destination_node=node2&backup_storage=nfs&check_limit=2')
        assert result.status_code == 200 and result.json()['data']['read_only']
        assert calls == [{'node_id':'node1','destination_node':'node2','backup_storage':'nfs','check_limit':2,'backup_max_age_hours':24}]
        assert client.post(route,json={}).status_code == 405
        def unavailable(): raise MaintenanceError('TEST_UNAVAILABLE','관찰 불가')
        monkeypatch.setattr(maintenance,'maintenance_service',unavailable)
        assert client.get(route).json()['detail']['code'] == 'TEST_UNAVAILABLE'
