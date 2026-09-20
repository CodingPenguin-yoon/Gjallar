from fastapi.testclient import TestClient

from app.auth.users import create_user
from app.main import app
from app.api.v1 import vm_template


def test_template_authorization_validation_and_result_contract(monkeypatch):
    monkeypatch.setenv("GJALLAR_PASSWORD_HASH_ITERATIONS", "1200")
    calls = []

    class Service:
        def review(self, **kwargs):
            calls.append(kwargs)
            return {"target": kwargs}

        def execute(self, **kwargs):
            calls.append(kwargs)
            return {"operation_id": "template-test", "status": "needs_reconciliation"}

    monkeypatch.setattr(vm_template, "template_service", lambda: Service())
    for role in ("viewer", "operator"):
        create_user(username=role, password="synthetic-password", role=role)
    review = "/api/v1/nodes/node1/vms/40000/template-conversion"
    action = "/api/v1/nodes/node1/vms/40000/actions/template"
    payload = {"idempotency_key": "template-test", "expected_digest": "a" * 40,
               "expected_name": "test", "expected_resources_digest": "sha256:" + "b" * 64,
               "confirmation": "40000/test", "guest_prepared": True, "conversion_acknowledged": True}
    with TestClient(app) as client:
        assert client.get(review).status_code == 401
        client.post("/api/v1/auth/login", json={"username": "viewer", "password": "synthetic-password"})
        assert client.get(review).status_code == 403
        assert client.post(action, json=payload).status_code == 403
        assert not calls
        client.post("/api/v1/auth/login", json={"username": "operator", "password": "synthetic-password"})
        for patch in ({"conversion_acknowledged": "yes"}, {"conversion_acknowledged": 1}, {"expected_resources_digest": "other"},
                      {"confirmation": ""}, {"template": "net0"}, {"skiplock": 1}):
            assert client.post(action, json={**payload, **patch}).status_code == 422
        assert not calls
        assert client.get(review).status_code == 200
        result = client.post(action, json=payload)
        assert result.status_code == 200 and result.json()["data"]["status"] == "needs_reconciliation"
        assert calls[-1]["actor"]["role"] == "operator"
