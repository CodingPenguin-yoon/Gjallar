"""Architecture contracts for the Create VM transport/application split."""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.routing import APIRoute


BACKEND_ROOT = Path(__file__).resolve().parents[2]
APPLICATION_MODULE = BACKEND_ROOT / "app" / "vm_create" / "application.py"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_vm_create_application_does_not_depend_on_http_interface_modules():
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


def test_all_vm_create_routes_are_owned_by_the_compatibility_child_router():
    from app.main import app

    vm_create_routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1/vm-create/")
    ]

    assert len(vm_create_routes) == 7
    assert {
        route.endpoint.__module__
        for route in vm_create_routes
    } == {"app.api.v1.vm_create_compat"}
