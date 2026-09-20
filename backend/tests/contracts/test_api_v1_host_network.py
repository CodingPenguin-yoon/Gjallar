from fastapi.testclient import TestClient

from app.api.v1 import host_network
from app.auth.users import create_user
from app.main import app
from app.operations.host_network.domain import BridgeError


def test_only_admin_can_review_and_apply_bridge_with_explicit_node_reload_consent(monkeypatch):
    monkeypatch.setenv('GJALLAR_PASSWORD_HASH_ITERATIONS', '1200')
    calls = []
    class Service:
        def review(self, **kwargs):
            calls.append(kwargs)
            return {'target': {'node_id': kwargs['node_id'], 'bridge_id': kwargs['bridge_id']}}
        def execute(self, **kwargs):
            calls.append(kwargs)
            return {'operation_id': 'test-host-network', 'status': 'needs_reconciliation'}
    monkeypatch.setattr(host_network, 'bridge_service', lambda: Service())
    for role in ('viewer', 'operator', 'admin'):
        create_user(username=role, password='synthetic-password', role=role)
    root = '/api/v1/nodes/node1/host-network/vmbr40/'
    change = {'mode': 'create', 'autostart': True, 'vlan_aware': True, 'vlan_ids': '10 20-30'}
    payload = {**change, 'idempotency_key': 'test', 'expected_review_digest': 'sha256:' + 'a' * 64,
               'confirmation': 'node1/vmbr40/create', 'acknowledge_node_reload': True}
    with TestClient(app) as client:
        assert client.post(root + 'review', json=change).status_code == 401
        for role in ('viewer', 'operator'):
            client.post('/api/v1/auth/login', json={'username': role, 'password': 'synthetic-password'})
            assert client.post(root + 'review', json=change).status_code == 403
            assert client.post(root + 'actions/configure', json=payload).status_code == 403
        assert not calls
        client.post('/api/v1/auth/login', json={'username': 'admin', 'password': 'synthetic-password'})
        for patch in ({'bridge_ports': 'eno1'}, {'address': '192.0.2.3'}, {'autostart': 1}, {'vlan_ids': '4095'},
                      {'acknowledge_node_reload': False}, {'acknowledge_node_reload': 1}, {'delete': 'address'}):
            assert client.post(root + 'actions/configure', json={**payload, **patch}).status_code == 422
        assert not calls
        assert client.post(root + 'review', json=change).status_code == 200
        result = client.post(root + 'actions/configure', json=payload)
        assert result.status_code == 200 and result.json()['data']['status'] == 'needs_reconciliation'
        assert calls[-1]['actor']['role'] == 'admin'


def test_host_network_error_retains_operation_reference_for_reconciliation(monkeypatch):
    class Service:
        def execute(self, **kwargs):
            raise BridgeError('HOST_NETWORK_STATE_CHANGED', '다시 검토하세요.', details={'operation_id': 'host-network-test'})
    monkeypatch.setattr(host_network, 'bridge_service', lambda: Service())
    try:
        host_network._invoke('execute')
    except host_network.HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail['details']['operation_id'] == 'host-network-test'
    else:
        raise AssertionError('Expected explicit conflict response')
