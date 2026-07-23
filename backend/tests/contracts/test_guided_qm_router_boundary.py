"""Architecture contracts for the Guided ``qm`` child router split."""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.routing import APIRoute


BACKEND_ROOT = Path(__file__).resolve().parents[2]
ROOT_ROUTER_MODULE = BACKEND_ROOT / "app" / "api" / "v1" / "router.py"


def test_api_v1_root_router_is_only_a_composition_root():
    tree = ast.parse(ROOT_ROUTER_MODULE.read_text(encoding="utf-8"))

    assert not [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]


def test_all_guided_qm_routes_are_owned_by_the_child_router():
    from app.main import app

    guided_paths = {
        "/api/v1/operations/guided-qm/vm-unlock",
        "/api/v1/operations/{operation_id}/operator-attestation",
        "/api/v1/operations/{operation_id}/verification",
    }
    guided_routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path in guided_paths
    ]

    assert {route.path for route in guided_routes} == guided_paths
    assert {
        route.endpoint.__module__
        for route in guided_routes
    } == {"app.api.v1.guided_qm"}
