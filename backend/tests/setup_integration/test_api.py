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
