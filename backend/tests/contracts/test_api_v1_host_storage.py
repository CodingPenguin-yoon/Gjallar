from fastapi.testclient import TestClient
from app.auth.users import create_user
from app.main import app
from app.api.v1 import host_storage


def test_host_storage_requires_admin_for_review_and_execution(monkeypatch):
    monkeypatch.setenv('GJALLAR_PASSWORD_HASH_ITERATIONS','1200')
    calls = []
    class Service:
        def review(self,**kwargs): calls.append(kwargs); return {'target':{'node_id':kwargs['node_id'],'storage_id':kwargs['storage_id']}}
        def execute(self,**kwargs): calls.append(kwargs); return {'operation_id':'test-host-storage','status':'needs_reconciliation'}
    monkeypatch.setattr(host_storage,'storage_service',lambda:Service())
    for role in ('viewer','operator','admin'): create_user(username=role,password='synthetic-password',role=role)
    root = '/api/v1/nodes/node1/host-storage/test-dir/'
    change = {'mode':'update','content':['iso'],'enabled':False}
    payload = {**change,'idempotency_key':'test','expected_review_digest':'sha256:'+'a'*64,
               'confirmation':'node1/test-dir/update','acknowledge_cluster_impact':True}
    with TestClient(app) as client:
        assert client.post(root+'review',json=change).status_code == 401
        for role in ('viewer','operator'):
            client.post('/api/v1/auth/login',json={'username':role,'password':'synthetic-password'})
            assert client.post(root+'review',json=change).status_code == 403
            assert client.post(root+'actions/configure',json=payload).status_code == 403
        assert not calls
        client.post('/api/v1/auth/login',json={'username':'admin','password':'synthetic-password'})
        for patch in ({'path':'/other'},{'enabled':1},{'delete':'path'},{'content':['exec']},{'acknowledge_cluster_impact':False},{'acknowledge_cluster_impact':1}):
            assert client.post(root+'actions/configure',json={**payload,**patch}).status_code == 422
        assert not calls
        assert client.post(root+'review',json=change).status_code == 200
        assert client.post(root+'actions/configure',json=payload).json()['data']['status'] == 'needs_reconciliation'
        assert calls[-1]['actor']['role'] == 'admin'
