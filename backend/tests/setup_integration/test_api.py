import json
import uuid

from fastapi.testclient import TestClient

from app.auth.users import create_user
from app.main import app


BASE = "/api/v1/setup/proxmox/registrations"


def test_setup_api_admin_boundary_and_validation_never_echoes_secrets(monkeypatch):
    monkeypatch.setenv("GJALLAR_PASSWORD_HASH_ITERATIONS", "1200")
    monkeypatch.setenv("GJALLAR_INSTALLATION_ID", str(uuid.uuid4()))
    for role in ("viewer", "operator", "admin"):
        create_user(username=role, password="synthetic-login", role=role)
    with TestClient(app) as client:
        assert client.get(BASE).status_code == 401
        for role in ("viewer", "operator"):
            assert client.post("/api/v1/auth/login", json={"username": role, "password": "synthetic-login"}).status_code == 200
            assert client.get(BASE).status_code == 403
            assert client.post(BASE, json={"password": "synthetic-sensitive"}).status_code == 403
        client.post("/api/v1/auth/login", json={"username": "admin", "password": "synthetic-login"})
        for payload in ({"password": "synthetic-sensitive"}, {"intent": {"password": "synthetic-sensitive"}, "idempotency_key": "test-request"}):
            response = client.post(BASE, json=payload)
            assert response.status_code == 422
            assert "synthetic-sensitive" not in response.text
        response = client.post(BASE, content='{"password":"synthetic-sensitive", broken')
        assert response.status_code == 422 and "synthetic-sensitive" not in response.text
        response = client.post(BASE + "/" + str(uuid.uuid4()) + "/login", json={"expected_version": 1, "password": "synthetic-sensitive"})
        assert response.status_code == 404 and "synthetic-sensitive" not in response.text
        assert client.get(BASE).json()["data"] == []


def test_trust_probe_is_admin_only_validated_and_secret_free(monkeypatch):
    from app.setup_integration.transport import ProxmoxSetupTransport
    probes = []
    monkeypatch.setattr(ProxmoxSetupTransport, 'probe_certificate',
        lambda *, endpoint: probes.append(endpoint) or {'endpoint': endpoint, 'certificate_sha256': 'a'*64})
    monkeypatch.setenv('GJALLAR_PASSWORD_HASH_ITERATIONS', '1200')
    create_user(username='admin', password='synthetic-login', role='admin')
    create_user(username='viewer', password='synthetic-login', role='viewer')
    with TestClient(app) as client:
        assert client.post(BASE + '/trust', json={'endpoint': 'https://pve.example.test'}).status_code == 401
        client.post('/api/v1/auth/login', json={'username': 'viewer', 'password': 'synthetic-login'})
        assert client.post(BASE + '/trust', json={'endpoint': 'https://pve.example.test'}).status_code == 403
        client.post('/api/v1/auth/login', json={'username': 'admin', 'password': 'synthetic-login'})
        for body in ({'endpoint': 'https://127.0.0.1'}, {'endpoint': 'http://pve.example.test'},
                     {'endpoint': 'https://pve.example.test', 'password': 'synthetic-secret'}):
            result = client.post(BASE + '/trust', json=body)
            assert result.status_code == 422 and 'synthetic-secret' not in result.text
        assert not probes
        result = client.post(BASE + '/trust', json={'endpoint': 'https://pve.example.test'})
        assert result.status_code == 200 and result.json()['data']['certificate_sha256'] == 'a'*64
        assert probes == ['https://pve.example.test:8006/api2/json']
