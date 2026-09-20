from fastapi.testclient import TestClient
from app.auth.users import create_user
from app.main import app
from app.api.v1 import vm_restore


def test_restore_requires_operator_and_exact_request_but_report_allows_viewer(monkeypatch):
    monkeypatch.setenv('GJALLAR_PASSWORD_HASH_ITERATIONS','1200')
    calls=[]
    class Service:
        def review(self,**kwargs):calls.append(kwargs);return {'target':kwargs}
        def execute(self,**kwargs):calls.append(kwargs);return {'operation_id':'restore-test','status':'needs_reconciliation'}
    monkeypatch.setattr(vm_restore,'restore_service',lambda:Service())
    monkeypatch.setattr(vm_restore,'restore_report',lambda **kwargs:{'read_only':True,**kwargs})
    for role in ('viewer','operator'):create_user(username=role,password='synthetic-password',role=role)
    archive='nfs:backup/vzdump-qemu-40000-2026_09_19-05_00_00.vma.zst'
    review='/api/v1/nodes/node1/vms/40000/restore-review'
    query={'archive':archive,'new_vmid':40001,'storage_id':'target','bridge_id':'vmbr1'}
    action='/api/v1/nodes/node1/vms/40000/actions/restore'
    payload={**query,'name':'restored','idempotency_key':'test','expected_name':'source','expected_review_digest':'sha256:'+'a'*64,
        'confirmation':'40000/40001/restored','isolation_acknowledged':True}
    with TestClient(app) as client:
        assert client.get(review,params=query).status_code==401
        client.post('/api/v1/auth/login',json={'username':'viewer','password':'synthetic-password'})
        assert client.get(review,params=query).status_code==403
        assert client.post(action,json=payload).status_code==403
        assert client.get('/api/v1/operations/restore-test/restore-report').json()['data']['read_only']
        assert not calls
        client.post('/api/v1/auth/login',json={'username':'operator','password':'synthetic-password'})
        for patch in ({'new_vmid':True},{'isolation_acknowledged':'yes'},{'force':1},{'start':1},{'archive':'/tmp/backup'},{'new_vmid':99}):
            assert client.post(action,json={**payload,**patch}).status_code==422
        assert not calls
        assert client.get(review,params=query).status_code==200
        assert client.post(action,json=payload).json()['data']['status']=='needs_reconciliation'
        assert calls[-1]['actor']['role']=='operator'
