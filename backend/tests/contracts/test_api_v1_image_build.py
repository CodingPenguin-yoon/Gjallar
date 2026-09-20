from fastapi.testclient import TestClient
from app.api.v1 import vm_image_build
from app.auth.users import create_user
from app.cloud_images.catalog import ALMA_9
from app.main import app


def test_image_catalog_review_and_build_use_operator_and_strict_inputs(monkeypatch):
    monkeypatch.setenv('GJALLAR_PASSWORD_HASH_ITERATIONS', '1200')
    calls = []
    class Service:
        def review(self, **kwargs):
            calls.append(kwargs)
            return {'review_digest': 'sha256:' + 'a' * 64}
        def execute(self, **kwargs):
            calls.append(kwargs)
            return {'status': 'needs_reconciliation', 'operation_id': 'synthetic-image-operation'}
    monkeypatch.setattr(vm_image_build, 'image_build_service', lambda: Service())
    for role in ('viewer', 'operator'): create_user(username=role, password='synthetic-password', role=role)
    catalog = '/api/v1/templates/cloud-images'
    review = '/api/v1/nodes/node1/vms/40000/image-build'
    action = '/api/v1/nodes/node1/vms/40000/actions/image-build'
    query = dict(image_id=ALMA_9.image_id, name='alma-test', storage_id='target', staging_storage_id='stage', bridge_id='vmbr1')
    payload = {**query, 'idempotency_key': 'image-test', 'expected_review_digest': 'sha256:' + 'a' * 64,
               'confirmation': '40000/alma-test', 'image_build_acknowledged': True}
    with TestClient(app) as client:
        assert client.get(catalog).status_code == 401
        client.post('/api/v1/auth/login', json={'username': 'viewer', 'password': 'synthetic-password'})
        assert client.get(catalog).status_code == 403
        assert client.get(review, params=query).status_code == 403
        assert client.post(action, json=payload).status_code == 403
        assert not calls
        client.post('/api/v1/auth/login', json={'username': 'operator', 'password': 'synthetic-password'})
        images = client.get(catalog).json()['data']['images']
        assert len(images) == 1 and images[0]['sha256'] == ALMA_9.sha256
        for patch in ({'name': 'bad name'}, {'storage_id': '../store'}):
            assert client.get(review, params={**query, **patch}).status_code == 422
        for patch in ({'image_build_acknowledged': 1}, {'url': 'https://other'}, {'skiplock': 1}, {'force': 1}):
            assert client.post(action, json={**payload, **patch}).status_code == 422
        assert not calls
        assert client.get(review, params=query).status_code == 200
        assert client.post(action, json=payload).json()['data']['status'] == 'needs_reconciliation'
        assert calls[-1]['actor']['role'] == 'operator'
