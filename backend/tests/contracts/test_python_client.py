"""Use the independent client against the real FastAPI cookie contracts, no network."""
from pathlib import Path
import sys

import httpx
import pytest
from fastapi.testclient import TestClient


def test_client_real_cookie_contract_and_revoke(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "client" / "src"))
    from gjallar_client.api import Api
    from gjallar_client.application import Application
    from gjallar_client.connections import Connections
    from gjallar_client.sessions import MemoryStore
    from gjallar_client.errors import ClientError
    from app.auth.users import create_user, disable_user
    from app.main import app

    monkeypatch.setenv("GJALLAR_PASSWORD_HASH_ITERATIONS", "1200")
    create_user(username="reader", password="test-password", role="viewer")
    server = TestClient(app)
    def transport(request):
        server.cookies.clear()
        return server.request(request.method, request.url.path, headers=dict(request.headers), content=request.content)
    connections = Connections(tmp_path / "client-config")
    connections.add("local", "http://127.0.0.1:8000")
    client = Application(connections, MemoryStore(), lambda p: Api(p, httpx.MockTransport(transport)))
    assert client.login("reader", "test-password", "local")["user"]["role"] == "viewer"
    assert client.status()["user"]["username"] == "reader"
    for resource in ("nodes", "vms", "templates", "connection"):
        assert client.read(resource)["ok"]
    disable_user(username="reader")
    with pytest.raises(ClientError) as error:
        client.status()
    assert error.value.code == "SESSION_EXPIRED"
    server.close()
