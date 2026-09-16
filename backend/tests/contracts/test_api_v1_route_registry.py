"""Characterization contract for the public ``/api/v1`` route registry."""

from __future__ import annotations

from fastapi.routing import APIRoute

from app.auth.dependencies import require_admin, require_operator, require_user, require_viewer


EXPECTED_API_V1_ROUTES = (
    ("GET", "/api/v1/admin/sessions", "admin_list_sessions", 200),
    ("POST", "/api/v1/admin/sessions/{session_id}/revoke", "admin_revoke_session", 200),
    ("GET", "/api/v1/admin/users", "admin_list_users", 200),
    ("POST", "/api/v1/admin/users", "admin_create_user", 201),
    ("POST", "/api/v1/admin/users/{username}/disable", "admin_disable_user", 200),
    ("POST", "/api/v1/admin/users/{username}/reset-password", "admin_reset_password", 200),
    ("PATCH", "/api/v1/admin/users/{username}/role", "admin_set_user_role", 200),
    ("POST", "/api/v1/auth/change-password", "change_password", 200),
    ("POST", "/api/v1/auth/login", "login", 200),
    ("POST", "/api/v1/auth/logout", "logout", 200),
    ("GET", "/api/v1/auth/me", "me", 200),
    ("GET", "/api/v1/cluster/summary", "cluster_summary", 200),
    ("GET", "/api/v1/insights", "get_insights_route", 200),
    ("GET", "/api/v1/jobs", "list_jobs", 200),
    ("GET", "/api/v1/jobs/{job_id}", "get_job", 200),
    ("GET", "/api/v1/jobs/{job_id}/artifacts", "list_job_artifacts", 200),
    ("GET", "/api/v1/networks", "list_networks", 200),
    ("GET", "/api/v1/nodes", "list_nodes", 200),
    (
        "POST",
        "/api/v1/nodes/{node_id}/vms/{vmid}/actions/shutdown",
        "shutdown_vm_action_route",
        200,
    ),
    (
        "POST",
        "/api/v1/nodes/{node_id}/vms/{vmid}/actions/start",
        "start_vm_action_route",
        200,
    ),
    (
        "POST",
        "/api/v1/nodes/{node_id}/vms/{vmid}/post-create-readiness-evidence",
        "post_create_readiness_evidence_route",
        200,
    ),
    ("GET", "/api/v1/operations", "list_operations_route", 200),
    (
        "POST",
        "/api/v1/operations/guided-qm/vm-unlock",
        "plan_guided_qm_unlock_route",
        200,
    ),
    ("GET", "/api/v1/operations/{operation_id}", "get_operation_route", 200),
    (
        "POST",
        "/api/v1/operations/{operation_id}/operator-attestation",
        "attest_guided_qm_operation_route",
        200,
    ),
    (
        "POST",
        "/api/v1/operations/{operation_id}/recovery/observe",
        "observe_operation_recovery_route",
        200,
    ),
    (
        "POST",
        "/api/v1/operations/{operation_id}/verification",
        "verify_guided_qm_operation_route",
        200,
    ),
    ("GET", "/api/v1/profiles", "list_profiles", 200),
    ("GET", "/api/v1/risks", "list_risks", 200),
    (
        "GET",
        "/api/v1/setup/proxmox/connection",
        "get_proxmox_connection_status",
        200,
    ),
    ("GET", "/api/v1/storage", "list_storage", 200),
    ("GET", "/api/v1/templates", "list_templates", 200),
    ("POST", "/api/v1/vm-create/drafts", "create_vm_draft_route", 200),
    ("GET", "/api/v1/vm-create/suggested-vmid", "suggested_vm_id_route", 200),
    ("POST", "/api/v1/vm-create/{draft_id}/approve", "approve_vm_draft_route", 200),
    ("POST", "/api/v1/vm-create/{draft_id}/plan", "plan_vm_draft_route", 200),
    ("POST", "/api/v1/vm-create/{draft_id}/preflight", "preflight_vm_draft_route", 200),
    (
        "POST",
        "/api/v1/vm-create/{draft_id}/proxmox-create",
        "create_vm_draft_proxmox_native_route",
        200,
    ),
    (
        "POST",
        "/api/v1/vm-create/{draft_id}/proxmox-preview",
        "preview_vm_draft_proxmox_create_route",
        200,
    ),
    ("GET", "/api/v1/vms", "list_vms", 200),
    ("GET", "/api/v1/vms/{vmid}", "get_vm", 200),
)

OPERATOR_ROUTES = {
    ("GET", "/api/v1/vm-create/suggested-vmid"),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/shutdown"),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/start"),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/post-create-readiness-evidence"),
    ("POST", "/api/v1/operations/guided-qm/vm-unlock"),
    ("POST", "/api/v1/operations/{operation_id}/operator-attestation"),
    ("POST", "/api/v1/operations/{operation_id}/recovery/observe"),
    ("POST", "/api/v1/operations/{operation_id}/verification"),
    ("POST", "/api/v1/vm-create/drafts"),
    ("POST", "/api/v1/vm-create/{draft_id}/approve"),
    ("POST", "/api/v1/vm-create/{draft_id}/plan"),
    ("POST", "/api/v1/vm-create/{draft_id}/preflight"),
    ("POST", "/api/v1/vm-create/{draft_id}/proxmox-create"),
    ("POST", "/api/v1/vm-create/{draft_id}/proxmox-preview"),
}

PUBLIC_AUTH_ROUTES = {
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/logout"),
    ("GET", "/api/v1/auth/me"),
}


def _api_v1_routes() -> list[APIRoute]:
    from app.main import app

    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1")
    ]


def _methods(route: APIRoute) -> tuple[str, ...]:
    return tuple(sorted((route.methods or set()) - {"HEAD", "OPTIONS"}))


def _route_registry_entry(route: APIRoute) -> tuple[str, str, str, int]:
    methods = _methods(route)
    assert len(methods) == 1, f"Expected one public method for {route.path}, got {methods}"
    return (methods[0], route.path, route.name, route.status_code or 200)


def _access_dependencies(route: APIRoute) -> set[object]:
    known_dependencies = {require_viewer, require_operator, require_user, require_admin}
    return {
        dependency.call
        for dependency in route.dependant.dependencies
        if dependency.call in known_dependencies
    }


def test_api_v1_route_registry_is_unchanged_during_router_extraction():
    actual = tuple(
        sorted(
            (_route_registry_entry(route) for route in _api_v1_routes()),
            key=lambda entry: (entry[1], entry[0], entry[2]),
        )
    )

    assert len(actual) == 41
    assert actual == EXPECTED_API_V1_ROUTES


def test_api_v1_access_boundaries_are_unchanged_during_router_extraction():
    for route in _api_v1_routes():
        methods = _methods(route)
        assert len(methods) == 1
        route_key = (methods[0], route.path)
        dependencies = _access_dependencies(route)

        if route_key in PUBLIC_AUTH_ROUTES:
            assert dependencies == set(), route_key
        elif route_key == ("POST", "/api/v1/auth/change-password"):
            assert dependencies == {require_user}, route_key
        elif route.path.startswith("/api/v1/admin/"):
            assert dependencies == {require_admin}, route_key
        elif route_key in OPERATOR_ROUTES:
            assert dependencies == {require_viewer, require_operator}, route_key
        else:
            assert dependencies == {require_viewer}, route_key
