"""API contract tests for shared Operation list queries."""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.operations.core.application import InvalidOperationQuery, OperationQueryNotFound


def test_operation_list_route_is_additive_and_keeps_existing_detail_routes():
    from app.main import app

    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/v1/operations" in paths
    assert "/api/v1/operations/{operation_id}" in paths
    assert "/api/v1/operations/guided-qm/vm-unlock" in paths


def test_operation_list_route_forwards_bounded_filters_and_envelope():
    from app.api.v1 import operations as api

    summaries = [{"operation_id": "operation-1", "status": "succeeded"}]
    with patch.object(api, "list_operations", return_value=summaries) as query:
        response = api.list_operations_route(
            status="succeeded",
            operation_type="vm_start",
            limit=25,
        )

    query.assert_called_once_with(status="succeeded", operation_type="vm_start", limit=25)
    assert response["ok"] is True
    assert response["data"] == summaries
    assert response["meta"]["filters"] == {
        "status": "succeeded",
        "operation_type": "vm_start",
        "limit": 25,
    }


def test_operation_list_route_maps_invalid_query_to_422():
    from app.api.v1 import operations as api

    with patch.object(api, "list_operations", side_effect=InvalidOperationQuery("bad status")):
        with pytest.raises(HTTPException) as raised:
            api.list_operations_route(status="bad", operation_type=None, limit=50)

    assert raised.value.status_code == 422
    assert raised.value.detail["code"] == "INVALID_OPERATION_QUERY"


def test_operation_detail_route_uses_generic_not_found_contract():
    from app.api.v1 import operations as api

    with patch.object(api, "get_operation", side_effect=OperationQueryNotFound("missing-operation")):
        with pytest.raises(HTTPException) as raised:
            api.get_operation_route("missing-operation")

    assert raised.value.status_code == 404
    assert raised.value.detail["code"] == "GUIDED_QM_OPERATION_NOT_FOUND"
    assert raised.value.detail["canonical_code"] == "OPERATION_NOT_FOUND"
