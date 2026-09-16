"""Application tests for Guided `qm unlock` lifecycle and safety gates."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.operations.core.application import OperationQueryService
from app.operations.core.domain import OperationActor, operation_digest, verify_event_chain
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
from app.operations.guided_qm.recovery import GuidedQmUnlockRecoveryHandler
from app.operations.recovery.domain import (
    RecoveryItem,
    RecoveryLease,
    RecoveryLeaseBusy,
    RecoveryOperationConflict,
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
            "durable": {
                "operation_lock_id": f"lock-{operation_id}",
                "cluster_id": "gjallar-mvp",
                "operation_type": "guided_qm_vm_unlock",
                "scope_type": "proxmox_locator",
                "status": "active",
                "vmid": 306,
                "owner_id": operation_id,
            },
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



class FakeRecovery:
    def __init__(self, *, operations, locks: FakeLocks, clock=lambda: FIXED_NOW) -> None:
        self.operations = operations
        self.locks = locks
        self.clock = clock
        self.items: dict[str, RecoveryItem] = {}
        self.sequence = 0

    def get(self, operation_id: str) -> RecoveryItem | None:
        return self.items.get(operation_id)

    def prepare_and_claim(
        self,
        spec,
        *,
        lease_owner: str,
        lease_seconds: float,
        expected_operation_version: int | None = None,
        expected_operation_checksum: str | None = None,
    ) -> RecoveryLease:
        self._assert_fence(spec.operation_id, expected_operation_version, expected_operation_checksum)
        if spec.operation_id in self.items:
            raise RecoveryLeaseBusy(spec.operation_id)
        now = self.clock()
        item = RecoveryItem(
            operation_id=spec.operation_id,
            recovery_kind=spec.recovery_kind,
            status="leased",
            available_at=now,
            lease_owner=lease_owner,
            lease_generation=1,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            attempt_count=1,
            last_error_code=None,
            details=dict(spec.details),
            created_at=now,
            updated_at=now,
            completed_at=None,
        )
        self.items[spec.operation_id] = item
        return self._lease(item)

    def claim_operation(
        self,
        operation_id: str,
        *,
        lease_owner: str,
        lease_seconds: float,
        expected_operation_version: int | None = None,
        expected_operation_checksum: str | None = None,
    ) -> RecoveryLease:
        self._assert_fence(operation_id, expected_operation_version, expected_operation_checksum)
        item = self.items[operation_id]
        if item.status in {"leased", "completed"}:
            raise RecoveryLeaseBusy(operation_id)
        now = self.clock()
        claimed = replace(
            item,
            status="leased",
            lease_owner=lease_owner,
            lease_generation=item.lease_generation + 1,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            attempt_count=item.attempt_count + 1,
            updated_at=now,
        )
        self.items[operation_id] = claimed
        return self._lease(claimed)

    def commit_observation(
        self,
        lease: RecoveryLease,
        *,
        event_type: str,
        stage: str,
        payload=None,
        details_patch=None,
        next_status=None,
        expected_statuses=None,
        actor=None,
        recovery_status: str,
        retry_delay_seconds: float = 0,
        error_code=None,
        recovery_details_patch=None,
        release_target_lock: bool = False,
        require_exact_reconciliation_lock: bool = True,
        bind_target_lock: bool = False,
        expected_operation_version: int | None = None,
        expected_operation_checksum: str | None = None,
    ):
        current_item = self.items[lease.operation_id]
        if current_item.status != "leased" or current_item.lease_generation != lease.item.lease_generation:
            raise RecoveryLeaseBusy(lease.operation_id)
        self._assert_fence(lease.operation_id, expected_operation_version, expected_operation_checksum)
        if bind_target_lock:
            proposed = {**current_item.details, **dict(recovery_details_patch or {})}
            current_lock = self.locks.current("proxmox_vm", f"vmid:{proposed.get('vmid')}")
            binding = (
                details_patch.get("target_operation_lock")
                if isinstance(details_patch, dict)
                else None
            )
            assert current_lock is not None
            assert binding == current_lock
            assert current_lock["owner_id"] == lease.operation_id
            assert (
                current_lock["durable"]["operation_lock_id"]
                == proposed["target_lock_id"]
            )
            assert current_lock["durable"]["cluster_id"] == proposed["cluster_id"]
        kwargs = {
            "event_type": event_type,
            "stage": stage,
            "payload": payload,
            "details_patch": details_patch,
            "actor": actor,
            "expected_statuses": expected_statuses,
        }
        if next_status is None:
            operation = self.operations.append_event(lease.operation_id, **kwargs)
        else:
            operation = self.operations.transition(lease.operation_id, next_status=next_status, **kwargs)
        if release_target_lock:
            key = (operation.target_type, operation.target_id)
            current_lock = self.locks.locks.get(key)
            assert current_lock and current_lock.get("owner_id") == operation.operation_id
            self.locks.locks.pop(key)
        now = self.clock()
        item = replace(
            current_item,
            status=recovery_status,
            available_at=now + timedelta(seconds=retry_delay_seconds),
            lease_owner=current_item.lease_owner if recovery_status == "leased" else None,
            lease_expires_at=current_item.lease_expires_at if recovery_status == "leased" else None,
            last_error_code=error_code,
            details={**current_item.details, **dict(recovery_details_patch or {})},
            updated_at=now,
            completed_at=now if recovery_status == "completed" else None,
        )
        self.items[lease.operation_id] = item
        return operation, item

    def _assert_fence(self, operation_id, version, checksum) -> None:
        operation = self.operations.get(operation_id)
        if operation is None:
            raise RecoveryOperationConflict(operation_id)
        if version is not None and operation.version != version:
            raise RecoveryOperationConflict(operation_id)
        if checksum is not None and operation.last_event_checksum != checksum:
            raise RecoveryOperationConflict(operation_id)

    def _lease(self, item: RecoveryItem) -> RecoveryLease:
        self.sequence += 1
        return RecoveryLease(item=item, token=f"fake-lease-{self.sequence}")


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


def use_case(*, observation=None, locks=None, store=None, clock=None, recovery=None):
    observation = observation or FakeObservation()
    locks = locks or FakeLocks()
    store = store or SqlAlchemyOperationStore(clock=lambda: FIXED_NOW)
    effective_clock = clock or (lambda: FIXED_NOW)
    recovery = recovery or FakeRecovery(operations=store, locks=locks, clock=effective_clock)
    kwargs = {
        "ports": GuidedQmExecutionPorts(
            operations=store,
            observation=observation,
            locks=locks,
            recovery=recovery,
        ),
    }
    if clock is not None:
        kwargs["clock"] = clock
    else:
        kwargs["clock"] = effective_clock
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
    assert first["instruction_state"]["active"] is True
    assert first["instruction_state"]["do_not_execute"] is False
    assert replay["idempotent_replay"] is True
    assert replay["operation"]["operation_id"] == operation["operation_id"]
    assert [call[0] for call in observation.calls] == [
        "has_node_task_audit",
        "list_active_vm_tasks",
        "get_vm_config",
        "list_active_vm_tasks",
        "has_node_task_audit",
        "list_active_vm_tasks",
        "get_vm_config",
        "list_active_vm_tasks",
    ]
    assert locks.current("proxmox_vm", "vmid:306")["owner_id"] == operation["operation_id"]
    recovery_item = case._ports.recovery.get(operation["operation_id"])
    assert recovery_item.recovery_kind == "guided_qm_unlock_observation"
    assert recovery_item.status == "retry_wait"
    assert recovery_item.details["operation_type"] == "guided_qm_vm_unlock"
    assert recovery_item.details["execution_mode"] == "guided_manual"
    assert recovery_item.details["target_id"] == "vmid:306"
    assert recovery_item.details["target_lock_id"] == f"lock-{operation['operation_id']}"
    assert recovery_item.details["original_config_lock"] == "backup"
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


def test_same_operation_lock_race_does_not_block_the_durable_plan_owner():
    class SameOwnerRaceLocks(FakeLocks):
        def __init__(self) -> None:
            super().__init__()
            self.race_once = True

        def acquire(self, target_type: str, target_id: str, operation_id: str):
            if self.race_once:
                self.race_once = False
                evidence = {
                    "target_type": target_type,
                    "target_id": target_id,
                    "owner_id": operation_id,
                    "lock_id": f"lock-{operation_id}",
                    "acquired_at": FIXED_NOW.isoformat(),
                    "durable": {
                        "operation_lock_id": f"lock-{operation_id}",
                        "cluster_id": "gjallar-mvp",
                        "operation_type": "guided_qm_vm_unlock",
                        "scope_type": "proxmox_locator",
                        "status": "active",
                        "vmid": 306,
                        "owner_id": operation_id,
                    },
                }
                self.locks[(target_type, target_id)] = evidence
                raise GuidedQmTargetLockBusy(evidence)
            return super().acquire(target_type, target_id, operation_id)

    locks = SameOwnerRaceLocks()
    case, _, _, store = use_case(locks=locks)
    command = plan_command(idempotency_key="same-operation-lock-race")

    result = case.plan_unlock(command)

    assert result["operation"]["status"] == "awaiting_operator"
    assert store.get(command.operation_id).status == "awaiting_operator"


def test_instruction_is_not_published_when_target_lock_changes_during_final_observation():
    locks = FakeLocks()

    class ReplacingLockObservation(FakeObservation):
        def __init__(self) -> None:
            super().__init__()
            self.config_reads = 0

        def get_vm_config(self, *, node: str, vmid: int):
                result = super().get_vm_config(node=node, vmid=vmid)
                self.config_reads += 1
                if self.config_reads == 2:
                    locks.locks[("proxmox_vm", "vmid:306")]["lock_id"] = "replacement-during-observation"
                    locks.locks[("proxmox_vm", "vmid:306")]["durable"][
                        "operation_lock_id"
                    ] = "replacement-during-observation"
                return result

    observation = ReplacingLockObservation()
    case, _, _, store = use_case(observation=observation, locks=locks)
    command = plan_command(idempotency_key="lock-changed-before-instruction")

    with pytest.raises(GuidedQmError) as raised:
        case.plan_unlock(command)

    operation = store.get(command.operation_id)
    assert raised.value.code == "GUIDED_QM_TARGET_LOCK_LOST"
    assert operation.status == "blocked"
    assert operation.details.get("instruction_bundle") is None
    assert case._ports.recovery.get(command.operation_id).status == "paused"
    assert locks.current("proxmox_vm", "vmid:306")["lock_id"] == "replacement-during-observation"


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
    assert verified["instruction_state"]["do_not_execute"] is True
    assert verified["instruction_state"]["historical"] is True
    assert locks.current("proxmox_vm", "vmid:306") is None
    events = store.list_events(operation_id)
    assert [event.event_type for event in events] == [
        "operation_created",
        "guided_plan_target_lock_bound",
        "guided_instruction_issued",
        "operator_execution_attested",
        "verification_started",
        "verification_succeeded",
    ]
    assert verify_event_chain(events) is True


def test_attestation_rejects_same_owner_replacement_lock_before_authorizing_verification():
    case, _, locks, store = use_case()
    planned = case.plan_unlock(plan_command(idempotency_key="attest-replaced-lock"))
    operation_id = planned["operation"]["operation_id"]
    digest = planned["operation"]["plan_digest"]
    current = locks.locks[("proxmox_vm", "vmid:306")]
    current["lock_id"] = "replacement-lock-id"
    current["durable"]["operation_lock_id"] = "replacement-lock-id"

    with pytest.raises(GuidedQmError) as raised:
        case.attest(
            AttestGuidedQmCommand.from_request(
                operation_id,
                {"plan_digest": digest, "command_executed": True},
                actor=ACTOR,
            )
        )

    operation = store.get(operation_id)
    assert raised.value.code == "GUIDED_QM_TARGET_LOCK_LOST"
    assert operation.status == "needs_reconciliation"
    assert operation.details.get("operator_attestation") is None
    assert store.list_events(operation_id)[-1].event_type == "target_lock_lost"


def test_guided_verification_persists_only_bounded_task_and_lock_evidence():
    case, observation, _, store = use_case()
    planned = case.plan_unlock(plan_command(idempotency_key="bounded-guided-evidence"))
    operation_id = planned["operation"]["operation_id"]
    digest = planned["operation"]["plan_digest"]
    case.attest(
        AttestGuidedQmCommand.from_request(
            operation_id,
            {"plan_digest": digest, "command_executed": True},
            actor=ACTOR,
        )
    )
    opaque = "opaque-token-value"
    observation.config_lock = opaque
    observation.tasks = [
        {
            "upid": opaque,
            "node": "node-a",
            "type": "vzdump",
            "status": "RUNNING",
            "pid": 123,
            "raw": opaque,
        }
    ]

    result = case.verify(
        VerifyGuidedQmCommand.from_request(
            operation_id,
            {"plan_digest": digest},
            actor=ACTOR,
        )
    )

    assert result["operation"]["status"] == "needs_reconciliation"
    verification = store.get(operation_id).details["verification"]
    observed = verification["observed_after"]
    assert observed["config_lock"] == "unsupported_present"
    assert observed["active_tasks"] == [
        {
            "node": "node-a",
            "type": "vzdump",
            "status": "running",
            "pid": 123,
            "task_ref_digest": operation_digest(
                {
                    "task_ref": opaque,
                    "evidence": {
                        "node": "node-a",
                        "type": "vzdump",
                        "status": "running",
                        "pid": 123,
                    },
                }
            ),
        }
    ]
    serialized = repr(
        {
            "operation": store.get(operation_id),
            "events": store.list_events(operation_id),
        }
    )
    assert opaque not in serialized


def test_inactive_exact_lock_turns_attestation_into_late_manual_evidence():
    case, observation, locks, store = use_case()
    planned = case.plan_unlock(plan_command(idempotency_key="inactive-lock-attestation"))
    operation_id = planned["operation"]["operation_id"]
    digest = planned["operation"]["plan_digest"]
    locks.locks[("proxmox_vm", "vmid:306")]["durable"]["status"] = "reconciliation_required"
    observation_calls = len(observation.calls)

    attested = case.attest(
        AttestGuidedQmCommand.from_request(
            operation_id,
            {"plan_digest": digest, "command_executed": True},
            actor=ACTOR,
        )
    )

    operation = store.get(operation_id)
    assert attested["operation"]["status"] == "needs_reconciliation"
    assert operation.details["operator_attestation"]["late"] is True
    assert operation.details["reconciliation_reason"] == (
        "execution_attested_after_target_lock_became_inactive"
    )
    assert len(observation.calls) == observation_calls

    with pytest.raises(GuidedQmError) as raised:
        case.verify(
            VerifyGuidedQmCommand.from_request(
                operation_id,
                {"plan_digest": digest},
                actor=ACTOR,
            )
        )

    assert raised.value.code == "GUIDED_QM_TARGET_LOCK_LOST"
    assert len(observation.calls) == observation_calls


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
    assert [event.event_type for event in store.list_events(operation_id)] == [
        "operation_created",
        "guided_plan_target_lock_bound",
        "guided_instruction_issued",
    ]
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


def test_background_recovery_pauses_late_attestation_without_proxmox_observation():
    now = [FIXED_NOW]
    case, observation, locks, store = use_case(clock=lambda: now[0])
    planned = case.plan_unlock(
        plan_command(idempotency_key="late-attestation-background-recovery")
    )
    operation_id = planned["operation"]["operation_id"]
    digest = planned["operation"]["plan_digest"]
    now[0] = FIXED_NOW + timedelta(seconds=301)
    case.attest(
        AttestGuidedQmCommand.from_request(
            operation_id,
            {"plan_digest": digest, "command_executed": True},
            actor=ACTOR,
        )
    )
    calls_before_recovery = list(observation.calls)
    operation = store.get(operation_id)
    recovery = case._ports.recovery
    lease = recovery.claim_operation(
        operation_id,
        lease_owner="restart-worker-late-attestation",
        lease_seconds=60,
        expected_operation_version=operation.version,
        expected_operation_checksum=operation.last_event_checksum,
    )

    result = GuidedQmUnlockRecoveryHandler(
        operations=store,
        recovery=recovery,
        observation_factory=lambda: observation,
        locks=locks,
        clock=lambda: now[0],
    ).handle(lease)

    assert result.outcome == "guided_qm_needs_reconciliation"
    assert observation.calls == calls_before_recovery
    assert recovery.get(operation_id).status == "paused"
    assert recovery.get(operation_id).last_error_code == (
        "GUIDED_QM_LATE_ATTESTATION_MANUAL_VERIFICATION_REQUIRED"
    )
    assert store.get(operation_id).status == "needs_reconciliation"
    assert locks.current("proxmox_vm", "vmid:306")["owner_id"] == operation_id


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


def test_expiry_with_active_tasks_retains_lock_for_reconciliation():
    now = [FIXED_NOW]
    case, observation, locks, store = use_case(clock=lambda: now[0])
    command = plan_command(idempotency_key="expiry-active-tasks")
    planned = case.plan_unlock(command)
    observation.tasks = [{"upid": "UPID:node-a:task", "status": "RUNNING"}]
    now[0] = FIXED_NOW + timedelta(seconds=301)

    replay = case.plan_unlock(command)

    operation_id = planned["operation"]["operation_id"]
    assert replay["operation"]["status"] == "needs_reconciliation"
    assert store.get(operation_id).details["reconciliation_reason"] == "active_tasks_at_instruction_expiry"
    assert locks.current("proxmox_vm", "vmid:306")["owner_id"] == operation_id


def test_expiry_observation_retries_before_unknown_state_requires_reconciliation():
    now = [FIXED_NOW]
    case, observation, locks, store = use_case(clock=lambda: now[0])
    command = plan_command(idempotency_key="expiry-observation-unavailable")
    planned = case.plan_unlock(command)
    observation.fail = True
    now[0] = FIXED_NOW + timedelta(seconds=301)

    first_retry = case.plan_unlock(command)

    operation_id = planned["operation"]["operation_id"]
    assert first_retry["operation"]["status"] == "awaiting_operator"
    assert first_retry["instruction_state"]["do_not_execute"] is True
    assert case._ports.recovery.get(operation_id).status == "retry_wait"
    assert locks.current("proxmox_vm", "vmid:306")["owner_id"] == operation_id

    case.plan_unlock(command)
    case.plan_unlock(command)
    exhausted = case.plan_unlock(command)

    assert exhausted["operation"]["status"] == "needs_reconciliation"
    assert store.get(operation_id).details["reconciliation_reason"] == "state_unknown_at_instruction_expiry"
    assert case._ports.recovery.get(operation_id).status == "paused"
    assert locks.current("proxmox_vm", "vmid:306")["owner_id"] == operation_id


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


def test_recovery_handler_resumes_persisted_verifying_with_get_only_ports():
    case, observation, locks, store = use_case()
    planned = case.plan_unlock(plan_command(idempotency_key="restart-handler-verification"))
    operation_id = planned["operation"]["operation_id"]
    digest = planned["operation"]["plan_digest"]
    case.attest(
        AttestGuidedQmCommand.from_request(
            operation_id,
            {"plan_digest": digest, "command_executed": True},
            actor=ACTOR,
        )
    )
    operation = store.transition(
        operation_id,
        next_status="verifying",
        event_type="verification_started",
        stage="verification",
        expected_statuses=["awaiting_verification"],
    )
    recovery = case._ports.recovery
    lease = recovery.claim_operation(
        operation_id,
        lease_owner="restart-worker",
        lease_seconds=60,
        expected_operation_version=operation.version,
        expected_operation_checksum=operation.last_event_checksum,
    )
    observation.config_lock = ""

    result = GuidedQmUnlockRecoveryHandler(
        operations=store,
        recovery=recovery,
        observation_factory=lambda: observation,
        locks=locks,
        clock=lambda: FIXED_NOW,
    ).handle(lease)

    assert result.outcome == "guided_qm_succeeded"
    assert store.get(operation_id).status == "succeeded"
    assert locks.current("proxmox_vm", "vmid:306") is None


def test_recovery_handler_retries_transient_expiry_observation_then_expires_safely():
    now = [FIXED_NOW]
    case, observation, locks, store = use_case(clock=lambda: now[0])
    planned = case.plan_unlock(plan_command(idempotency_key="restart-handler-expiry-retry"))
    operation_id = planned["operation"]["operation_id"]
    recovery = case._ports.recovery
    now[0] = FIXED_NOW + timedelta(seconds=301)
    operation = store.get(operation_id)
    lease = recovery.claim_operation(
        operation_id,
        lease_owner="restart-worker-1",
        lease_seconds=60,
        expected_operation_version=operation.version,
        expected_operation_checksum=operation.last_event_checksum,
    )
    observation.fail = True
    handler = GuidedQmUnlockRecoveryHandler(
        operations=store,
        recovery=recovery,
        observation_factory=lambda: observation,
        locks=locks,
        clock=lambda: now[0],
    )

    retry = handler.handle(lease)

    assert retry.outcome == "guided_qm_awaiting_operator"
    assert recovery.get(operation_id).status == "retry_wait"
    assert locks.current("proxmox_vm", "vmid:306")["owner_id"] == operation_id

    operation = store.get(operation_id)
    retry_lease = recovery.claim_operation(
        operation_id,
        lease_owner="restart-worker-2",
        lease_seconds=60,
        expected_operation_version=operation.version,
        expected_operation_checksum=operation.last_event_checksum,
    )
    observation.fail = False
    recovered = handler.handle(retry_lease)

    assert recovered.outcome == "guided_qm_expired"
    assert store.get(operation_id).status == "expired"
    assert recovery.get(operation_id).status == "completed"
    assert locks.current("proxmox_vm", "vmid:306") is None


def test_recovery_handler_durably_pauses_corrupted_binding_as_ineligible():
    case, observation, locks, store = use_case()
    planned = case.plan_unlock(plan_command(idempotency_key="restart-handler-binding-mismatch"))
    operation_id = planned["operation"]["operation_id"]
    recovery = case._ports.recovery
    item = recovery.items[operation_id]
    recovery.items[operation_id] = replace(
        item,
        details={**item.details, "target_id": "vmid:999"},
    )
    operation = store.get(operation_id)
    lease = recovery.claim_operation(
        operation_id,
        lease_owner="restart-worker-binding",
        lease_seconds=60,
        expected_operation_version=operation.version,
        expected_operation_checksum=operation.last_event_checksum,
    )

    result = GuidedQmUnlockRecoveryHandler(
        operations=store,
        recovery=recovery,
        observation_factory=lambda: observation,
        locks=locks,
        clock=lambda: FIXED_NOW,
    ).handle(lease)

    assert result.outcome == "paused_binding_mismatch"
    assert recovery.get(operation_id).status == "paused"
    assert recovery.get(operation_id).last_error_code == "GUIDED_QM_RECOVERY_BINDING_MISMATCH"
    assert store.list_events(operation_id)[-1].event_type == "guided_qm_recovery_binding_mismatch"


def test_recovery_handler_pauses_corrupted_lease_cluster_before_get_or_cleanup():
    case, observation, locks, store = use_case()
    planned = case.plan_unlock(plan_command(idempotency_key="restart-handler-cluster-binding-mismatch"))
    operation_id = planned["operation"]["operation_id"]
    digest = planned["operation"]["plan_digest"]
    case.attest(
        AttestGuidedQmCommand.from_request(
            operation_id,
            {"plan_digest": digest, "command_executed": True},
            actor=ACTOR,
        )
    )
    operation = store.transition(
        operation_id,
        next_status="verifying",
        event_type="verification_started",
        stage="verification",
        expected_statuses=["awaiting_verification"],
    )
    recovery = case._ports.recovery
    item = recovery.items[operation_id]
    recovery.items[operation_id] = replace(
        item,
        details={**item.details, "cluster_id": "corrupted-cluster"},
    )
    lease = recovery.claim_operation(
        operation_id,
        lease_owner="restart-worker-cluster-binding",
        lease_seconds=60,
        expected_operation_version=operation.version,
        expected_operation_checksum=operation.last_event_checksum,
    )
    observation_calls = list(observation.calls)

    result = GuidedQmUnlockRecoveryHandler(
        operations=store,
        recovery=recovery,
        observation_factory=lambda: observation,
        locks=locks,
        clock=lambda: FIXED_NOW,
    ).handle(lease)

    assert result.outcome == "paused_binding_mismatch"
    assert recovery.get(operation_id).status == "paused"
    assert recovery.get(operation_id).last_error_code == "GUIDED_QM_RECOVERY_BINDING_MISMATCH"
    assert observation.calls == observation_calls
    assert locks.current("proxmox_vm", "vmid:306")["owner_id"] == operation_id


def test_recovery_handler_pauses_current_lock_cluster_mismatch_before_get_or_cleanup():
    case, observation, locks, store = use_case()
    planned = case.plan_unlock(plan_command(idempotency_key="restart-handler-current-cluster-mismatch"))
    operation_id = planned["operation"]["operation_id"]
    digest = planned["operation"]["plan_digest"]
    case.attest(
        AttestGuidedQmCommand.from_request(
            operation_id,
            {"plan_digest": digest, "command_executed": True},
            actor=ACTOR,
        )
    )
    operation = store.transition(
        operation_id,
        next_status="verifying",
        event_type="verification_started",
        stage="verification",
        expected_statuses=["awaiting_verification"],
    )
    recovery = case._ports.recovery
    lease = recovery.claim_operation(
        operation_id,
        lease_owner="restart-worker-current-cluster",
        lease_seconds=60,
        expected_operation_version=operation.version,
        expected_operation_checksum=operation.last_event_checksum,
    )
    locks.locks[("proxmox_vm", "vmid:306")]["durable"]["cluster_id"] = "replacement-cluster"
    observation_calls = list(observation.calls)

    result = GuidedQmUnlockRecoveryHandler(
        operations=store,
        recovery=recovery,
        observation_factory=lambda: observation,
        locks=locks,
        clock=lambda: FIXED_NOW,
    ).handle(lease)

    assert result.outcome == "paused_binding_mismatch"
    assert recovery.get(operation_id).status == "paused"
    assert recovery.get(operation_id).last_error_code == "GUIDED_QM_RECOVERY_BINDING_MISMATCH"
    assert observation.calls == observation_calls
    assert locks.current("proxmox_vm", "vmid:306")["owner_id"] == operation_id


def test_planned_recovery_cluster_mismatch_pauses_before_instruction_finalization_get():
    class SimulatedProcessCrash(BaseException):
        pass

    class CrashBeforeInstructionHandoffRecovery(FakeRecovery):
        def commit_observation(self, lease, **kwargs):
            if kwargs.get("event_type") == "guided_instruction_issued":
                raise SimulatedProcessCrash()
            return super().commit_observation(lease, **kwargs)

    store = SqlAlchemyOperationStore(clock=lambda: FIXED_NOW)
    locks = FakeLocks()
    recovery = CrashBeforeInstructionHandoffRecovery(operations=store, locks=locks)
    case, observation, _, _ = use_case(store=store, locks=locks, recovery=recovery)
    command = plan_command(idempotency_key="planned-recovery-cluster-mismatch")

    with pytest.raises(SimulatedProcessCrash):
        case.plan_unlock(command)

    operation = store.get(command.operation_id)
    item = recovery.items[command.operation_id]
    recovery.items[command.operation_id] = replace(
        item,
        status="retry_wait",
        lease_owner=None,
        lease_expires_at=None,
    )
    lease = recovery.claim_operation(
        command.operation_id,
        lease_owner="restart-worker-planned-cluster",
        lease_seconds=60,
        expected_operation_version=operation.version,
        expected_operation_checksum=operation.last_event_checksum,
    )
    locks.locks[("proxmox_vm", "vmid:306")]["durable"]["cluster_id"] = "replacement-cluster"
    observation_calls = list(observation.calls)

    result = GuidedQmUnlockRecoveryHandler(
        operations=store,
        recovery=recovery,
        observation_factory=lambda: observation,
        locks=locks,
        clock=lambda: FIXED_NOW,
    ).handle(lease)

    assert result.outcome == "paused_binding_mismatch"
    assert recovery.get(command.operation_id).status == "paused"
    assert recovery.get(command.operation_id).last_error_code == "GUIDED_QM_RECOVERY_BINDING_MISMATCH"
    assert observation.calls == observation_calls
    assert locks.current("proxmox_vm", "vmid:306")["owner_id"] == command.operation_id


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


def test_recovery_prepare_failure_happens_before_target_lock_acquire():
    class FailingPrepareRecovery(FakeRecovery):
        def prepare_and_claim(self, spec, **kwargs):
            raise RuntimeError("recovery unavailable")

    store = SqlAlchemyOperationStore(clock=lambda: FIXED_NOW)
    locks = FakeLocks()
    recovery = FailingPrepareRecovery(operations=store, locks=locks)
    case, _, _, _ = use_case(store=store, locks=locks, recovery=recovery)
    command = plan_command(idempotency_key="recovery-before-target-lock")

    with pytest.raises(GuidedQmError) as raised:
        case.plan_unlock(command)

    assert raised.value.code == "GUIDED_QM_RECOVERY_UNAVAILABLE"
    assert store.get(command.operation_id).status == "planned"
    assert recovery.get(command.operation_id) is None
    assert locks.current("proxmox_vm", "vmid:306") is None


def test_operator_observe_safely_bootstraps_planned_no_item_without_lock_or_get():
    from app.operations.recovery.application import (
        OperationRecoveryCoordinator,
        OperationRecoveryRunner,
    )

    class TogglePrepareRecovery(FakeRecovery):
        fail_prepare = True

        def prepare_and_claim(self, spec, **kwargs):
            if self.fail_prepare:
                raise RuntimeError("recovery unavailable")
            return super().prepare_and_claim(spec, **kwargs)

    store = SqlAlchemyOperationStore(clock=lambda: FIXED_NOW)
    locks = FakeLocks()
    recovery = TogglePrepareRecovery(operations=store, locks=locks)
    case, observation, _, _ = use_case(store=store, locks=locks, recovery=recovery)
    command = plan_command(idempotency_key="operator-bootstrap-planned-no-item")

    with pytest.raises(GuidedQmError):
        case.plan_unlock(command)

    operation = store.get(command.operation_id)
    calls_before_observe = list(observation.calls)
    recovery.fail_prepare = False
    handler = GuidedQmUnlockRecoveryHandler(
        operations=store,
        recovery=recovery,
        observation_factory=lambda: observation,
        locks=locks,
        clock=lambda: FIXED_NOW,
    )
    coordinator = OperationRecoveryCoordinator(
        recovery=recovery,
        operations=store,
        runner=OperationRecoveryRunner(
            recovery=recovery,
            handlers={"guided_qm_unlock_observation": handler},
            worker_id="automatic-guided-recovery",
        ),
        lock_reader=lambda target_type, target_id: locks.current(target_type, target_id),
        worker_id="operator-guided-recovery",
        clock=lambda: FIXED_NOW,
    )

    result = coordinator.observe(
        command.operation_id,
        actor=OperationActor(user_id="user-1", username="operator", role="operator"),
        expected_version=operation.version,
        expected_checksum=operation.last_event_checksum,
        idempotency_key="observe-guided-planned-no-item",
    )

    assert result["outcome"] == "guided_qm_blocked"
    assert store.get(command.operation_id).status == "blocked"
    assert recovery.get(command.operation_id).status == "completed"
    assert recovery.get(command.operation_id).details["terminal_outcome"] == "blocked"
    assert locks.current("proxmox_vm", "vmid:306") is None
    assert observation.calls == calls_before_observe


def test_restart_recovers_crash_after_lock_acquire_from_prepared_item():
    class SimulatedProcessCrash(BaseException):
        pass

    class CrashAfterAcquireLocks(FakeLocks):
        def __init__(self):
            super().__init__()
            self.crash_once = True

        def acquire(self, target_type: str, target_id: str, operation_id: str):
            handle = super().acquire(target_type, target_id, operation_id)
            if self.crash_once:
                self.crash_once = False
                raise SimulatedProcessCrash()
            return handle

    store = SqlAlchemyOperationStore(clock=lambda: FIXED_NOW)
    locks = CrashAfterAcquireLocks()
    recovery = FakeRecovery(operations=store, locks=locks)
    case, observation, _, _ = use_case(store=store, locks=locks, recovery=recovery)
    command = plan_command(idempotency_key="crash-after-target-lock-acquire")

    with pytest.raises(SimulatedProcessCrash):
        case.plan_unlock(command)

    operation = store.get(command.operation_id)
    item = recovery.get(command.operation_id)
    assert operation.status == "planned"
    assert operation.details.get("target_operation_lock") is None
    assert item is not None
    assert item.details["target_lock_id"] == ""
    assert item.details["cluster_id"] == ""
    assert locks.current("proxmox_vm", "vmid:306")["owner_id"] == command.operation_id

    recovery.items[command.operation_id] = replace(
        item,
        status="retry_wait",
        lease_owner=None,
        lease_expires_at=None,
    )
    lease = recovery.claim_operation(
        command.operation_id,
        lease_owner="restart-worker-after-lock",
        lease_seconds=60,
        expected_operation_version=operation.version,
        expected_operation_checksum=operation.last_event_checksum,
    )
    calls_before_recovery = list(observation.calls)

    result = GuidedQmUnlockRecoveryHandler(
        operations=store,
        recovery=recovery,
        observation_factory=lambda: observation,
        locks=locks,
        clock=lambda: FIXED_NOW,
    ).handle(lease)

    recovered = store.get(command.operation_id)
    recovered_item = recovery.get(command.operation_id)
    assert result.outcome == "guided_qm_awaiting_operator"
    assert recovered.status == "awaiting_operator"
    assert recovered.details["target_operation_lock"]["owner_id"] == command.operation_id
    assert recovered_item.details["target_lock_id"] == f"lock-{command.operation_id}"
    assert recovered_item.details["cluster_id"] == "gjallar-mvp"
    assert recovered_item.status == "retry_wait"
    assert len(observation.calls) > len(calls_before_recovery)
    assert verify_event_chain(store.list_events(command.operation_id)) is True


def test_lock_acquire_race_closes_unissued_plan_without_touching_foreign_lock():
    class ForeignLockAcquireRace(FakeLocks):
        def acquire(self, target_type: str, target_id: str, operation_id: str):
            foreign = {
                "target_type": target_type,
                "target_id": target_id,
                "owner_id": "foreign-operation",
                "lock_id": "foreign-lock",
                "durable": {
                    "operation_lock_id": "foreign-lock",
                    "cluster_id": "gjallar-mvp",
                    "operation_type": "vm_start",
                    "scope_type": "proxmox_locator",
                    "status": "active",
                    "vmid": 306,
                    "owner_id": "foreign-operation",
                },
            }
            self.locks[(target_type, target_id)] = foreign
            raise GuidedQmTargetLockBusy(foreign)

    store = SqlAlchemyOperationStore(clock=lambda: FIXED_NOW)
    locks = ForeignLockAcquireRace()
    recovery = FakeRecovery(operations=store, locks=locks)
    case, _, _, _ = use_case(store=store, locks=locks, recovery=recovery)
    command = plan_command(idempotency_key="foreign-lock-acquire-race")

    with pytest.raises(GuidedQmError) as raised:
        case.plan_unlock(command)

    operation = store.get(command.operation_id)
    item = recovery.get(command.operation_id)
    current_lock = locks.current("proxmox_vm", "vmid:306")
    assert raised.value.code == "GUIDED_QM_TARGET_LOCK_BUSY"
    assert operation.status == "blocked"
    assert operation.details["plan_finalization"]["reason"] == "target_lock_busy"
    assert item.status == "completed"
    assert item.details["phase"] == "blocked"
    assert current_lock["owner_id"] == "foreign-operation"
    assert current_lock["lock_id"] == "foreign-lock"
    assert operation.details.get("instruction_bundle") is None


def test_process_crash_before_operation_create_never_leaves_an_ownerless_target_lock():
    class SimulatedProcessCrash(BaseException):
        pass

    class CrashBeforeCreateStore:
        def get(self, operation_id):
            return None

        def create(self, spec, *, event_payload=None):
            raise SimulatedProcessCrash()

    store = CrashBeforeCreateStore()
    case, _, locks, _ = use_case(store=store)
    command = plan_command(idempotency_key="crash-before-operation-create")

    with pytest.raises(SimulatedProcessCrash):
        case.plan_unlock(command)

    current_lock = locks.current("proxmox_vm", "vmid:306")
    persisted_owner = store.get(current_lock["owner_id"]) if current_lock else None
    assert current_lock is None or persisted_owner is not None


def test_stale_plan_finalizer_cannot_publish_instruction_for_a_replaced_target_lock():
    class SimulatedProcessCrash(BaseException):
        pass

    class CrashBeforeInstructionHandoffRecovery(FakeRecovery):
        def commit_observation(self, lease, **kwargs):
            if kwargs.get("event_type") == "guided_instruction_issued":
                raise SimulatedProcessCrash()
            return super().commit_observation(lease, **kwargs)

    store = SqlAlchemyOperationStore(clock=lambda: FIXED_NOW)
    locks = FakeLocks()
    recovery = CrashBeforeInstructionHandoffRecovery(operations=store, locks=locks)
    case, _, _, _ = use_case(store=store, locks=locks, recovery=recovery)
    command = plan_command(idempotency_key="stale-finalizer-replaced-lock")

    with pytest.raises(SimulatedProcessCrash):
        case.plan_unlock(command)

    provisional = case.get(command.operation_id)
    assert provisional["operation"]["status"] == "planned"
    assert provisional["instruction_bundle"] is None
    assert provisional["instruction_state"]["do_not_execute"] is True
    assert "instruction_bundle" not in provisional["events"][0]["payload"]
    item = recovery.items[command.operation_id]
    recovery.items[command.operation_id] = replace(
        item,
        status="retry_wait",
        lease_owner=None,
        lease_expires_at=None,
    )
    locks.locks[("proxmox_vm", "vmid:306")]["lock_id"] = "replacement-lock-id"
    locks.locks[("proxmox_vm", "vmid:306")]["durable"][
        "operation_lock_id"
    ] = "replacement-lock-id"

    with pytest.raises(GuidedQmError) as raised:
        case.plan_unlock(command)

    assert raised.value.code == "GUIDED_QM_RECOVERY_BINDING_MISMATCH"
    assert store.get(command.operation_id).status == "planned"
    assert [event.event_type for event in store.list_events(command.operation_id)] == [
        "operation_created",
        "guided_plan_target_lock_bound",
    ]


def test_common_operation_get_does_not_advance_guided_instruction_expiry():
    now = [FIXED_NOW]
    case, observation, locks, store = use_case(clock=lambda: now[0])
    planned = case.plan_unlock(plan_command(idempotency_key="read-only-common-get"))
    operation_id = planned["operation"]["operation_id"]
    observation_call_count = len(observation.calls)
    now[0] = FIXED_NOW + timedelta(seconds=301)

    fetched = OperationQueryService(operations=store).get(operation_id)
    guided_fetched = case.get(operation_id)

    assert fetched["operation"]["status"] == "awaiting_operator"
    assert guided_fetched["operation"]["status"] == "awaiting_operator"
    assert guided_fetched["instruction_state"]["active"] is False
    assert guided_fetched["instruction_state"]["historical"] is True
    assert guided_fetched["instruction_state"]["do_not_execute"] is True
    assert guided_fetched["instruction_state"]["reason"] == "instruction_ttl_elapsed"
    assert len(observation.calls) == observation_call_count
    assert locks.current("proxmox_vm", "vmid:306")["owner_id"] == operation_id


@pytest.mark.parametrize("durable_status", ["stale", "reconciliation_required"])
def test_replay_and_get_never_present_non_active_durable_lock_as_executable(durable_status):
    case, _, locks, _ = use_case()
    command = plan_command(idempotency_key=f"inactive-display-lock-{durable_status}")
    planned = case.plan_unlock(command)
    operation_id = planned["operation"]["operation_id"]
    locks.locks[("proxmox_vm", "vmid:306")]["durable"]["status"] = durable_status

    replay = case.plan_unlock(command)
    fetched = case.get(operation_id)

    for result in (replay, fetched):
        assert result["operation"]["status"] == "awaiting_operator"
        assert result["instruction_state"]["active"] is False
        assert result["instruction_state"]["historical"] is True
        assert result["instruction_state"]["do_not_execute"] is True
        assert result["instruction_state"]["reason"] == "target_lock_mismatch"
    assert locks.current("proxmox_vm", "vmid:306")["owner_id"] == operation_id


def test_expiry_requires_the_exact_original_config_lock_before_release():
    now = [FIXED_NOW]
    case, observation, locks, store = use_case(clock=lambda: now[0])
    command = plan_command(idempotency_key="expiry-changed-lock")
    planned = case.plan_unlock(command)
    operation_id = planned["operation"]["operation_id"]
    observation.config_lock = "snapshot"
    now[0] = FIXED_NOW + timedelta(seconds=301)

    replay = case.plan_unlock(command)

    assert replay["operation"]["status"] == "needs_reconciliation"
    assert store.get(operation_id).details["reconciliation_reason"] == (
        "config_lock_changed_at_instruction_expiry"
    )
    assert locks.current("proxmox_vm", "vmid:306")["owner_id"] == operation_id


def test_expiry_requires_the_exact_owned_target_lock_identity_before_release():
    now = [FIXED_NOW]
    case, _, locks, store = use_case(clock=lambda: now[0])
    command = plan_command(idempotency_key="expiry-replaced-target-lock")
    planned = case.plan_unlock(command)
    operation_id = planned["operation"]["operation_id"]
    locks.locks[("proxmox_vm", "vmid:306")]["lock_id"] = "lock-replaced-after-handoff"
    locks.locks[("proxmox_vm", "vmid:306")]["durable"][
        "operation_lock_id"
    ] = "lock-replaced-after-handoff"
    now[0] = FIXED_NOW + timedelta(seconds=301)

    replay = case.plan_unlock(command)

    assert replay["operation"]["status"] == "needs_reconciliation"
    assert store.get(operation_id).details["reconciliation_reason"] == (
        "target_lock_missing_at_instruction_expiry"
    )
    assert locks.current("proxmox_vm", "vmid:306")["lock_id"] == "lock-replaced-after-handoff"


def test_verified_terminal_result_is_not_published_when_target_lock_release_fails():
    class RefusingTerminalCommit(FakeRecovery):
        def commit_observation(self, lease, **kwargs):
            if kwargs.get("release_target_lock"):
                raise RuntimeError("terminal transaction unavailable")
            return super().commit_observation(lease, **kwargs)

    locks = FakeLocks()
    store = SqlAlchemyOperationStore(clock=lambda: FIXED_NOW)
    recovery = RefusingTerminalCommit(operations=store, locks=locks)
    case, observation, _, store = use_case(locks=locks, store=store, recovery=recovery)
    planned = case.plan_unlock(plan_command(idempotency_key="terminal-release-failure"))
    operation_id = planned["operation"]["operation_id"]
    digest = planned["operation"]["plan_digest"]
    case.attest(
        AttestGuidedQmCommand.from_request(
            operation_id,
            {"plan_digest": digest, "command_executed": True},
            actor=ACTOR,
        )
    )
    observation.config_lock = ""

    with pytest.raises(GuidedQmError) as error:
        case.verify(VerifyGuidedQmCommand.from_request(operation_id, {"plan_digest": digest}, actor=ACTOR))
    assert error.value.code == "GUIDED_QM_RECOVERY_UNAVAILABLE"
    assert store.get(operation_id).status == "verifying"
    assert case._ports.recovery.get(operation_id).status == "leased"
    assert locks.current("proxmox_vm", "vmid:306")["owner_id"] == operation_id


def test_expired_late_attestation_remains_reconciliation_when_target_lock_is_absent():
    now = [FIXED_NOW]
    case, _, locks, store = use_case(clock=lambda: now[0])
    command = plan_command(idempotency_key="expired-late-attestation-no-lock")
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

    with pytest.raises(GuidedQmError) as raised:
        case.verify(
            VerifyGuidedQmCommand.from_request(operation_id, {"plan_digest": digest}, actor=ACTOR)
        )

    assert attested["operation"]["status"] == "needs_reconciliation"
    assert raised.value.code == "GUIDED_QM_TARGET_LOCK_LOST"
    assert store.get(operation_id).status == "needs_reconciliation"
    assert locks.current("proxmox_vm", "vmid:306") is None
