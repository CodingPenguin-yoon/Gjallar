from fastapi.testclient import TestClient
from app.api.v1 import template_test
from app.auth.users import create_user
from app.main import app
from app.vm_actions.post_create_readiness import PostCreateReadinessError


def test_template_report_is_authenticated_read_only(monkeypatch):
    monkeypatch.setenv('GJALLAR_PASSWORD_HASH_ITERATIONS', '1200')
    calls = []
    def report(operation_id):
        calls.append(operation_id)
        if operation_id == 'wrong': raise PostCreateReadinessError('TEMPLATE_TEST_TARGET_INVALID', '잘못된 생성 작업')
        return {'operation_id': operation_id, 'historical': True, 'live_checks_performed': False}
    monkeypatch.setattr(template_test, 'template_test_report', report)
    create_user(username='viewer', password='synthetic-password', role='viewer')
    with TestClient(app) as client:
        assert client.get('/api/v1/operations/create-test/template-test').status_code == 401
        assert not calls
        client.post('/api/v1/auth/login', json={'username': 'viewer', 'password': 'synthetic-password'})
        response = client.get('/api/v1/operations/create-test/template-test')
        assert response.json()['data']['historical']
        assert client.get('/api/v1/operations/wrong/template-test').status_code == 409
        assert client.post('/api/v1/nodes/node1/vms/40001/post-create-readiness-evidence', json={}).status_code == 403
