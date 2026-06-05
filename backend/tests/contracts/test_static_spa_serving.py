"""Static React SPA serving contract for the single-image runtime."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


INDEX_HTML = """<!doctype html>
<html>
  <head><title>Gjallar SPA</title></head>
  <body><div id="root">Gjallar frontend shell</div></body>
</html>
"""


def _client() -> TestClient:
    from app.main import app

    return TestClient(app)


def _frontend_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "frontend-dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (dist / "robots.txt").write_text("User-agent: *\n", encoding="utf-8")
    (assets / "app.js").write_text("console.log('gjallar')\n", encoding="utf-8")
    return dist


def _assert_index(response) -> None:
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Gjallar frontend shell" in response.text


def test_backend_root_stays_json_when_no_frontend_dist(monkeypatch, tmp_path):
    monkeypatch.setenv("GJALLAR_FRONTEND_DIST", str(tmp_path / "missing-dist"))
    client = _client()

    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "Gjallar VM Operations API", "status": "running"}
    assert client.get("/instances").status_code == 404


def test_frontend_dist_serves_index_for_root_and_extensionless_routes(monkeypatch, tmp_path):
    monkeypatch.setenv("GJALLAR_FRONTEND_DIST", str(_frontend_dist(tmp_path)))
    client = _client()

    for path in ["/", "/instances", "/operations/jobs", "/settings/admin/users", "/instances/"]:
        _assert_index(client.get(path))


def test_frontend_dist_preserves_api_health_and_static_asset_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("GJALLAR_FRONTEND_DIST", str(_frontend_dist(tmp_path)))
    client = _client()

    assert client.get("/health").json() == {"status": "healthy", "service": "backend"}

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["data"] == {"authenticated": False, "user": None}

    protected = client.get("/api/v1/nodes")
    assert protected.status_code == 401
    assert protected.json()["detail"]["code"] == "AUTH_REQUIRED"

    admin = client.get("/api/v1/admin/users")
    assert admin.status_code == 401
    assert admin.json()["detail"]["code"] == "AUTH_REQUIRED"

    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert "console.log('gjallar')" in asset.text


def test_frontend_dist_does_not_fallback_for_reserved_or_missing_file_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("GJALLAR_FRONTEND_DIST", str(_frontend_dist(tmp_path)))
    client = _client()

    root_file = client.get("/robots.txt")
    assert root_file.status_code == 200
    assert root_file.text == "User-agent: *\n"

    for path in ["/missing.js", "/assets/missing.js", "/api/not-a-frontend-route", "/docs/missing"]:
        response = client.get(path)
        assert response.status_code == 404
        assert "Gjallar frontend shell" not in response.text
