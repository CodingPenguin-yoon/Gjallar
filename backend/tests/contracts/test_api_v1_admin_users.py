"""Admin local-user management API contract tests."""

from __future__ import annotations

import concurrent.futures
import threading
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select


def _client() -> TestClient:
    from app.main import app

    return TestClient(app)


def _create_user(monkeypatch, *, username: str, password: str = "correct horse battery staple", role: str = "viewer", enabled: bool = True):
    monkeypatch.setenv("GJALLAR_PASSWORD_HASH_ITERATIONS", "1200")
    from app.auth.users import create_user

    return create_user(username=username, password=password, role=role, enabled=enabled)


def _login(client: TestClient, *, username: str, password: str = "correct horse battery staple"):
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response


def _assert_no_secret_material(payload: Any, forbidden_values: set[str] | None = None) -> None:
    forbidden_values = forbidden_values or set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).lower()
            assert "password_hash" not in lowered
            assert "session_token_hash" not in lowered
            assert "token_hash" not in lowered
            assert "secret" not in lowered
            _assert_no_secret_material(value, forbidden_values)
        return
    if isinstance(payload, list):
        for item in payload:
            _assert_no_secret_material(item, forbidden_values)
        return
    if isinstance(payload, str):
        assert payload not in forbidden_values


def test_admin_user_api_admin_can_list_create_change_role_disable_and_reset_password(monkeypatch):
    _create_user(monkeypatch, username="root-admin", role="admin")
    client = _client()
    _login(client, username="root-admin")

    create = client.post(
        "/api/v1/admin/users",
        json={"username": "api-target", "password": "api-target-password", "role": "viewer"},
    )
    assert create.status_code == 201, create.text
    created_user = create.json()["data"]["user"]
    assert created_user["username"] == "api-target"
    assert created_user["role"] == "viewer"
    assert created_user["enabled"] is True
    _assert_no_secret_material(create.json(), {"api-target-password"})

    listed = client.get("/api/v1/admin/users")
    assert listed.status_code == 200, listed.text
    assert {user["username"] for user in listed.json()["data"]} == {"api-target", "root-admin"}
    _assert_no_secret_material(listed.json())

    changed = client.patch("/api/v1/admin/users/api-target/role", json={"role": "operator"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["data"]["user"]["role"] == "operator"

    disabled = client.post("/api/v1/admin/users/api-target/disable")
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["data"]["user"]["enabled"] is False
    assert disabled.json()["data"]["revoked_sessions"] == 0

    reset = client.post("/api/v1/admin/users/api-target/reset-password", json={"password": "new-api-target-password"})
    assert reset.status_code == 200, reset.text
    assert reset.json()["data"]["user"]["username"] == "api-target"
    assert reset.json()["data"]["revoked_sessions"] == 0
    _assert_no_secret_material(reset.json(), {"new-api-target-password"})


def test_admin_user_api_rejects_viewer_operator_and_unauthenticated_clients(monkeypatch):
    _create_user(monkeypatch, username="admin", role="admin")
    _create_user(monkeypatch, username="viewer", role="viewer")
    _create_user(monkeypatch, username="operator", role="operator")

    unauthenticated = _client()
    assert unauthenticated.get("/api/v1/admin/users").status_code == 401
    assert unauthenticated.post("/api/v1/admin/users", json={"username": "x", "password": "p", "role": "viewer"}).status_code == 401
    assert unauthenticated.patch("/api/v1/admin/users/admin/role", json={"role": "viewer"}).status_code == 401
    assert unauthenticated.post("/api/v1/admin/users/admin/disable").status_code == 401
    assert unauthenticated.post("/api/v1/admin/users/admin/reset-password", json={"password": "p"}).status_code == 401

    for username in ("viewer", "operator"):
        client = _client()
        _login(client, username=username)
        assert client.get("/api/v1/admin/users").status_code == 403
        assert client.post("/api/v1/admin/users", json={"username": f"{username}-x", "password": "p", "role": "viewer"}).status_code == 403
        assert client.patch("/api/v1/admin/users/admin/role", json={"role": "viewer"}).status_code == 403
        assert client.post("/api/v1/admin/users/admin/disable").status_code == 403
        assert client.post("/api/v1/admin/users/admin/reset-password", json={"password": "p"}).status_code == 403


def test_admin_user_api_maps_operator_errors_to_structured_details(monkeypatch):
    _create_user(monkeypatch, username="admin", role="admin")
    client = _client()
    _login(client, username="admin")

    duplicate = client.post(
        "/api/v1/admin/users",
        json={"username": "admin", "password": "password", "role": "viewer"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "USER_ALREADY_EXISTS"

    missing = client.patch("/api/v1/admin/users/missing/role", json={"role": "operator"})
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "USER_NOT_FOUND"

    invalid_role = client.post(
        "/api/v1/admin/users",
        json={"username": "bad-role", "password": "password", "role": "owner"},
    )
    assert invalid_role.status_code == 400
    assert invalid_role.json()["detail"]["code"] == "INVALID_ADMIN_USER_REQUEST"

    missing_password = client.post("/api/v1/admin/users", json={"username": "no-password", "role": "viewer"})
    assert missing_password.status_code == 400
    assert missing_password.json()["detail"]["code"] == "INVALID_ADMIN_USER_REQUEST"


def test_last_enabled_admin_cannot_be_disabled_or_demoted_through_cli_and_api(monkeypatch, capsys):
    _create_user(monkeypatch, username="only-admin", role="admin")
    _create_user(monkeypatch, username="disabled-admin", role="admin", enabled=False)

    from app.auth.users import main
    from app.db.models import UserRecord
    from app.db.session import session_scope

    assert main(["disable-user", "--username", "only-admin"]) == 1
    captured = capsys.readouterr()
    assert "Cannot disable the last enabled admin user: only-admin" in captured.err
    assert "Traceback" not in captured.err

    assert main(["set-role", "--username", "only-admin", "--role", "operator"]) == 1
    captured = capsys.readouterr()
    assert "Cannot demote the last enabled admin user: only-admin" in captured.err
    assert "Traceback" not in captured.err

    client = _client()
    _login(client, username="only-admin")

    disabled = client.post("/api/v1/admin/users/only-admin/disable")
    assert disabled.status_code == 409
    assert disabled.json()["detail"]["code"] == "LAST_ENABLED_ADMIN"

    demoted = client.patch("/api/v1/admin/users/only-admin/role", json={"role": "operator"})
    assert demoted.status_code == 409
    assert demoted.json()["detail"]["code"] == "LAST_ENABLED_ADMIN"

    with session_scope() as session:
        row = session.scalar(select(UserRecord).where(UserRecord.username == "only-admin"))
        assert row.enabled is True
        assert row.role == "admin"


def test_last_admin_protection_counts_only_enabled_admins_and_allows_safe_changes(monkeypatch, capsys):
    _create_user(monkeypatch, username="admin-a", role="admin")
    _create_user(monkeypatch, username="admin-b", role="admin")
    _create_user(monkeypatch, username="admin-disabled", role="admin", enabled=False)

    from app.auth.users import main
    from app.db.models import UserRecord
    from app.db.session import session_scope

    assert main(["set-role", "--username", "admin-disabled", "--role", "operator"]) == 0
    assert main(["disable-user", "--username", "admin-b"]) == 0
    assert "disabled user admin-b" in capsys.readouterr().out

    with session_scope() as session:
        admin_a = session.scalar(select(UserRecord).where(UserRecord.username == "admin-a"))
        admin_b = session.scalar(select(UserRecord).where(UserRecord.username == "admin-b"))
        disabled = session.scalar(select(UserRecord).where(UserRecord.username == "admin-disabled"))
        assert admin_a.enabled is True
        assert admin_a.role == "admin"
        assert admin_b.enabled is False
        assert disabled.enabled is False
        assert disabled.role == "operator"


def test_concurrent_last_admin_mutations_cannot_remove_all_enabled_admins(monkeypatch):
    _create_user(monkeypatch, username="admin-a", role="admin")
    _create_user(monkeypatch, username="admin-b", role="admin")

    from app.auth import users as user_service
    from app.db.models import UserRecord
    from app.db.session import session_scope

    original_enabled_admin_count = user_service._enabled_admin_count
    count_barrier = threading.Barrier(2)
    start_barrier = threading.Barrier(3)

    def synchronized_enabled_admin_count(session) -> int:
        count = original_enabled_admin_count(session)
        if count > 1:
            try:
                count_barrier.wait(timeout=1)
            except threading.BrokenBarrierError:
                pass
        return count

    def run_mutation(operation):
        start_barrier.wait(timeout=5)
        try:
            operation()
        except user_service.LastEnabledAdminError:
            return "last_admin"
        return "ok"

    monkeypatch.setattr(user_service, "_enabled_admin_count", synchronized_enabled_admin_count)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(run_mutation, lambda: user_service.disable_user(username="admin-a")),
            executor.submit(run_mutation, lambda: user_service.set_user_role(username="admin-b", role="viewer")),
        ]
        start_barrier.wait(timeout=5)
        outcomes = [future.result(timeout=10) for future in futures]

    assert outcomes.count("ok") == 1
    assert outcomes.count("last_admin") == 1
    with session_scope() as session:
        enabled_admins = session.scalar(
            select(func.count())
            .select_from(UserRecord)
            .where(UserRecord.role == "admin")
            .where(UserRecord.enabled.is_(True))
        )
        assert enabled_admins == 1


def test_admin_disable_and_reset_password_revoke_target_sessions(monkeypatch):
    _create_user(monkeypatch, username="admin", role="admin")
    _create_user(monkeypatch, username="disable-target", role="viewer")
    _create_user(monkeypatch, username="reset-target", password="old-password", role="viewer")

    admin_client = _client()
    _login(admin_client, username="admin")

    disable_client = _client()
    _login(disable_client, username="disable-target")
    disabled = admin_client.post("/api/v1/admin/users/disable-target/disable")
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["data"]["revoked_sessions"] == 1
    assert disable_client.get("/api/v1/auth/me").json()["data"]["authenticated"] is False

    reset_client = _client()
    _login(reset_client, username="reset-target", password="old-password")
    reset = admin_client.post("/api/v1/admin/users/reset-target/reset-password", json={"password": "new-password"})
    assert reset.status_code == 200, reset.text
    assert reset.json()["data"]["revoked_sessions"] == 1
    assert reset_client.get("/api/v1/auth/me").json()["data"]["authenticated"] is False
    assert _client().post("/api/v1/auth/login", json={"username": "reset-target", "password": "old-password"}).status_code == 401
    assert _client().post("/api/v1/auth/login", json={"username": "reset-target", "password": "new-password"}).status_code == 200


def test_admin_set_role_does_not_revoke_existing_session(monkeypatch):
    _create_user(monkeypatch, username="admin", role="admin")
    _create_user(monkeypatch, username="role-target", role="viewer")
    admin_client = _client()
    target_client = _client()
    _login(admin_client, username="admin")
    _login(target_client, username="role-target")

    response = admin_client.patch("/api/v1/admin/users/role-target/role", json={"role": "operator"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["user"]["role"] == "operator"

    me = target_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["data"]["authenticated"] is True
    assert me.json()["data"]["user"]["role"] == "operator"

    from app.db.models import SessionRecord
    from app.db.session import session_scope

    with session_scope() as session:
        rows = session.scalars(select(SessionRecord)).all()
        assert rows
        assert all(row.revoked_at is None for row in rows)


def test_reset_password_for_last_enabled_admin_is_not_blocked_but_revokes_session(monkeypatch):
    _create_user(monkeypatch, username="only-admin", password="old-admin-password", role="admin")
    client = _client()
    _login(client, username="only-admin", password="old-admin-password")

    response = client.post("/api/v1/admin/users/only-admin/reset-password", json={"password": "new-admin-password"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["revoked_sessions"] == 1
    _assert_no_secret_material(response.json(), {"new-admin-password"})

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["data"]["authenticated"] is False

    assert _client().post(
        "/api/v1/auth/login",
        json={"username": "only-admin", "password": "new-admin-password"},
    ).status_code == 200
