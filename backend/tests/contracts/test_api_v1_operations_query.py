"""API contract tests for shared Operation list queries."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.operations.core.application import InvalidOperationQuery, OperationQueryNotFound
from app.operations.core.domain import OperationActor, OperationSpec
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.facade import get_operation


def test_operation_list_route_is_additive_and_keeps_existing_detail_routes():
    from app.main import app

    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/v1/operations" in paths
    assert "/api/v1/operations/{operation_id}" in paths
    assert "/api/v1/operations/{operation_id}/recovery/observe" in paths
    assert "/api/v1/operations/guided-qm/vm-unlock" in paths


def test_operation_list_route_forwards_bounded_filters_and_envelope():
    from app.api.v1 import operations as api

    summaries = [{"operation_id": "operation-1", "status": "succeeded"}]
    with patch.object(api, "list_operations", return_value=summaries) as query:
        response = api.list_operations_route(
            status="succeeded",
            operation_type="vm_start",
            target_type="proxmox_vm",
            target_id="vmid:306",
            limit=25,
        )

    query.assert_called_once_with(
        status="succeeded",
        operation_type="vm_start",
        target_type="proxmox_vm",
        target_id="vmid:306",
        limit=25,
    )
    assert response["ok"] is True
    assert response["data"] == summaries
    assert response["meta"]["filters"] == {
        "status": "succeeded",
        "operation_type": "vm_start",
        "target_type": "proxmox_vm",
        "target_id": "vmid:306",
        "limit": 25,
    }


def test_operation_list_route_keeps_existing_positional_status_type_limit_contract():
    from app.api.v1 import operations as api

    with patch.object(api, "list_operations", return_value=[]) as query:
        response = api.list_operations_route("succeeded", "vm_start", 25)

    query.assert_called_once_with(
        status="succeeded",
        operation_type="vm_start",
        target_type=None,
        target_id=None,
        limit=25,
    )
    assert response["meta"]["filters"]["limit"] == 25


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


def test_recovery_observe_route_forwards_fenced_operator_request():
    from app.api.v1 import operations as api

    actor = {"user_id": "user-1", "username": "operator", "role": "operator"}
    observed = {"operation": {"operation_id": "operation-1", "version": 8}}
    with patch.object(api, "observe_operation_recovery", return_value=observed) as observe:
        response = asyncio.run(
            api.observe_operation_recovery_route(
                "operation-1",
                {
                    "expected_version": 7,
                    "expected_checksum": "sha256:abc",
                    "idempotency_key": "observe-operation-1-v7",
                },
                actor=actor,
            )
        )

    observe.assert_called_once_with(
        "operation-1",
        actor=actor,
        expected_version=7,
        expected_checksum="sha256:abc",
        idempotency_key="observe-operation-1-v7",
    )
    assert response["data"] == observed
    assert response["meta"] == {
        "mode": "operation_recovery_observation",
        "mutation_enabled": False,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"expected_version": "invalid"},
        {
            "expected_version": True,
            "expected_checksum": "sha256:abc",
            "idempotency_key": "observe-v1",
        },
        {
            "expected_version": 0,
            "expected_checksum": "sha256:abc",
            "idempotency_key": "observe-v1",
        },
        {
            "expected_version": 7,
            "expected_checksum": 123,
            "idempotency_key": "observe-v1",
        },
        {
            "expected_version": 7,
            "expected_checksum": "sha256:abc",
            "idempotency_key": "observe-v1",
            "command": "qm unlock 306",
        },
    ],
)
def test_recovery_observe_route_rejects_invalid_or_extra_fields_before_dispatch(payload):
    from app.api.v1 import operations as api

    with patch.object(api, "observe_operation_recovery") as observe:
        with pytest.raises(HTTPException) as raised:
            asyncio.run(
                api.observe_operation_recovery_route(
                    "operation-1",
                    payload,
                    actor={"user_id": "user-1", "username": "operator", "role": "operator"},
                )
            )

    assert raised.value.status_code == 422
    assert raised.value.detail["code"] == "INVALID_OPERATION_RECOVERY_OBSERVE_REQUEST"
    observe.assert_not_called()


def test_common_operation_detail_marks_expired_guided_instruction_as_historical_without_mutating_it():
    operation_id = "guided-qm-common-detail-expired"
    expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    SqlAlchemyOperationStore().create(
        OperationSpec(
            operation_id=operation_id,
            operation_type="guided_qm_vm_unlock",
            execution_mode="guided_manual",
            target_type="proxmox_vm",
            target_id="vmid:306",
            idempotency_key="guided-common-detail-expired",
            intent_digest="sha256:intent",
            plan_digest="sha256:plan",
            actor=OperationActor(user_id="user-1", username="operator", role="operator"),
            initial_status="awaiting_operator",
            initial_stage="operator_handoff",
            expires_at=expires_at,
            details={
                "instruction_bundle": {"command": "qm unlock 306"},
                "target": {"node_id": "node-a", "vmid": 306},
            },
        )
    )

    detail = get_operation(operation_id)

    assert detail["operation"]["status"] == "awaiting_operator"
    assert detail["instruction_bundle"] == {"command": "qm unlock 306"}
    assert detail["instruction_state"] == {
        "active": False,
        "historical": True,
        "do_not_execute": True,
        "reason": "instruction_ttl_elapsed",
        "expires_at": expires_at.isoformat(),
    }
    assert SqlAlchemyOperationStore().get(operation_id).status == "awaiting_operator"


def test_common_operation_detail_requires_the_exact_live_guided_lock_for_active_instruction():
    from app.operations import facade

    operation_id = "guided-qm-common-detail-exact-lock"
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    recorded_lock = {
        "target_type": "proxmox_vm",
        "target_id": "vmid:306",
        "owner_id": operation_id,
        "lock_id": "compatibility-file-lock",
        "durable": {
            "operation_lock_id": "operation-lock-guided-exact",
            "operation_type": "guided_qm_vm_unlock",
            "scope_type": "proxmox_locator",
            "status": "active",
            "cluster_id": "gjallar-mvp",
            "vmid": 306,
            "owner_id": operation_id,
        },
    }
    SqlAlchemyOperationStore().create(
        OperationSpec(
            operation_id=operation_id,
            operation_type="guided_qm_vm_unlock",
            execution_mode="guided_manual",
            target_type="proxmox_vm",
            target_id="vmid:306",
            idempotency_key="guided-common-detail-exact-lock",
            intent_digest="sha256:intent-exact-lock",
            plan_digest="sha256:plan-exact-lock",
            actor=OperationActor(user_id="user-1", username="operator", role="operator"),
            initial_status="awaiting_operator",
            initial_stage="operator_handoff",
            expires_at=expires_at,
            details={
                "instruction_bundle": {"command": "qm unlock 306"},
                "target": {"node_id": "node-a", "vmid": 306},
                "target_operation_lock": recorded_lock,
            },
        )
    )

    with patch.object(facade, "get_target_operation_lock", return_value=recorded_lock):
        exact = get_operation(operation_id)
    with patch.object(
        facade,
        "get_target_operation_lock",
        return_value={
            **recorded_lock,
            "durable": {
                **recorded_lock["durable"],
                "operation_lock_id": "operation-lock-replacement",
            },
        },
    ):
        replaced = get_operation(operation_id)
    with patch.object(facade, "get_target_operation_lock", return_value=None):
        missing = get_operation(operation_id)

    assert exact["instruction_state"]["active"] is True
    assert exact["instruction_state"]["reason"] == "instruction_active"
    assert replaced["instruction_state"]["active"] is False
    assert replaced["instruction_state"]["do_not_execute"] is True
    assert replaced["instruction_state"]["reason"] == "target_lock_mismatch"
    assert missing["instruction_state"]["active"] is False
    assert missing["instruction_state"]["reason"] == "target_lock_lost"


def test_recovery_observe_maps_canonical_handoff_read_failure_to_stable_503():
    from app.operations import facade

    class Coordinator:
        def observe(self, *_args, **_kwargs):
            return {
                "operation_id": "operation-handoff-failure",
                "outcome": "succeeded",
                "observation_only": True,
                "idempotent_replay": False,
            }

    with patch.object(facade, "build_recovery_coordinator", return_value=Coordinator()):
        with patch.object(facade, "get_operation", side_effect=RuntimeError("database unavailable")):
            with pytest.raises(facade.OperationRecoveryObserveError) as raised:
                facade.observe_operation_recovery(
                    "operation-handoff-failure",
                    actor={"user_id": "user-1", "username": "operator", "role": "operator"},
                    expected_version=3,
                    expected_checksum="sha256:current",
                    idempotency_key="observe-handoff-failure-v3",
                )

    assert raised.value.status_code == 503
    assert raised.value.code == "OPERATION_RECOVERY_PERSISTENCE_UNAVAILABLE"
    assert raised.value.details["observation_committed"] is True
