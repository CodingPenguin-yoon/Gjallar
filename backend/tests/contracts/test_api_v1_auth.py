"""Auth and authorization contract tests for /api/v1."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import select


def _client():
    from app.main import app

    return TestClient(app)


def _create_user(monkeypatch, *, username: str, password: str = "correct horse battery staple", role: str = "viewer", enabled: bool = True):
    monkeypatch.setenv("GJALLAR_PASSWORD_HASH_ITERATIONS", "1200")
    from app.auth.users import create_user

    return create_user(username=username, password=password, role=role, enabled=enabled)


def _login(client, *, username: str, password: str = "correct horse battery staple"):
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
            assert "user_agent" not in lowered
            assert lowered not in {"ip", "ip_hash", "remote_ip", "client_ip"}
            _assert_no_secret_material(value, forbidden_values)
        return
    if isinstance(payload, list):
        for item in payload:
            _assert_no_secret_material(item, forbidden_values)
        return
    if isinstance(payload, str):
        assert payload not in forbidden_values


def test_user_cli_can_create_non_admin_user(monkeypatch, capsys):
    monkeypatch.setenv("GJALLAR_PASSWORD_HASH_ITERATIONS", "1200")
    from app.auth.users import main
    from app.db.models import UserRecord
    from app.db.session import session_scope

    assert main(["create-user", "--username", "kim", "--role", "operator", "--password", "operator-password"]) == 0
    output = capsys.readouterr().out
    assert "created operator user kim" in output

    with session_scope() as session:
        row = session.scalar(select(UserRecord).where(UserRecord.username == "kim"))
        assert row is not None
        assert row.role == "operator"
        assert row.enabled is True
        assert row.password_hash != "operator-password"


def test_user_cli_lists_users_without_secrets(monkeypatch, capsys):
    _create_user(monkeypatch, username="alice", password="alice-secret", role="viewer")
    _create_user(monkeypatch, username="zoe", password="zoe-secret", role="operator")
    from app.auth.users import main
    from app.db.models import UserRecord
    from app.db.session import session_scope

    with session_scope() as session:
        hashes = [
            row.password_hash
            for row in session.scalars(select(UserRecord).order_by(UserRecord.username)).all()
        ]

    assert main(["list-users"]) == 0
    output = capsys.readouterr().out

    assert "username\trole\tenabled" in output
    assert "alice\tviewer\ttrue" in output
    assert "zoe\toperator\ttrue" in output
    assert "alice-secret" not in output
    assert "zoe-secret" not in output
    assert "password" not in output.lower()
    assert "hash" not in output.lower()
    for password_hash in hashes:
        assert password_hash not in output


def test_user_cli_set_role_affects_existing_session_without_revocation(monkeypatch, capsys):
    _create_user(monkeypatch, username="role-target", role="viewer")
    client = _client()
    _login(client, username="role-target")
    from app.auth.users import main
    from app.db.models import SessionRecord
    from app.db.session import session_scope

    before = client.get("/api/v1/auth/me")
    assert before.status_code == 200
    assert before.json()["data"]["user"]["role"] == "viewer"

    assert main(["set-role", "--username", "role-target", "--role", "operator"]) == 0
    output = capsys.readouterr().out
    assert "updated user role-target role to operator" in output

    after = client.get("/api/v1/auth/me")
    assert after.status_code == 200
    assert after.json()["data"]["authenticated"] is True
    assert after.json()["data"]["user"]["role"] == "operator"

    with session_scope() as session:
        row = session.scalar(select(SessionRecord))
        assert row.revoked_at is None


def test_user_cli_disable_user_blocks_login_and_revokes_existing_session(monkeypatch, capsys):
    _create_user(monkeypatch, username="disable-target", role="viewer")
    client = _client()
    _login(client, username="disable-target")
    from app.auth.users import main
    from app.db.models import SessionRecord, UserRecord
    from app.db.session import session_scope

    assert main(["disable-user", "--username", "disable-target"]) == 0
    output = capsys.readouterr().out
    assert "disabled user disable-target; revoked 1 session(s)" in output

    with session_scope() as session:
        user = session.scalar(select(UserRecord).where(UserRecord.username == "disable-target"))
        session_row = session.scalar(select(SessionRecord).where(SessionRecord.user_id == user.user_id))
        assert user.enabled is False
        assert session_row.revoked_at is not None

    login = client.post(
        "/api/v1/auth/login",
        json={"username": "disable-target", "password": "correct horse battery staple"},
    )
    assert login.status_code == 401
    assert login.json()["detail"]["code"] == "LOGIN_FAILED"

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["data"]["authenticated"] is False

    protected = client.get("/api/v1/nodes")
    assert protected.status_code == 401
    assert protected.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_user_cli_reset_password_changes_login_and_revokes_existing_session(monkeypatch, capsys):
    _create_user(monkeypatch, username="reset-target", password="old-password", role="viewer")
    client = _client()
    _login(client, username="reset-target", password="old-password")
    from app.auth.users import main
    from app.db.models import SessionRecord, UserRecord
    from app.db.session import session_scope

    assert main(["reset-password", "--username", "reset-target", "--password", "new-password"]) == 0
    output = capsys.readouterr().out
    assert "reset password for user reset-target; revoked 1 session(s)" in output
    assert "new-password" not in output

    with session_scope() as session:
        user = session.scalar(select(UserRecord).where(UserRecord.username == "reset-target"))
        session_row = session.scalar(select(SessionRecord).where(SessionRecord.user_id == user.user_id))
        assert user.enabled is True
        assert user.password_hash not in {"old-password", "new-password"}
        assert session_row.revoked_at is not None

    old_login = _client().post(
        "/api/v1/auth/login",
        json={"username": "reset-target", "password": "old-password"},
    )
    assert old_login.status_code == 401
    assert old_login.json()["detail"]["code"] == "LOGIN_FAILED"

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["data"]["authenticated"] is False

    new_login = _client().post(
        "/api/v1/auth/login",
        json={"username": "reset-target", "password": "new-password"},
    )
    assert new_login.status_code == 200, new_login.text
    assert new_login.json()["data"]["user"]["username"] == "reset-target"


def test_user_cli_unknown_user_fails_without_traceback(monkeypatch, capsys):
    monkeypatch.setenv("GJALLAR_PASSWORD_HASH_ITERATIONS", "1200")
    from app.auth.users import main

    commands = [
        ["set-role", "--username", "missing", "--role", "operator"],
        ["disable-user", "--username", "missing"],
        ["reset-password", "--username", "missing", "--password", "new-password"],
    ]

    for command in commands:
        assert main(command) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Unknown user: missing" in captured.err
        assert "Traceback" not in captured.err


def test_user_cli_missing_database_url_fails_without_traceback(monkeypatch, capsys):
    from app.auth.users import main
    from app.db.session import reset_session_cache

    monkeypatch.delenv("GJALLAR_DATABASE_URL", raising=False)
    reset_session_cache()

    assert main(["list-users"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error: GJALLAR_DATABASE_URL is required" in captured.err
    assert "Traceback" not in captured.err


def test_login_me_logout_session_cookie_flow(monkeypatch):
    _create_user(monkeypatch, username="viewer")
    client = _client()

    anonymous = client.get("/api/v1/auth/me")
    assert anonymous.status_code == 200
    assert anonymous.json()["data"] == {"authenticated": False, "user": None}

    login = _login(client, username="viewer")
    assert login.json()["data"]["user"]["role"] == "viewer"
    set_cookie = login.headers.get("set-cookie", "")
    assert "gjallar_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "samesite=lax" in set_cookie.lower()
    assert "Max-Age=" in set_cookie

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["data"]["authenticated"] is True
    assert me.json()["data"]["user"]["username"] == "viewer"

    logout = client.post("/api/v1/auth/logout")
    assert logout.status_code == 200
    assert logout.json()["data"]["authenticated"] is False
    assert "Max-Age=0" in logout.headers.get("set-cookie", "")

    after = client.get("/api/v1/auth/me")
    assert after.status_code == 200
    assert after.json()["data"]["authenticated"] is False


def test_login_rejects_bad_password_and_disabled_user(monkeypatch):
    _create_user(monkeypatch, username="enabled")
    _create_user(monkeypatch, username="disabled", enabled=False)
    client = _client()

    bad_password = client.post("/api/v1/auth/login", json={"username": "enabled", "password": "wrong"})
    assert bad_password.status_code == 401
    assert bad_password.json()["detail"]["code"] == "LOGIN_FAILED"

    disabled = client.post("/api/v1/auth/login", json={"username": "disabled", "password": "correct horse battery staple"})
    assert disabled.status_code == 401
    assert disabled.json()["detail"]["code"] == "LOGIN_FAILED"


def test_change_password_requires_current_password_and_preserves_current_session(monkeypatch):
    _create_user(monkeypatch, username="self-change", password="old-password", role="operator")
    client = _client()
    other_client = _client()
    _login(client, username="self-change", password="old-password")
    _login(other_client, username="self-change", password="old-password")

    missing_auth = _client().post(
        "/api/v1/auth/change-password",
        json={"current_password": "old-password", "new_password": "new-password"},
    )
    assert missing_auth.status_code == 401
    assert missing_auth.json()["detail"]["code"] == "AUTH_REQUIRED"

    rejected = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "wrong-password", "new_password": "new-password"},
    )
    assert rejected.status_code == 403
    assert rejected.json()["detail"]["code"] == "CURRENT_PASSWORD_INVALID"
    assert "wrong-password" not in rejected.text

    changed = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "old-password", "new_password": "new-password"},
    )
    assert changed.status_code == 200, changed.text
    data = changed.json()["data"]
    assert data["authenticated"] is True
    assert data["user"]["username"] == "self-change"
    assert data["revoked_sessions"] == 1
    assert data["current_session_preserved"] is True
    assert data["audit_event_id"].startswith("acctevt-")
    assert data["audit_event"]["operation"] == "auth.change_password"
    assert data["audit_event"]["actor"]["username"] == "self-change"
    assert data["audit_event"]["target"]["username"] == "self-change"
    assert data["audit_event"]["details"] == {
        "revoked_sessions": 1,
        "current_session_preserved": True,
    }
    _assert_no_secret_material(changed.json(), {"old-password", "new-password", "wrong-password"})

    assert client.get("/api/v1/auth/me").json()["data"]["authenticated"] is True
    assert other_client.get("/api/v1/auth/me").json()["data"]["authenticated"] is False
    assert _client().post(
        "/api/v1/auth/login",
        json={"username": "self-change", "password": "old-password"},
    ).status_code == 401

    from app.db.models import AccountAuditEventRecord, SessionRecord
    from app.db.session import session_scope

    with session_scope() as session:
        event = session.get(AccountAuditEventRecord, data["audit_event_id"])
        assert event is not None
        assert event.actor_username == "self-change"
        assert event.target_username == "self-change"
        assert event.details == {"revoked_sessions": 1, "current_session_preserved": True}
        rows = session.scalars(select(SessionRecord)).all()
        assert len(rows) == 2
        assert sum(row.revoked_at is None for row in rows) == 1

    assert _client().post(
        "/api/v1/auth/login",
        json={"username": "self-change", "password": "new-password"},
    ).status_code == 200


def test_session_expiry_returns_anonymous_me_and_401_for_protected_routes(monkeypatch):
    _create_user(monkeypatch, username="expiring")
    client = _client()
    _login(client, username="expiring")

    from app.db.models import SessionRecord
    from app.db.session import session_scope

    with session_scope() as session:
        row = session.scalar(select(SessionRecord))
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["data"]["authenticated"] is False

    protected = client.get("/api/v1/nodes")
    assert protected.status_code == 401
    assert protected.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_read_routes_require_viewer_session_but_health_and_auth_me_are_public(monkeypatch):
    _create_user(monkeypatch, username="reader")
    client = _client()

    assert client.get("/").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200

    unauthenticated = client.get("/api/v1/nodes")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["detail"]["code"] == "AUTH_REQUIRED"

    _login(client, username="reader")
    authenticated = client.get("/api/v1/nodes")
    assert authenticated.status_code == 200
    assert authenticated.json()["ok"] is True


def test_origin_guard_rejects_unexpected_unsafe_origins(monkeypatch):
    _create_user(monkeypatch, username="origin-user")
    client = _client()

    null_origin = client.post(
        "/api/v1/auth/login",
        json={"username": "origin-user", "password": "correct horse battery staple"},
        headers={"Origin": "null"},
    )
    assert null_origin.status_code == 403
    assert null_origin.json()["detail"]["code"] == "FORBIDDEN_ORIGIN"

    unknown_origin = client.post(
        "/api/v1/auth/login",
        json={"username": "origin-user", "password": "correct horse battery staple"},
        headers={"Origin": "https://evil.example.invalid"},
    )
    assert unknown_origin.status_code == 403
    assert unknown_origin.json()["detail"]["code"] == "FORBIDDEN_ORIGIN"

    safe_get = client.get("/api/v1/auth/me", headers={"Origin": "https://evil.example.invalid"})
    assert safe_get.status_code == 200


def test_mutation_routes_require_operator_before_calling_mutation_functions(monkeypatch):
    _create_user(monkeypatch, username="viewer-only", role="viewer")
    client = _client()

    create_payload = {"proxmox_mutation_acknowledged": True}
    start_payload = {"vm_start_acknowledged": True, "idempotency_key": "authz"}
    guided_payload = {
        "node_id": "node-a",
        "vmid": 306,
        "idempotency_key": "authz-guided",
        "qm_unlock_risk_acknowledged": True,
    }

    with patch("app.api.v1.router.get_default_proxmox_mutation_client") as client_factory, patch(
        "app.api.v1.router.run_proxmox_create"
    ) as create_mutation, patch("app.api.v1.router.record_vm_create_request") as create_record, patch(
        "app.api.v1.router.run_vm_start"
    ) as start_mutation, patch(
        "app.api.v1.router.plan_guided_qm_unlock"
    ) as guided_plan, patch(
        "app.api.v1.router.attest_guided_qm_operation"
    ) as guided_attest, patch(
        "app.api.v1.router.verify_guided_qm_operation"
    ) as guided_verify:
        create_unauth = client.post("/api/v1/vm-create/authz/proxmox-create", json=create_payload)
        start_unauth = client.post("/api/v1/nodes/node-a/vms/306/actions/start", json=start_payload)
        guided_plan_unauth = client.post("/api/v1/operations/guided-qm/vm-unlock", json=guided_payload)
        guided_attest_unauth = client.post(
            "/api/v1/operations/guided-authz/operator-attestation",
            json={"plan_digest": "sha256:" + "0" * 64, "command_executed": True},
        )
        guided_verify_unauth = client.post(
            "/api/v1/operations/guided-authz/verification",
            json={"plan_digest": "sha256:" + "0" * 64},
        )
        assert create_unauth.status_code == 401
        assert start_unauth.status_code == 401
        assert guided_plan_unauth.status_code == 401
        assert guided_attest_unauth.status_code == 401
        assert guided_verify_unauth.status_code == 401

        _login(client, username="viewer-only")
        create_viewer = client.post("/api/v1/vm-create/authz/proxmox-create", json=create_payload)
        start_viewer = client.post("/api/v1/nodes/node-a/vms/306/actions/start", json=start_payload)
        guided_plan_viewer = client.post("/api/v1/operations/guided-qm/vm-unlock", json=guided_payload)
        guided_attest_viewer = client.post(
            "/api/v1/operations/guided-authz/operator-attestation",
            json={"plan_digest": "sha256:" + "0" * 64, "command_executed": True},
        )
        guided_verify_viewer = client.post(
            "/api/v1/operations/guided-authz/verification",
            json={"plan_digest": "sha256:" + "0" * 64},
        )
        assert create_viewer.status_code == 403
        assert start_viewer.status_code == 403
        assert guided_plan_viewer.status_code == 403
        assert guided_attest_viewer.status_code == 403
        assert guided_verify_viewer.status_code == 403

        client_factory.assert_not_called()
        create_mutation.assert_not_called()
        create_record.assert_not_called()
        start_mutation.assert_not_called()
        guided_plan.assert_not_called()
        guided_attest.assert_not_called()
        guided_verify.assert_not_called()


def test_drs_approval_packet_route_requires_operator_before_local_or_proxmox_work(monkeypatch):
    _create_user(monkeypatch, username="drs-viewer", role="viewer")
    client = _client()
    path = "/api/v1/drs/recommendations/authz-rec/approval-packets"

    with patch("app.api.v1.router.create_approval_packet_and_job_intent") as create_local_intent, patch(
        "app.api.v1.router.get_default_proxmox_mutation_client"
    ) as mutation_client_factory, patch("app.api.v1.router.run_proxmox_create") as create_mutation, patch(
        "app.api.v1.router.record_job_run"
    ) as record_job_run:
        unauthenticated = client.post(path, json={"warning_acknowledged": True})
        assert unauthenticated.status_code == 401
        assert unauthenticated.json()["detail"]["code"] == "AUTH_REQUIRED"

        _login(client, username="drs-viewer")
        viewer = client.post(path, json={"warning_acknowledged": True})
        assert viewer.status_code == 403
        assert viewer.json()["detail"]["code"] == "AUTH_FORBIDDEN"

        create_local_intent.assert_not_called()
        mutation_client_factory.assert_not_called()
        create_mutation.assert_not_called()
        record_job_run.assert_not_called()


def test_drs_explicit_test_candidate_routes_require_operator_before_adapter_or_local_work(monkeypatch):
    _create_user(monkeypatch, username="drs-explicit-viewer", role="viewer")
    client = _client()
    paths = [
        "/api/v1/drs/explicit-test-candidates/check",
        "/api/v1/drs/explicit-test-candidates/approval-packets",
    ]
    payload = {
        "explicit_test_vm_acknowledged": True,
        "vm_identity_id": "vmid-authz",
        "vmid": 140,
        "source_node_id": "node-a",
        "target_node_id": "node-b",
    }

    with patch("app.api.v1.router._inventory_adapter") as inventory, patch(
        "app.api.v1.router.build_drs_check_result"
    ) as build_check, patch("app.api.v1.router.create_approval_packet_and_job_intent") as create_local_intent, patch(
        "app.api.v1.router.get_default_drs_proxmox_migration_client"
    ) as drs_client_factory:
        for path in paths:
            unauthenticated = client.post(path, json=payload)
            assert unauthenticated.status_code == 401
            assert unauthenticated.json()["detail"]["code"] == "AUTH_REQUIRED"

        _login(client, username="drs-explicit-viewer")
        for path in paths:
            viewer = client.post(path, json=payload)
            assert viewer.status_code == 403
            assert viewer.json()["detail"]["code"] == "AUTH_FORBIDDEN"

        inventory.assert_not_called()
        build_check.assert_not_called()
        create_local_intent.assert_not_called()
        drs_client_factory.assert_not_called()


def test_drs_policy_put_requires_operator_before_service_or_db_mutation(monkeypatch):
    _create_user(monkeypatch, username="drs-policy-viewer", role="viewer")
    client = _client()
    path = "/api/v1/drs/policies/vmid-authz"
    payload = {
        "policy": "allowed",
        "reason": "authz should block before service",
        "policy_change_acknowledged": True,
        "expected_observation": {
            "cluster_id": "cluster-a",
            "node_id": "node-a",
            "vmid": 101,
            "fingerprint_hash": "sha256:test",
            "observed_at": "2026-05-31T00:00:00+00:00",
        },
    }

    with patch("app.api.v1.router.update_drs_policy") as update_policy:
        unauthenticated = client.put(path, json=payload)
        assert unauthenticated.status_code == 401
        assert unauthenticated.json()["detail"]["code"] == "AUTH_REQUIRED"

        _login(client, username="drs-policy-viewer")
        viewer = client.put(path, json=payload)
        assert viewer.status_code == 403
        assert viewer.json()["detail"]["code"] == "AUTH_FORBIDDEN"

        update_policy.assert_not_called()


def test_drs_execute_and_reconcile_preview_routes_require_operator_before_work(monkeypatch):
    _create_user(monkeypatch, username="drs-exec-viewer", role="viewer")
    client = _client()
    execute_path = "/api/v1/drs/migration-jobs/authz-job/execute"
    reconcile_preview_path = "/api/v1/drs/migration-jobs/authz-job/reconcile-preview"
    reconcile_path = "/api/v1/drs/migration-jobs/authz-job/reconcile"

    with patch("app.api.v1.router.execute_drs_migration_job") as execute_drs, patch(
        "app.api.v1.router.build_drs_migration_reconciliation_preview"
    ) as preview_reconcile, patch(
        "app.api.v1.router.reconcile_drs_migration_job"
    ) as reconcile_drs, patch(
        "app.api.v1.router.get_default_drs_proxmox_migration_client"
    ) as drs_client_factory, patch(
        "app.api.v1.router.get_default_proxmox_mutation_client"
    ) as create_vm_client_factory, patch(
        "app.api.v1.router.run_proxmox_create"
    ) as create_mutation:
        execute_unauthenticated = client.post(execute_path, json={})
        reconcile_preview_unauthenticated = client.post(reconcile_preview_path, json={})
        reconcile_unauthenticated = client.post(reconcile_path, json={})
        assert execute_unauthenticated.status_code == 401
        assert reconcile_preview_unauthenticated.status_code == 401
        assert reconcile_unauthenticated.status_code == 401
        assert execute_unauthenticated.json()["detail"]["code"] == "AUTH_REQUIRED"
        assert reconcile_preview_unauthenticated.json()["detail"]["code"] == "AUTH_REQUIRED"
        assert reconcile_unauthenticated.json()["detail"]["code"] == "AUTH_REQUIRED"

        _login(client, username="drs-exec-viewer")
        execute_viewer = client.post(execute_path, json={})
        reconcile_preview_viewer = client.post(reconcile_preview_path, json={})
        reconcile_viewer = client.post(reconcile_path, json={})
        assert execute_viewer.status_code == 403
        assert reconcile_preview_viewer.status_code == 403
        assert reconcile_viewer.status_code == 403
        assert execute_viewer.json()["detail"]["code"] == "AUTH_FORBIDDEN"
        assert reconcile_preview_viewer.json()["detail"]["code"] == "AUTH_FORBIDDEN"
        assert reconcile_viewer.json()["detail"]["code"] == "AUTH_FORBIDDEN"

        execute_drs.assert_not_called()
        preview_reconcile.assert_not_called()
        reconcile_drs.assert_not_called()
        drs_client_factory.assert_not_called()
        create_vm_client_factory.assert_not_called()
        create_mutation.assert_not_called()


def test_viewer_cannot_write_create_vm_workflow_state(monkeypatch):
    _create_user(monkeypatch, username="workflow-viewer", role="viewer")
    client = _client()
    _login(client, username="workflow-viewer")

    with patch("app.api.v1.router.record_job_run") as record_job_run:
        for path in (
            "/api/v1/vm-create/drafts",
            "/api/v1/vm-create/workflow-viewer/preflight",
            "/api/v1/vm-create/workflow-viewer/plan",
            "/api/v1/vm-create/workflow-viewer/approve",
            "/api/v1/vm-create/workflow-viewer/proxmox-preview",
        ):
            response = client.post(path, json={"job_id": "viewer-should-not-write"})
            assert response.status_code == 403
            assert response.json()["detail"]["code"] == "AUTH_FORBIDDEN"

        record_job_run.assert_not_called()


def test_vm_start_route_passes_authenticated_actor_from_session(monkeypatch):
    _create_user(monkeypatch, username="starter", role="operator")
    client = _client()
    _login(client, username="starter")
    captured = {}

    def fake_start(**kwargs):
        captured.update(kwargs)
        return {
            "job_id": "vm-start-auth-actor",
            "status": "completed",
            "proxmox_mutation_enabled": True,
            "side_effects": [],
        }

    with patch("app.api.v1.router.run_vm_start", side_effect=fake_start):
        response = client.post(
            "/api/v1/nodes/node-a/vms/306/actions/start",
            json={"vm_start_acknowledged": True, "idempotency_key": "actor-start"},
        )

    assert response.status_code == 200, response.text
    assert captured["actor"]["username"] == "starter"
    assert captured["actor"]["role"] == "operator"


def test_guided_qm_plan_route_passes_authenticated_actor_from_session(monkeypatch):
    _create_user(monkeypatch, username="qm-operator", role="operator")
    client = _client()
    _login(client, username="qm-operator")
    captured = {}

    def fake_plan(**kwargs):
        captured.update(kwargs)
        return {"operation": {"operation_id": "guided-session-actor"}}

    with patch("app.api.v1.router.plan_guided_qm_unlock", side_effect=fake_plan):
        response = client.post(
            "/api/v1/operations/guided-qm/vm-unlock",
            json={
                "node_id": "node-a",
                "vmid": 306,
                "idempotency_key": "guided-session-actor",
                "qm_unlock_risk_acknowledged": True,
            },
        )

    assert response.status_code == 200, response.text
    assert captured["actor"]["username"] == "qm-operator"
    assert captured["actor"]["role"] == "operator"


def _assert_job_status_actor(job_id: str, *, username: str, role: str, forbidden_username: str = "") -> None:
    from app.jobs.artifacts import read_artifact_text
    from app.jobs.runs import get_job_run

    job = get_job_run(job_id)
    details = job["details"]
    assert details["actor_user_id"]
    assert details["actor_username"] == username
    assert details["actor_role"] == role
    assert details["actor"]["username"] == username
    if forbidden_username:
        assert details["actor_username"] != forbidden_username

    status_artifact = next(artifact for artifact in job["artifacts"] if artifact["type"] == "job_status")
    status_payload = json.loads(read_artifact_text(status_artifact))
    status_details = status_payload["details"]
    assert status_details["actor_user_id"]
    assert status_details["actor_username"] == username
    assert status_details["actor_role"] == role
    assert status_details["actor"]["username"] == username
    if forbidden_username:
        assert status_details["actor_username"] != forbidden_username


def test_operator_create_vm_prelive_routes_record_unredacted_session_actor(monkeypatch):
    _create_user(monkeypatch, username="secret-admin", role="operator")
    client = _client()
    _login(client, username="secret-admin")

    common = {
        "operator_id": "payload-spoof",
        "bridge_id": "vmbr0",
        "static_ip": "192.168.2.144",
        "prefix": 24,
        "gateway": "192.168.2.1",
    }

    draft_payload = {**common, "job_id": "job-secret-draft"}
    draft = client.post("/api/v1/vm-create/drafts", json=draft_payload)
    assert draft.status_code == 200, draft.text
    _assert_job_status_actor("job-secret-draft", username="secret-admin", role="operator", forbidden_username="payload-spoof")

    preflight_payload = {**common, "job_id": "job-secret-preflight"}
    preflight = client.post("/api/v1/vm-create/draft-secret-preflight/preflight", json=preflight_payload)
    assert preflight.status_code == 200, preflight.text
    _assert_job_status_actor("job-secret-preflight", username="secret-admin", role="operator", forbidden_username="payload-spoof")

    plan_payload = {**common, "job_id": "job-secret-plan"}
    plan = client.post("/api/v1/vm-create/draft-secret-plan/plan", json=plan_payload)
    assert plan.status_code == 200, plan.text
    review = plan.json()["data"]["review_confirm"]
    _assert_job_status_actor("job-secret-plan", username="secret-admin", role="operator", forbidden_username="payload-spoof")

    approved_payload = {
        **plan_payload,
        "plan_artifact_id": review["plan_artifact_id"],
        "review_summary_checksum": review["review_summary_checksum"],
        "yellow_risk_acknowledged": False,
    }
    approve = client.post("/api/v1/vm-create/draft-secret-plan/approve", json=approved_payload)
    assert approve.status_code == 200, approve.text
    _assert_job_status_actor("job-secret-plan", username="secret-admin", role="operator", forbidden_username="payload-spoof")

    preview = client.post("/api/v1/vm-create/draft-secret-plan/proxmox-preview", json=approved_payload)
    assert preview.status_code == 200, preview.text
    _assert_job_status_actor("job-secret-plan", username="secret-admin", role="operator", forbidden_username="payload-spoof")


def test_admin_can_access_protected_create_vm_mutation_route(monkeypatch):
    _create_user(monkeypatch, username="admin-user", role="admin")
    client = _client()
    _login(client, username="admin-user")
    handler = AsyncMock(return_value={"ok": True, "data": {"status": "mocked"}, "meta": {"mode": "mocked"}})

    with patch("app.api.v1.router.create_vm_draft_proxmox_native", handler):
        response = client.post(
            "/api/v1/vm-create/admin-authz/proxmox-create",
            json={"proxmox_mutation_acknowledged": True},
        )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "mocked"
    handler.assert_awaited_once()
    _, kwargs = handler.await_args
    assert kwargs["actor"].username == "admin-user"
    assert kwargs["actor"].role == "admin"


def test_vm_start_job_and_artifact_include_flat_actor_fields(monkeypatch):
    _create_user(monkeypatch, username="starter-evidence", role="operator")
    client = _client()
    _login(client, username="starter-evidence")

    from app.proxmox.models import VmInventory

    class StubInventoryAdapter:
        source = "test_read_only"

        def list_vms(self):
            return [
                VmInventory(
                    vmid=306,
                    name="stopped-app",
                    node_id="node-a",
                    status="stopped",
                    template=False,
                    cpu=2,
                    memory_mb=4096,
                    disk_gb=40,
                )
            ]

        def list_templates(self):
            return []

    class RecordingStartClient:
        def redacted_connection_context(self):
            return {"mode": "native_mutation"}

        def start_vm(self, *, node, vmid):
            return f"UPID:{node}:0001:start"

        def wait_for_task(self, *, node, upid):
            return {"node": node, "upid": upid, "status": "stopped", "exitstatus": "OK"}

        def get_vm_status(self, *, node, vmid):
            return {"node": node, "vmid": vmid, "name": "stopped-app", "status": "running"}

    with patch("app.api.v1.router._inventory_adapter", return_value=StubInventoryAdapter()), patch(
        "app.api.v1.router.get_default_proxmox_mutation_client",
        return_value=RecordingStartClient(),
    ):
        response = client.post(
            "/api/v1/nodes/node-a/vms/306/actions/start",
            json={
                "operator_id": "payload-spoof",
                "vm_start_acknowledged": True,
                "idempotency_key": "actor-flat-start",
                "expected_name": "stopped-app",
                "expected_status": "stopped",
            },
        )

    assert response.status_code == 200, response.text
    result = response.json()["data"]

    from app.jobs.artifacts import read_artifact_text
    from app.jobs.runs import get_job_run

    job = get_job_run(result["job_id"])
    details = job["details"]
    assert details["actor_username"] == "starter-evidence"
    assert details["actor_role"] == "operator"
    assert details["actor"]["username"] == "starter-evidence"
    assert details["actor_username"] != "payload-spoof"

    observed_payload = json.loads(read_artifact_text(result["observed_after_artifact"]))
    assert observed_payload["actor_username"] == "starter-evidence"
    assert observed_payload["actor_role"] == "operator"
    assert observed_payload["actor"]["username"] == "starter-evidence"
    assert observed_payload["actor_username"] != "payload-spoof"


def test_create_vm_records_authenticated_actor_not_payload_operator_id(monkeypatch):
    _create_user(monkeypatch, username="creator", role="operator")
    client = _client()
    _login(client, username="creator")

    draft_id = "draft-auth-actor-create"
    payload = {
        "operator_id": "payload-spoof",
        "job_id": "job-auth-actor-create",
        "bridge_id": "vmbr0",
        "static_ip": "192.168.2.144",
        "prefix": 24,
        "gateway": "192.168.2.1",
    }
    plan_response = client.post(f"/api/v1/vm-create/{draft_id}/plan", json=payload)
    assert plan_response.status_code == 200, plan_response.text
    review = plan_response.json()["data"]["review_confirm"]

    def fake_create(plan, *, run_dir, client):
        from app.jobs.artifacts import write_json_artifact

        artifact = write_json_artifact(
            run_dir=run_dir,
            job_id=plan.job_id,
            artifact_type="observed_after",
            filename="observed_after.json",
            payload={
                "vmid": plan.vmid,
                "target_node_id": plan.target_node_id,
                "exists": True,
                "status": "stopped",
                "fingerprint": {"hash": "sha256:" + "1" * 64},
            },
        )
        return {
            "job_id": plan.job_id,
            "manifest_id": plan.manifest_id,
            "vmid": plan.vmid,
            "target_node_id": plan.target_node_id,
            "success": True,
            "status": "completed",
            "message": "VM exists on target node and is stopped",
            "observed_after": {"status": "stopped", "fingerprint": {"hash": "sha256:" + "1" * 64}},
            "observed_after_artifact": artifact.to_dict(),
            "artifacts": [artifact.to_dict()],
            "side_effects": ["proxmox_clone_invoked", "proxmox_task_polled", "proxmox_config_updated", "proxmox_post_check_observed"],
        }

    with patch("app.api.v1.router.get_default_proxmox_mutation_client", return_value=object()), patch(
        "app.api.v1.router.run_proxmox_create",
        side_effect=fake_create,
    ):
        create_response = client.post(
            f"/api/v1/vm-create/{draft_id}/proxmox-create",
            json={
                **payload,
                "plan_artifact_id": review["plan_artifact_id"],
                "review_summary_checksum": review["review_summary_checksum"],
                "yellow_risk_acknowledged": False,
                "proxmox_mutation_acknowledged": True,
            },
        )

    assert create_response.status_code == 200, create_response.text
    request_record = create_response.json()["data"]["vm_create_request"]
    assert request_record["actor_username"] == "creator"
    assert request_record["actor_role"] == "operator"
    assert request_record["actor"]["username"] == "creator"
    assert request_record["actor"]["role"] == "operator"
    assert request_record["actor"]["username"] != payload["operator_id"]

    from app.jobs.artifacts import read_artifact_text
    from app.jobs.runs import get_job_run

    job = get_job_run(payload["job_id"])
    details = job["details"]
    assert details["actor_username"] == "creator"
    assert details["actor_role"] == "operator"
    assert details["actor"]["username"] == "creator"
    assert details["actor_username"] != payload["operator_id"]
    status_artifact = next(artifact for artifact in job["artifacts"] if artifact["type"] == "job_status")
    status_payload = json.loads(read_artifact_text(status_artifact))
    assert status_payload["details"]["actor_username"] == "creator"
    assert status_payload["details"]["actor_role"] == "operator"
    assert status_payload["details"]["actor"]["username"] == "creator"
    assert status_payload["details"]["actor_username"] != payload["operator_id"]

    from app.db.models import VmCreateRequestRecord
    from app.db.session import session_scope

    with session_scope() as session:
        row = session.get(VmCreateRequestRecord, payload["job_id"])
        assert row.actor_user_id
        assert row.actor_username == "creator"
        assert row.actor_role == "operator"
        assert row.actor_username != payload["operator_id"]
