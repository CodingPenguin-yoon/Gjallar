"""Application tests for Guided `qm unlock` lifecycle and safety gates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.operations.core.domain import verify_event_chain
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.guided_qm.application import GuidedQmUnlockUseCase
from app.operations.guided_qm.domain import (
    AttestGuidedQmCommand,
    PlanGuidedQmUnlockCommand,
    VerifyGuidedQmCommand,
)
from app.operations.guided_qm.errors import GuidedQmError
from app.operations.guided_qm.ports import (
    GuidedQmExecutionPorts,
    GuidedQmObservationFailure,
    GuidedQmTargetLockBusy,
    GuidedQmTargetLockHandle,
)


FIXED_NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
ACTOR = {"user_id": "user-1", "username": "operator", "role": "operator"}


class FakeObservation:
    def __init__(
        self,
        *,
        config_lock: str = "backup",
        tasks: list[dict] | None = None,
        complete_task_audit: bool = True,
    ) -> None:
        self.config_lock = config_lock
        self.tasks = list(tasks or [])
        self.complete_task_audit = complete_task_audit
        self.fail = False
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def has_node_task_audit(self, *, node: str) -> bool:
        self.calls.append(("has_node_task_audit", {"node": node}))
        if self.fail:
            raise GuidedQmObservationFailure("unavailable")
        return self.complete_task_audit

    def get_vm_config(self, *, node: str, vmid: int) -> dict[str, Any]:
        self.calls.append(("get_vm_config", {"node": node, "vmid": vmid}))
        if self.fail:
            raise GuidedQmObservationFailure("unavailable")
        return {"lock": self.config_lock} if self.config_lock else {"name": "vm-306"}

    def list_active_vm_tasks(self, *, node: str, vmid: int) -> list[dict[str, Any]]:
        self.calls.append(("list_active_vm_tasks", {"node": node, "vmid": vmid}))
        if self.fail:
            raise GuidedQmObservationFailure("unavailable")
        return list(self.tasks)


class FakeLocks:
    def __init__(self) -> None:
        self.locks: dict[tuple[str, str], dict[str, Any]] = {}

    def acquire(self, target_type: str, target_id: str, operation_id: str) -> GuidedQmTargetLockHandle:
        key = (target_type, target_id)
        if key in self.locks:
            raise GuidedQmTargetLockBusy(self.locks[key])
        evidence = {
            "target_type": target_type,
            "target_id": target_id,
            "owner_id": operation_id,
            "lock_id": f"lock-{operation_id}",
            "acquired_at": FIXED_NOW.isoformat(),
        }
        self.locks[key] = evidence
        return GuidedQmTargetLockHandle(token=key, evidence=evidence)

    def current(self, target_type: str, target_id: str) -> dict[str, Any] | None:
        current = self.locks.get((target_type, target_id))
        return dict(current) if current else None

    def release(self, handle: GuidedQmTargetLockHandle) -> None:
        self.locks.pop(handle.token, None)

    def release_owned(self, target_type: str, target_id: str, operation_id: str) -> bool:
        key = (target_type, target_id)
        current = self.locks.get(key)
        if not current or current.get("owner_id") != operation_id:
            return False
        self.locks.pop(key)
        return True


def plan_command(*, idempotency_key: str = "unlock-306-1") -> PlanGuidedQmUnlockCommand:
    return PlanGuidedQmUnlockCommand.from_request(
        {
            "node_id": "node-a",
            "vmid": 306,
            "idempotency_key": idempotency_key,
            "qm_unlock_risk_acknowledged": True,
        },
        actor=ACTOR,
    )


def use_case(*, observation=None, locks=None, store=None, clock=None):
    observation = observation or FakeObservation()
    locks = locks or FakeLocks()
    store = store or SqlAlchemyOperationStore(clock=lambda: FIXED_NOW)
    kwargs = {
        "ports": GuidedQmExecutionPorts(operations=store, observation=observation, locks=locks),
    }
    if clock is not None:
        kwargs["clock"] = clock
    else:
        kwargs["clock"] = lambda: FIXED_NOW
    return GuidedQmUnlockUseCase(**kwargs), observation, locks, store


def test_plan_issues_exact_expiring_bundle_and_replay_does_not_reobserve():
    case, observation, locks, store = use_case()
    command = plan_command()

    first = case.plan_unlock(command)
    replay = case.plan_unlock(command)

    operation = first["operation"]
    assert operation["status"] == "awaiting_operator"
    assert operation["execution_mode"] == "guided_manual"
    assert first["instruction_bundle"]["command"]["arguments"] == ["unlock", "306"]
    assert first["instruction_bundle"]["expires_at"] == "2026-07-20T12:05:00+00:00"
    assert first["backend_command_execution"] is False
    assert replay["idempotent_replay"] is True
    assert replay["operation"]["operation_id"] == operation["operation_id"]
    assert [call[0] for call in observation.calls] == [
        "has_node_task_audit",
        "list_active_vm_tasks",
        "get_vm_config",
        "list_active_vm_tasks",
    ]
    assert locks.current("proxmox_vm", "vmid:306")["owner_id"] == operation["operation_id"]
    assert verify_event_chain(store.list_events(operation["operation_id"])) is True


@pytest.mark.parametrize(
    ("observation", "code"),
    [
        (FakeObservation(config_lock=""), "GUIDED_QM_UNLOCK_NOT_LOCKED"),
        (
            FakeObservation(tasks=[{"upid": "UPID:node-a:0001:vzdump", "type": "vzdump", "status": "RUNNING"}]),
            "GUIDED_QM_UNLOCK_ACTIVE_TASKS_BLOCKED",
        ),
        (FakeObservation(complete_task_audit=False), "GUIDED_QM_TASK_AUDIT_INCOMPLETE"),
        (FakeObservation(config_lock="suspended"), "GUIDED_QM_UNLOCK_LOCK_TYPE_UNSUPPORTED"),
        (FakeObservation(config_lock="future-lock"), "GUIDED_QM_UNLOCK_LOCK_TYPE_UNSUPPORTED"),
    ],
)
def test_plan_blocks_without_lock_or_while_tasks_are_active(observation, code):
    case, _, locks, store = use_case(observation=observation)
    command = plan_command(idempotency_key=f"{code}-1")

    with pytest.raises(GuidedQmError) as raised:
        case.plan_unlock(command)

    assert raised.value.code == code
    assert locks.current("proxmox_vm", "vmid:306") is None
    assert store.get(command.operation_id) is None


def test_plan_blocks_on_existing_target_lock_before_proxmox_observation():
    observation = FakeObservation()
    locks = FakeLocks()
    locks.locks[("proxmox_vm", "vmid:306")] = {
        "target_type": "proxmox_vm",
        "target_id": "vmid:306",
        "owner_id": "another-operation",
        "lock_id": "lock-another-operation",
        "acquired_at": FIXED_NOW.isoformat(),
    }
    case, _, _, store = use_case(observation=observation, locks=locks)

    with pytest.raises(GuidedQmError) as raised:
        case.plan_unlock(plan_command())

    assert raised.value.code == "GUIDED_QM_TARGET_LOCK_BUSY"
    assert observation.calls == []
    assert store.get(plan_command().operation_id) is None


def test_attestation_then_api_verification_succeeds_and_releases_target_lock():
    case, observation, locks, store = use_case()
    planned = case.plan_unlock(plan_command())
    operation_id = planned["operation"]["operation_id"]
    digest = planned["operation"]["plan_digest"]

    attested = case.attest(
        AttestGuidedQmCommand.from_request(
            operation_id,
            {"plan_digest": digest, "command_executed": True},
            actor=ACTOR,
        )
    )
    observation.config_lock = ""
    verified = case.verify(
        VerifyGuidedQmCommand.from_request(operation_id, {"plan_digest": digest}, actor=ACTOR)
    )

    assert attested["operation"]["status"] == "awaiting_verification"
    assert verified["operation"]["status"] == "succeeded"
    assert verified["operation"]["details"]["verification"]["verified"] is True
    assert verified["target_lock_released"] is True
    assert locks.current("proxmox_vm", "vmid:306") is None
    events = store.list_events(operation_id)
    assert [event.event_type for event in events] == [
        "operation_created",
        "operator_execution_attested",
        "verification_started",
        "verification_succeeded",
    ]
    assert verify_event_chain(events) is True


def test_attestation_and_verification_reject_a_different_plan_digest():
    case, _, locks, store = use_case()
    planned = case.plan_unlock(plan_command())
    operation_id = planned["operation"]["operation_id"]
    wrong_digest = "sha256:" + "0" * 64

    with pytest.raises(GuidedQmError) as attest_error:
        case.attest(
            AttestGuidedQmCommand.from_request(
                operation_id,
                {"plan_digest": wrong_digest, "command_executed": True},
                actor=ACTOR,
            )
        )
    with pytest.raises(GuidedQmError) as verify_error:
        case.verify(
            VerifyGuidedQmCommand.from_request(
                operation_id,
                {"plan_digest": wrong_digest},
                actor=ACTOR,
            )
        )

    assert attest_error.value.code == "GUIDED_QM_PLAN_DIGEST_MISMATCH"
    assert verify_error.value.code == "GUIDED_QM_PLAN_DIGEST_MISMATCH"
    assert store.get(operation_id).status == "awaiting_operator"
    assert [event.event_type for event in store.list_events(operation_id)] == ["operation_created"]
    assert locks.current("proxmox_vm", "vmid:306") is not None


def test_verification_mismatch_requires_reconciliation_and_can_be_retried():
    case, observation, locks, _ = use_case()
    planned = case.plan_unlock(plan_command())
    operation_id = planned["operation"]["operation_id"]
    digest = planned["operation"]["plan_digest"]
    case.attest(
        AttestGuidedQmCommand.from_request(
            operation_id,
            {"plan_digest": digest, "command_executed": True},
            actor=ACTOR,
        )
    )

    mismatch = case.verify(
        VerifyGuidedQmCommand.from_request(operation_id, {"plan_digest": digest}, actor=ACTOR)
    )
    assert mismatch["operation"]["status"] == "needs_reconciliation"
    assert locks.current("proxmox_vm", "vmid:306") is not None

    observation.config_lock = ""
    recovered = case.verify(
        VerifyGuidedQmCommand.from_request(operation_id, {"plan_digest": digest}, actor=ACTOR)
    )
    assert recovered["operation"]["status"] == "succeeded"
    assert locks.current("proxmox_vm", "vmid:306") is None


def test_verification_unavailable_never_reports_success_and_retains_lock():
    case, observation, locks, store = use_case()
    planned = case.plan_unlock(plan_command())
    operation_id = planned["operation"]["operation_id"]
    digest = planned["operation"]["plan_digest"]
    case.attest(
        AttestGuidedQmCommand.from_request(
            operation_id,
            {"plan_digest": digest, "command_executed": True},
            actor=ACTOR,
        )
    )
    observation.fail = True

    with pytest.raises(GuidedQmError) as raised:
        case.verify(VerifyGuidedQmCommand.from_request(operation_id, {"plan_digest": digest}, actor=ACTOR))

    assert raised.value.code == "GUIDED_QM_VERIFICATION_UNAVAILABLE"
    assert store.get(operation_id).status == "needs_reconciliation"
    assert locks.current("proxmox_vm", "vmid:306") is not None


def test_late_execution_attestation_requires_reconciliation_and_retains_lock():
    now = [FIXED_NOW]
    case, _, locks, store = use_case(clock=lambda: now[0])
    planned = case.plan_unlock(plan_command())
    operation_id = planned["operation"]["operation_id"]
    digest = planned["operation"]["plan_digest"]
    now[0] = FIXED_NOW + timedelta(seconds=301)

    attested = case.attest(
        AttestGuidedQmCommand.from_request(
            operation_id,
            {"plan_digest": digest, "command_executed": True},
            actor=ACTOR,
        )
    )

    assert attested["operation"]["status"] == "needs_reconciliation"
    assert store.get(operation_id).details["operator_attestation"]["late"] is True
    assert locks.current("proxmox_vm", "vmid:306") is not None


def test_unattested_expired_bundle_is_observed_before_lock_release():
    now = [FIXED_NOW]
    case, _, locks, store = use_case(clock=lambda: now[0])
    command = plan_command()
    planned = case.plan_unlock(command)
    now[0] = FIXED_NOW + timedelta(seconds=301)

    replay = case.plan_unlock(command)

    assert replay["operation"]["status"] == "expired"
    assert store.get(planned["operation"]["operation_id"]).status == "expired"
    assert locks.current("proxmox_vm", "vmid:306") is None


def test_expiry_with_possible_external_effect_retains_lock_for_reconciliation():
    now = [FIXED_NOW]
    case, observation, locks, store = use_case(clock=lambda: now[0])
    command = plan_command()
    planned = case.plan_unlock(command)
    observation.config_lock = ""
    now[0] = FIXED_NOW + timedelta(seconds=301)

    replay = case.plan_unlock(command)

    operation_id = planned["operation"]["operation_id"]
    assert replay["operation"]["status"] == "needs_reconciliation"
    assert store.get(operation_id).details["reconciliation_reason"] == (
        "possible_external_effect_at_instruction_expiry"
    )
    assert locks.current("proxmox_vm", "vmid:306") is not None


def test_expiry_reconciliation_still_requires_and_records_operator_attestation():
    now = [FIXED_NOW]
    case, observation, locks, store = use_case(clock=lambda: now[0])
    command = plan_command()
    planned = case.plan_unlock(command)
    operation_id = planned["operation"]["operation_id"]
    digest = planned["operation"]["plan_digest"]
    observation.config_lock = ""
    now[0] = FIXED_NOW + timedelta(seconds=301)
    case.plan_unlock(command)

    with pytest.raises(GuidedQmError) as raised:
        case.verify(
            VerifyGuidedQmCommand.from_request(operation_id, {"plan_digest": digest}, actor=ACTOR)
        )
    assert raised.value.code == "GUIDED_QM_ATTESTATION_REQUIRED"

    attested = case.attest(
        AttestGuidedQmCommand.from_request(
            operation_id,
            {"plan_digest": digest, "command_executed": True},
            actor=ACTOR,
        )
    )
    verified = case.verify(
        VerifyGuidedQmCommand.from_request(operation_id, {"plan_digest": digest}, actor=ACTOR)
    )

    assert attested["operation"]["status"] == "needs_reconciliation"
    assert verified["operation"]["status"] == "succeeded"
    assert locks.current("proxmox_vm", "vmid:306") is None
    assert "operator_execution_attested_for_reconciliation" in [
        event.event_type for event in store.list_events(operation_id)
    ]


def test_attestation_after_operation_was_expired_reopens_reconciliation_without_false_success():
    now = [FIXED_NOW]
    case, _, locks, store = use_case(clock=lambda: now[0])
    command = plan_command()
    planned = case.plan_unlock(command)
    operation_id = planned["operation"]["operation_id"]
    digest = planned["operation"]["plan_digest"]
    now[0] = FIXED_NOW + timedelta(seconds=301)
    case.plan_unlock(command)
    assert store.get(operation_id).status == "expired"
    assert locks.current("proxmox_vm", "vmid:306") is None

    attested = case.attest(
        AttestGuidedQmCommand.from_request(
            operation_id,
            {"plan_digest": digest, "command_executed": True},
            actor=ACTOR,
        )
    )

    assert attested["operation"]["status"] == "needs_reconciliation"
    assert store.get(operation_id).details["reconciliation_reason"] == (
        "execution_attested_after_operation_expired"
    )
    assert attested["operation"]["details"].get("verification") is None


def test_verification_can_resume_from_persisted_verifying_state_after_crash_window():
    case, observation, locks, store = use_case()
    planned = case.plan_unlock(plan_command())
    operation_id = planned["operation"]["operation_id"]
    digest = planned["operation"]["plan_digest"]
    case.attest(
        AttestGuidedQmCommand.from_request(
            operation_id,
            {"plan_digest": digest, "command_executed": True},
            actor=ACTOR,
        )
    )
    store.transition(
        operation_id,
        next_status="verifying",
        event_type="verification_started",
        stage="verification",
        expected_statuses=["awaiting_verification"],
    )
    observation.config_lock = ""

    resumed = case.verify(
        VerifyGuidedQmCommand.from_request(operation_id, {"plan_digest": digest}, actor=ACTOR)
    )

    assert resumed["operation"]["status"] == "succeeded"
    assert resumed["target_lock_released"] is True
    assert locks.current("proxmox_vm", "vmid:306") is None


def test_persistence_failure_releases_lock_and_never_returns_bundle():
    class FailingStore:
        def get(self, operation_id):
            return None

        def create(self, spec, *, event_payload=None):
            raise RuntimeError("database unavailable")

    case, _, locks, _ = use_case(store=FailingStore())

    with pytest.raises(GuidedQmError) as raised:
        case.plan_unlock(plan_command())

    assert raised.value.code == "GUIDED_QM_PERSISTENCE_UNAVAILABLE"
    assert locks.current("proxmox_vm", "vmid:306") is None
