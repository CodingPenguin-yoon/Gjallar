"""Domain tests for the allowlisted Guided `qm unlock` template."""

from datetime import datetime, timezone

import pytest

from app.operations.guided_qm.domain import (
    GUIDED_QM_UNLOCK_TEMPLATE_ID,
    PlanGuidedQmUnlockCommand,
    build_guided_qm_unlock_bundle,
)
from app.operations.guided_qm.errors import GuidedQmError


ACTOR = {"user_id": "user-1", "username": "operator", "role": "operator"}


def valid_payload() -> dict:
    return {
        "node_id": "node-a",
        "vmid": 306,
        "idempotency_key": "unlock-306-1",
        "qm_unlock_risk_acknowledged": True,
    }


def test_unlock_bundle_is_fixed_argv_and_digest_bound():
    command = PlanGuidedQmUnlockCommand.from_request(valid_payload(), actor=ACTOR)
    bundle = build_guided_qm_unlock_bundle(
        operation_id=command.operation_id,
        node_id=command.node_id,
        vmid=command.vmid,
        expires_at=datetime(2026, 7, 20, 12, 5, tzinfo=timezone.utc),
        observed_lock="backup",
    )

    assert bundle["template_id"] == GUIDED_QM_UNLOCK_TEMPLATE_ID
    assert bundle["command"] == {
        "program": "qm",
        "arguments": ["unlock", "306"],
        "display": "qm unlock 306",
        "run_on": "target_proxmox_node_shell",
    }
    assert bundle["plan_digest"].startswith("sha256:")
    assert command.target_id == "vmid:306"
    assert command.intent["target"] == {"type": "proxmox_vm", "node_id": "node-a", "vmid": 306}


@pytest.mark.parametrize(
    ("patch", "code"),
    [
        ({"command": "qm unlock 999"}, "GUIDED_QM_UNSUPPORTED_FIELD"),
        ({"arguments": ["unlock", "999"]}, "GUIDED_QM_UNSUPPORTED_FIELD"),
        ({"token_secret": "should-not-enter"}, "GUIDED_QM_UNSUPPORTED_FIELD"),
        ({"node_id": "node-a;rm"}, "GUIDED_QM_NODE_ID_INVALID"),
        ({"vmid": "306"}, "GUIDED_QM_VMID_INVALID"),
        ({"idempotency_key": "bad key"}, "GUIDED_QM_IDEMPOTENCY_KEY_INVALID"),
        ({"qm_unlock_risk_acknowledged": False}, "GUIDED_QM_UNLOCK_RISK_ACK_REQUIRED"),
    ],
)
def test_unlock_plan_rejects_arbitrary_or_untyped_input(patch, code):
    payload = {**valid_payload(), **patch}

    with pytest.raises(GuidedQmError) as raised:
        PlanGuidedQmUnlockCommand.from_request(payload, actor=ACTOR)

    assert raised.value.code == code
    assert raised.value.details["backend_command_execution"] is False


def test_bundle_digest_changes_when_expiry_changes():
    base = {
        "operation_id": "guided-qm-unlock-node-a-306-test",
        "node_id": "node-a",
        "vmid": 306,
        "observed_lock": "backup",
    }
    first = build_guided_qm_unlock_bundle(
        **base,
        expires_at=datetime(2026, 7, 20, 12, 5, tzinfo=timezone.utc),
    )
    second = build_guided_qm_unlock_bundle(
        **base,
        expires_at=datetime(2026, 7, 20, 12, 6, tzinfo=timezone.utc),
    )

    assert first["plan_digest"] != second["plan_digest"]
