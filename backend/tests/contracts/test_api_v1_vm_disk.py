from fastapi.testclient import TestClient

from app.api.v1 import vm_disk
from app.auth.users import create_user
from app.main import app


def test_disk_operator_and_strict_request_contract(monkeypatch):
    monkeypatch.setenv("GJALLAR_PASSWORD_HASH_ITERATIONS", "1200")
    calls = []

    class Service:
        def review(self, **kwargs):
            calls.append(kwargs)
            return {"target": kwargs}

        def execute(self, **kwargs):
            calls.append(kwargs)
            return {"operation_id": "disk-test", "status": "needs_reconciliation"}

    monkeypatch.setattr(vm_disk, "disk_service", lambda: Service())
    for role in ("viewer", "operator"):
        create_user(username=role, password="synthetic-password", role=role)
    review = "/api/v1/nodes/node1/vms/40000/disks/scsi0"
    action = "/api/v1/nodes/node1/vms/40000/actions/disk-resize"
    payload = {"idempotency_key": "disk-test", "expected_digest": "a" * 40, "expected_name": "test",
               "expected_volume": "store1:40000/vm-40000-disk-0.qcow2", "expected_size_bytes": 20 * 1024 ** 3, "size_gib": 24}
    with TestClient(app) as client:
        assert client.get(review).status_code == 401
        client.post("/api/v1/auth/login", json={"username": "viewer", "password": "synthetic-password"})
        assert client.get(review).status_code == client.post(action, json=payload).status_code == 403
        client.post("/api/v1/auth/login", json={"username": "operator", "password": "synthetic-password"})
        for patch in ({"size_gib": True}, {"size_gib": 0}, {"size_gib": "24"}, {"size_gib": 65537},
                      {"expected_size_bytes": -1}, {"disk": "scsi1"}, {"skiplock": 1}):
            assert client.post(action, json={**payload, **patch}).status_code == 422
        assert not calls
        assert client.get(review).status_code == 200
        result = client.post(action, json=payload)
        assert result.status_code == 200 and result.json()["data"]["status"] == "needs_reconciliation"
        assert calls[-1]["actor"]["role"] == "operator"
