"""Application tests for shared Operation list queries."""

from datetime import datetime, timezone

import pytest

from app.operations.core.application import InvalidOperationQuery, OperationListQuery, OperationQueryNotFound, OperationQueryService
from app.operations.core.domain import OperationActor, OperationEvent, OperationSnapshot


NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


class RecordingStore:
    def __init__(self) -> None:
        self.filters = None

    def list(self, **filters):
        self.filters = filters
        return [
            OperationSnapshot(
                operation_id="operation-1",
                operation_type="vm_start",
                execution_mode="managed_api",
                status="succeeded",
                target_type="proxmox_vm",
                target_id="vmid:306",
                idempotency_key="idem-1",
                intent_digest="sha256:intent",
                plan_digest="sha256:plan",
                current_stage="verification",
                actor=OperationActor(user_id="user-1", username="operator", role="operator"),
                details={"private_projection": "detail-only"},
                expires_at=None,
                version=4,
                last_event_checksum="sha256:event",
                created_at=NOW,
                updated_at=NOW,
            )
        ]

    def get(self, operation_id):
        return self.list()[0] if operation_id == "operation-1" else None

    def list_events(self, operation_id):
        return [
            OperationEvent(
                event_id="event-1",
                operation_id=operation_id,
                sequence=1,
                event_type="operation_created",
                from_status=None,
                to_status="succeeded",
                stage="verification",
                actor=OperationActor(user_id="user-1", username="operator", role="operator"),
                payload={},
                previous_checksum="",
                checksum="sha256:event",
                created_at=NOW,
            )
        ]


def test_list_normalizes_filters_and_returns_summary_read_model():
    store = RecordingStore()
    result = OperationQueryService(operations=store).list(
        OperationListQuery(
            status=" succeeded ",
            operation_type=" vm_start ",
            target_type=" proxmox_vm ",
            target_id=" vmid:306 ",
            limit=20,
        )
    )

    assert store.filters == {
        "status": "succeeded",
        "operation_type": "vm_start",
        "target_type": "proxmox_vm",
        "target_id": "vmid:306",
        "limit": 20,
    }
    assert result[0]["operation_id"] == "operation-1"
    assert result[0]["actor"]["username"] == "operator"
    assert "details" not in result[0]


def test_list_query_keeps_existing_positional_status_type_limit_contract():
    normalized = OperationListQuery("succeeded", "vm_start", 20).normalized()

    assert normalized.status == "succeeded"
    assert normalized.operation_type == "vm_start"
    assert normalized.limit == 20
    assert normalized.target_type is None
    assert normalized.target_id is None


@pytest.mark.parametrize(
    "query",
    [
        OperationListQuery(status="not-a-status"),
        OperationListQuery(limit=0),
        OperationListQuery(limit=201),
    ],
)
def test_list_rejects_filters_outside_public_contract(query):
    with pytest.raises(InvalidOperationQuery):
        OperationQueryService(operations=RecordingStore()).list(query)


def test_get_returns_common_detail_without_guided_only_metadata():
    result = OperationQueryService(operations=RecordingStore()).get("operation-1")

    assert result["operation"]["operation_id"] == "operation-1"
    assert result["events"][0]["event_type"] == "operation_created"
    assert "instruction_bundle" not in result
    assert "backend_command_execution" not in result


def test_get_raises_generic_not_found_error():
    with pytest.raises(OperationQueryNotFound) as raised:
        OperationQueryService(operations=RecordingStore()).get("missing-operation")

    assert raised.value.operation_id == "missing-operation"
