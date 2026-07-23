"""Architecture contracts for the DRS HTTP/application compatibility split."""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.routing import APIRoute


BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"
DRS_ROOT = APP_ROOT / "drs"
APPLICATION_MODULE = BACKEND_ROOT / "app" / "drs" / "application.py"
DRS_COMPATIBILITY_MODULE = APP_ROOT / "api" / "v1" / "drs_compat.py"
DRS_JOB_PRODUCERS = {
    DRS_ROOT / "approval.py",
    DRS_ROOT / "execution.py",
}


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


def test_drs_application_does_not_depend_on_http_interface_modules():
    imported = _imported_modules(APPLICATION_MODULE)

    assert not {
        module
        for module in imported
        if module == "fastapi"
        or module.startswith("fastapi.")
        or module == "starlette"
        or module.startswith("starlette.")
        or module == "app.api"
        or module.startswith("app.api.")
    }


def test_all_drs_routes_are_owned_by_the_compatibility_child_router():
    from app.main import app

    drs_routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1/drs/")
    ]

    assert len(drs_routes) == 13
    assert {
        route.endpoint.__module__
        for route in drs_routes
    } == {"app.api.v1.drs_compat"}


def test_drs_does_not_integrate_with_common_operation_or_recovery():
    forbidden_prefixes = (
        "app.operations.core",
        "app.operations.recovery",
        "app.operations.drs_migration",
    )
    sources = [*DRS_ROOT.rglob("*.py"), DRS_COMPATIBILITY_MODULE]

    violations = {
        str(path.relative_to(BACKEND_ROOT)): sorted(
            module
            for module in _imported_modules(path)
            if any(
                module == prefix or module.startswith(f"{prefix}.")
                for prefix in forbidden_prefixes
            )
        )
        for path in sources
    }

    assert not {path: modules for path, modules in violations.items() if modules}


def test_drs_common_operation_module_and_recovery_registration_are_absent():
    from app.operations.recovery.domain import RECOVERY_KINDS

    assert not (APP_ROOT / "operations" / "drs_migration").exists()
    assert not {kind for kind in RECOVERY_KINDS if "drs" in kind.lower()}


def test_drs_backend_consumers_are_frozen_to_compatibility_boundary():
    consumers: set[Path] = set()
    for path in APP_ROOT.rglob("*.py"):
        if path.is_relative_to(DRS_ROOT):
            continue
        imported = _imported_modules(path)
        if any(
            module == "app.drs" or module.startswith("app.drs.")
            for module in imported
        ):
            consumers.add(path)

    assert consumers == {DRS_COMPATIBILITY_MODULE}


def test_drs_jobs_and_artifacts_producers_are_frozen():
    producers: set[Path] = set()
    for path in DRS_ROOT.rglob("*.py"):
        imported = _imported_modules(path)
        if any(
            module == "app.jobs"
            or module.startswith("app.jobs.")
            for module in imported
        ):
            producers.add(path)

    assert producers == DRS_JOB_PRODUCERS
