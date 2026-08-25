"""Architecture contracts for the removed DRS runtime and API surface."""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.routing import APIRoute


BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"
REMOVED_RUNTIME_PATHS = (
    APP_ROOT / "drs" / "__init__.py",
    APP_ROOT / "api" / "v1" / "drs_compat.py",
    APP_ROOT / "proxmox" / "drs_migration.py",
)
FORBIDDEN_RUNTIME_IMPORTS = (
    "app.drs",
    "app.proxmox.drs_migration",
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(
                f"{node.module}.{alias.name}"
                for alias in node.names
                if alias.name != "*"
            )
    return modules


def test_drs_runtime_packages_and_compatibility_router_are_absent():
    assert not [
        str(path.relative_to(BACKEND_ROOT))
        for path in REMOVED_RUNTIME_PATHS
        if path.exists()
    ]
    assert list((APP_ROOT / "drs").glob("*.py")) == []


def test_drs_api_surface_is_absent():
    from app.main import app

    drs_routes = [
        route.path
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1/drs")
    ]

    assert drs_routes == []


def test_active_backend_does_not_import_removed_drs_runtime():
    violations: dict[str, list[str]] = {}
    for path in APP_ROOT.rglob("*.py"):
        imported = _imported_modules(path)
        forbidden = sorted(
            module
            for module in imported
            if any(
                module == prefix or module.startswith(f"{prefix}.")
                for prefix in FORBIDDEN_RUNTIME_IMPORTS
            )
        )
        if forbidden:
            violations[str(path.relative_to(BACKEND_ROOT))] = forbidden

    assert violations == {}


def test_active_backend_has_no_drs_credential_configuration_dependency():
    offenders = [
        str(path.relative_to(BACKEND_ROOT))
        for path in APP_ROOT.rglob("*.py")
        if "PROXMOX_DRS_" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_drs_common_operation_module_and_recovery_registration_are_absent():
    from app.operations.recovery.domain import RECOVERY_KINDS

    assert not (APP_ROOT / "operations" / "drs_migration").exists()
    assert not {kind for kind in RECOVERY_KINDS if "drs" in kind.lower()}
