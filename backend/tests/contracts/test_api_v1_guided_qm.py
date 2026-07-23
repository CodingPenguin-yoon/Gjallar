"""API contract tests for allowlisted Guided `qm unlock` operations."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from fastapi import HTTPException


ACTOR = {"user_id": "user-1", "username": "operator", "role": "operator"}


class RecordingObservationClient:
    def __init__(self, *, config_lock: str = "backup", tasks: list[dict] | None = None) -> None:
        self.config_lock = config_lock
        self.tasks = list(tasks or [])
        self.calls: list[tuple[str, dict]] = []

    def has_node_task_audit(self, *, node: str):
        self.calls.append(("has_node_task_audit", {"node": node}))
        return True

    def get_vm_config(self, *, node: str, vmid: int):
        self.calls.append(("get_vm_config", {"node": node, "vmid": vmid}))
        return {"lock": self.config_lock} if self.config_lock else {"name": "vm-306"}

    def list_active_vm_tasks(self, *, node: str, vmid: int):
        self.calls.append(("list_active_vm_tasks", {"node": node, "vmid": vmid}))
        return list(self.tasks)


def plan_payload(*, idempotency_key: str = "api-unlock-306-1") -> dict:
    return {
        "node_id": "node-a",
        "vmid": 306,
        "idempotency_key": idempotency_key,
        "qm_unlock_risk_acknowledged": True,
    }


def test_guided_qm_routes_are_additive_and_do_not_expose_executor():
    from app.main import app

    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/v1/operations/guided-qm/vm-unlock" in paths
    assert "/api/v1/operations/{operation_id}" in paths
    assert "/api/v1/operations/{operation_id}/operator-attestation" in paths
    assert "/api/v1/operations/{operation_id}/verification" in paths
    assert "/api/v1/operations/shell" not in paths
    assert "/api/v1/operations/execute-command" not in paths


def test_guided_qm_unlock_plan_attestation_and_verification_contract():
    from app.api.v1 import guided_qm as api

    client = RecordingObservationClient()
    with patch.object(api, "get_default_proxmox_mutation_client", return_value=client):
        planned = asyncio.run(api.plan_guided_qm_unlock_action(plan_payload(), actor=ACTOR))

    assert planned["ok"] is True
    assert planned["meta"] == {"mode": "guided_manual", "executor": "external_proxmox_node_shell"}
    plan_data = planned["data"]
    operation_id = plan_data["operation"]["operation_id"]
    digest = plan_data["operation"]["plan_digest"]
    assert plan_data["operation"]["status"] == "awaiting_operator"
    assert plan_data["instruction_bundle"]["command"]["display"] == "qm unlock 306"
    assert plan_data["instruction_bundle"]["command"]["arguments"] == ["unlock", "306"]
    assert plan_data["backend_command_execution"] is False
    assert [call[0] for call in client.calls] == [
        "has_node_task_audit",
        "list_active_vm_tasks",
        "get_vm_config",
        "list_active_vm_tasks",
    ]

    attested = asyncio.run(
        api.attest_guided_qm_operation_action(
            operation_id,
            {"plan_digest": digest, "command_executed": True},
            actor=ACTOR,
        )
    )
    assert attested["data"]["operation"]["status"] == "awaiting_verification"

    client.config_lock = ""
    with patch.object(api, "get_default_proxmox_mutation_client", return_value=client):
        verified = asyncio.run(
            api.verify_guided_qm_operation_action(
                operation_id,
                {"plan_digest": digest},
                actor=ACTOR,
            )
        )
    assert verified["data"]["operation"]["status"] == "succeeded"
    assert verified["data"]["operation"]["details"]["verification"]["verified"] is True
    assert verified["data"]["target_lock_released"] is True

    from app.api.v1 import operations as operations_api

    fetched = operations_api.get_operation_route(operation_id)
    assert fetched["data"]["operation"]["operation_id"] == operation_id
    assert [event["event_type"] for event in fetched["data"]["events"]] == [
        "operation_created",
        "operator_execution_attested",
        "verification_started",
        "verification_succeeded",
    ]


@pytest.mark.parametrize("field", ["command", "arguments", "options", "token_secret"])
def test_guided_qm_plan_rejects_arbitrary_command_fields_before_proxmox_access(field):
    from app.api.v1 import guided_qm as api

    with patch.object(api, "get_default_proxmox_mutation_client") as client_factory:
        with pytest.raises(HTTPException) as raised:
            asyncio.run(
                api.plan_guided_qm_unlock_action(
                    {**plan_payload(idempotency_key=f"reject-{field}"), field: "unexpected"},
                    actor=ACTOR,
                )
            )

    assert raised.value.status_code == 422
    assert raised.value.detail["code"] == "GUIDED_QM_UNSUPPORTED_FIELD"
    assert raised.value.detail["backend_command_execution"] is False
    client_factory.assert_not_called()


def test_guided_qm_plan_blocks_active_tasks_and_releases_local_target_lock():
    from app.api.v1 import guided_qm as api
    from app.operations.target_lock import get_target_operation_lock

    client = RecordingObservationClient(
        tasks=[{"upid": "UPID:node-a:0001:vzdump", "type": "vzdump", "status": "RUNNING"}]
    )
    with patch.object(api, "get_default_proxmox_mutation_client", return_value=client):
        with pytest.raises(HTTPException) as raised:
            asyncio.run(
                api.plan_guided_qm_unlock_action(
                    plan_payload(idempotency_key="active-task-block"),
                    actor=ACTOR,
                )
            )

    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "GUIDED_QM_UNLOCK_ACTIVE_TASKS_BLOCKED"
    assert get_target_operation_lock("proxmox_vm", "vmid:306") is None
