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
    ("GET", "/api/v1/maintenance/nodes/{node_id}", "node_maintenance", 200),
    ("GET", "/api/v1/monitoring/nodes/{node_id}", "node_metrics", 200),
    ("GET", "/api/v1/monitoring/nodes/{node_id}/storage/{storage_id}", "storage_metrics", 200),
    ("GET", "/api/v1/monitoring/nodes/{node_id}/vms/{vmid}", "vm_metrics", 200),
    ("GET", "/api/v1/monitoring/operation-alerts", "get_operation_alerts", 200),
    ("GET", "/api/v1/networks", "list_networks", 200),
    ("GET", "/api/v1/nodes", "list_nodes", 200),
    ("POST", "/api/v1/nodes/{node_id}/host-network/{bridge_id}/actions/configure", "configure_bridge", 200),
    ("POST", "/api/v1/nodes/{node_id}/host-network/{bridge_id}/review", "review_bridge", 200),
    ("POST", "/api/v1/nodes/{node_id}/host-storage/{storage_id}/actions/configure", "configure_storage", 200),
    ("POST", "/api/v1/nodes/{node_id}/host-storage/{storage_id}/review", "review_storage", 200),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/backup", "execute_backup", 200),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/clone", "execute_clone", 200),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/compute", "execute_compute", 200),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/delete", "execute_delete", 200),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/disk-resize", "execute_disk", 200),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/image-build", "execute_image_build", 200),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/image-cleanup", "execute_image_cleanup", 200),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/migrate", "execute_migrate", 200),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/network", "execute_network", 200),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/restore", "execute_restore", 200),
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
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/template", "execute_template", 200),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/backup-review", "review_backup", 200),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/backups", "list_backups", 200),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/clone", "review_clone", 200),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/compute", "review_compute", 200),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/console", "review_console", 200),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/deletion", "review_delete", 200),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/disks/scsi0", "review_disk", 200),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/image-build", "review_image_build", 200),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/image-cleanup", "review_image_cleanup", 200),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/migrate", "review_migrate", 200),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/network", "review_network", 200),
    (
        "POST",
        "/api/v1/nodes/{node_id}/vms/{vmid}/post-create-readiness-evidence",
        "post_create_readiness_evidence_route",
        200,
    ),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/restore-review", "review_restore", 200),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/template-conversion", "review_template", 200),
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
    ("GET", "/api/v1/operations/{operation_id}/restore-report", "read_restore_report", 200),
    ("GET", "/api/v1/operations/{operation_id}/template-test", "get_template_test_report", 200),
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
    ("GET", "/api/v1/setup/proxmox/registrations", "list_attempts", 200),
    ("POST", "/api/v1/setup/proxmox/registrations", "prepare", 200),
    ("GET", "/api/v1/setup/proxmox/registrations/{attempt_id}", "status", 200),
    ("POST", "/api/v1/setup/proxmox/registrations/{attempt_id}/{action}", "action", 200),
    ("GET", "/api/v1/storage", "list_storage", 200),
    ("GET", "/api/v1/templates", "list_templates", 200),
    ("GET", "/api/v1/templates/cloud-images", "cloud_image_catalog", 200),
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
    ("GET", "/api/v1/maintenance/nodes/{node_id}"),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/image-cleanup"),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/image-cleanup"),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/deletion"),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/delete"),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/template"),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/image-build"),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/image-build"),
    ("GET", "/api/v1/templates/cloud-images"),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/template-conversion"),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/clone"),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/backup"),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/restore"),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/migrate"),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/migrate"),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/restore-review"),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/backup-review"),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/clone"),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/network"),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/network"),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/compute"),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/console"),
    ("GET", "/api/v1/nodes/{node_id}/vms/{vmid}/disks/scsi0"),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/disk-resize"),
    ("POST", "/api/v1/nodes/{node_id}/vms/{vmid}/actions/compute"),
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

    assert len(actual) == 81
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
        elif route.path.startswith("/api/v1/setup/proxmox/registrations") or '/host-storage/' in route.path or '/host-network/' in route.path:
            assert dependencies == {require_viewer, require_admin}, route_key
        elif route_key in OPERATOR_ROUTES:
            assert dependencies == {require_viewer, require_operator}, route_key
        else:
            assert dependencies == {require_viewer}, route_key
