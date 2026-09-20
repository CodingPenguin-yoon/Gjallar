from fastapi.testclient import TestClient

from app.auth.users import create_user
from app.main import app
from app.api.v1 import vm_migrate


def test_migrate_authorization_validation_and_result_contract(monkeypatch):
    monkeypatch.setenv("GJALLAR_PASSWORD_HASH_ITERATIONS", "1200")
    calls = []

    class Service:
        def review(self, **kwargs):
            calls.append(kwargs)
            return {"target": kwargs}

        def listing(self, **kwargs):
            calls.append(kwargs)
            return {"archives": [], "read_only": True}

        def execute(self, **kwargs):
            calls.append(kwargs)
            return {"operation_id": "migrate-test", "status": "needs_reconciliation"}

    monkeypatch.setattr(vm_migrate, "migrate_service", lambda: Service())
    for role in ("viewer", "operator"):
        create_user(username=role, password="synthetic-password", role=role)
    review = "/api/v1/nodes/node1/vms/40000/migrate?destination_node=node2"
    action = "/api/v1/nodes/node1/vms/40000/actions/migrate"
    payload = {"idempotency_key": "migrate-test", "destination_node": "node2",
               "expected_name": "test", "expected_review_digest": "sha256:" + "b" * 64,
               "confirmation": "40000/test/node1->node2", "migration_acknowledged": True}
    with TestClient(app) as client:
        assert client.get(review).status_code == 401
        client.post("/api/v1/auth/login", json={"username": "viewer", "password": "synthetic-password"})
        assert client.get(review).status_code == 403
        assert client.post(action, json=payload).status_code == 403
        assert not calls
        client.post("/api/v1/auth/login", json={"username": "operator", "password": "synthetic-password"})
        for patch in ({"migration_acknowledged": "yes"}, {"migration_acknowledged": 1}, {"expected_review_digest": "other"},
                      {"confirmation": ""}, {"destination_node": "../other"}, {"online": 1}, {"force": 1}, {"skiplock": 1}):
            assert client.post(action, json={**payload, **patch}).status_code == 422
        assert not calls
        assert client.get(review).status_code == 200
        result = client.post(action, json=payload)
        assert result.status_code == 200 and result.json()["data"]["status"] == "needs_reconciliation"
        assert calls[-1]["actor"]["role"] == "operator"
