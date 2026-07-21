"""Opt-in PostgreSQL checks for recovery coordination semantics."""

from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import OperationLockRecord
from app.operations.core.domain import OperationActor, OperationSpec, operation_digest
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.locks.infrastructure.repository import SqlAlchemyDurableTargetLockRepository
from app.operations.recovery.application import VmShutdownRecoveryHandler
from app.operations.recovery.domain import RecoveryLeaseLost, RecoverySpec
from app.operations.recovery.infrastructure.models import OperationRecoveryItemRecord
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore


pytestmark = pytest.mark.postgresql


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime.now(timezone.utc).replace(microsecond=0)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _postgres_url() -> str:
    url = str(os.getenv("GJALLAR_POSTGRES_TEST_URL") or "").strip()
    if not url:
        pytest.skip("GJALLAR_POSTGRES_TEST_URL is not configured")
    return url


def test_postgresql_partial_unique_skip_locked_and_fencing():
    engine = create_engine(_postgres_url(), pool_pre_ping=True)

    @contextmanager
    def sessions():
        with Session(engine) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    suffix = uuid.uuid4().hex[:12]
    operation_id = f"pg-recovery-{suffix}"
    lock_a = f"pg-lock-a-{suffix}"
    lock_b = f"pg-lock-b-{suffix}"
    shutdown_lock = f"pg-lock-shutdown-{suffix}"
    vmid = 900000 + (int(suffix[:5], 16) % 90000)
    cluster_id = f"pg-test-{suffix}"
    scope_key = f"{cluster_id}|proxmox_locator|{vmid}"
    clock = MutableClock()
    operations = SqlAlchemyOperationStore(sessions=sessions, clock=clock)
    recovery = SqlAlchemyRecoveryStore(sessions=sessions, clock=clock)
    intent = {"operation": "vm_start", "target": {"node_id": "node-pg", "vmid": vmid}}

    try:
        index_names = {index["name"] for index in inspect(engine).get_indexes("operation_locks")}
        assert "uq_operation_locks_open_locator" in index_names
        assert inspect(engine).has_table("operation_recovery_items")

        operations.create(
            OperationSpec(
                operation_id=operation_id,
                operation_type="vm_start",
                execution_mode="managed_api",
                target_type="proxmox_vm",
                target_id=f"vmid:{vmid}",
                idempotency_key=f"idem-{operation_id}",
                intent_digest=operation_digest(intent),
                plan_digest=operation_digest({"intent": intent, "version": 1}),
                actor=OperationActor(user_id="pg-test", username="pg-test", role="operator"),
                initial_status="dispatching",
                initial_stage="start",
                details={"target": {"node_id": "node-pg", "vmid": vmid}, "proxmox_upid": "UPID:pg:test"},
            )
        )

        with sessions() as session:
            session.add(
                OperationLockRecord(
                    operation_lock_id=lock_a,
                    operation_type="vm_start",
                    scope_type="proxmox_locator",
                    scope_key=scope_key,
                    status="active",
                    cluster_id=cluster_id,
                    vmid=vmid,
                    owner_id=operation_id,
                    reason="postgresql_constraint_test",
                    evidence={},
                    created_at=clock.now,
                    updated_at=clock.now,
                )
            )
        with pytest.raises(IntegrityError):
            with sessions() as session:
                session.add(
                    OperationLockRecord(
                        operation_lock_id=lock_b,
                        operation_type="guided_qm_vm_unlock",
                        scope_type="proxmox_locator",
                        scope_key=scope_key,
                        status="reconciliation_required",
                        cluster_id=cluster_id,
                        vmid=vmid,
                        owner_id=f"other-{operation_id}",
                        reason="postgresql_constraint_test",
                        evidence={},
                        created_at=clock.now,
                        updated_at=clock.now,
                    )
                )
                session.flush()

        with sessions() as session:
            session.add(
                OperationLockRecord(
                    operation_lock_id=shutdown_lock,
                    operation_type="vm_shutdown",
                    scope_type="proxmox_locator",
                    scope_key=scope_key,
                    status="released",
                    cluster_id=cluster_id,
                    vmid=vmid,
                    owner_id=f"shutdown-{operation_id}",
                    reason="postgresql_shutdown_constraint_test",
                    evidence={},
                    created_at=clock.now,
                    updated_at=clock.now,
                )
            )

        stale = recovery.prepare_and_claim(
            RecoverySpec(
                operation_id=operation_id,
                recovery_kind="vm_start_observation",
                details={"node_id": "node-pg", "vmid": vmid, "upid": "UPID:pg:test"},
            ),
            lease_owner="foreground",
            lease_seconds=10,
        )
        assert stale.item.lease_expires_at is not None and stale.item.lease_expires_at.tzinfo is not None
        clock.advance(11)
        barrier = threading.Barrier(2)

        def claim(worker: str):
            barrier.wait(timeout=5)
            return SqlAlchemyRecoveryStore(sessions=sessions, clock=clock).claim_due(
                lease_owner=worker,
                lease_seconds=60,
                limit=1,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            claimed_batches = list(pool.map(claim, ("runner-a", "runner-b")))
        claimed = [lease for batch in claimed_batches for lease in batch]
        assert len(claimed) == 1
        assert claimed[0].generation == stale.generation + 1

        with pytest.raises(RecoveryLeaseLost):
            recovery.commit_observation(
                stale,
                event_type="postgresql_stale_write",
                stage="reconciliation",
                recovery_status="retry_wait",
            )
    finally:
        with sessions() as session:
            session.query(OperationRecoveryItemRecord).filter(
                OperationRecoveryItemRecord.operation_id == operation_id
            ).delete(synchronize_session=False)
            session.query(OperationLockRecord).filter(
                OperationLockRecord.operation_lock_id.in_((lock_a, lock_b, shutdown_lock))
            ).delete(synchronize_session=False)
            from app.operations.core.infrastructure.models import OperationEventRecord, OperationRecord

            session.query(OperationEventRecord).filter(
                OperationEventRecord.operation_id == operation_id
            ).delete(synchronize_session=False)
            session.query(OperationRecord).filter(
                OperationRecord.operation_id == operation_id
            ).delete(synchronize_session=False)
        engine.dispose()


def test_postgresql_vm_shutdown_restart_observes_then_completes_without_redispatch():
    engine = create_engine(_postgres_url(), pool_pre_ping=True)

    @contextmanager
    def sessions():
        with Session(engine) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    suffix = uuid.uuid4().hex[:12]
    operation_id = f"pg-shutdown-restart-{suffix}"
    vmid = 910000 + (int(suffix[:5], 16) % 80000)
    clock = MutableClock()
    operations = SqlAlchemyOperationStore(sessions=sessions, clock=clock)
    locks = SqlAlchemyDurableTargetLockRepository(sessions=sessions, clock=clock)
    recovery = SqlAlchemyRecoveryStore(sessions=sessions, clock=clock)
    intent = {"operation": "vm_shutdown", "target": {"node_id": "node-pg", "vmid": vmid}}

    class ObservationOnlyClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, object]] = []

        def get_task_status(self, *, node: str, upid: str):
            self.calls.append(("get_task_status", node, upid))
            return {"status": "stopped", "exitstatus": "OK"}

        def get_vm_status(self, *, node: str, vmid: int):
            self.calls.append(("get_vm_status", node, vmid))
            return {"name": "pg-test-vm", "status": "stopped"}

    class Projection:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def record_terminal(self, **payload):
            self.calls.append(payload)

    try:
        operations.create(
            OperationSpec(
                operation_id=operation_id,
                operation_type="vm_shutdown",
                execution_mode="managed_api",
                target_type="proxmox_vm",
                target_id=f"vmid:{vmid}",
                idempotency_key=f"idem-{operation_id}",
                intent_digest=operation_digest(intent),
                plan_digest=operation_digest({"intent": intent, "version": 1}),
                actor=OperationActor(user_id="pg-test", username="pg-test", role="operator"),
                initial_status="dispatching",
                initial_stage="shutdown",
                details={
                    "target": {"node_id": "node-pg", "vmid": vmid},
                    "proxmox_upid": "UPID:node-pg:test:qmshutdown",
                },
            )
        )
        locks.acquire(
            operation_type="vm_shutdown",
            cluster_id="gjallar-mvp",
            vmid=vmid,
            owner_id=operation_id,
            reason="postgresql_shutdown_restart_test",
        )
        recovery.prepare_and_claim(
            RecoverySpec(
                operation_id=operation_id,
                recovery_kind="vm_shutdown_observation",
                details={
                    "node_id": "node-pg",
                    "vmid": vmid,
                    "upid": "UPID:node-pg:test:qmshutdown",
                },
            ),
            lease_owner="foreground-before-restart",
            lease_seconds=10,
        )
        clock.advance(11)
        restarted_store = SqlAlchemyRecoveryStore(sessions=sessions, clock=clock)
        claimed = restarted_store.claim_due(
            lease_owner="new-process-after-restart",
            lease_seconds=60,
            limit=1,
        )
        assert len(claimed) == 1
        client = ObservationOnlyClient()
        projection = Projection()
        handler = VmShutdownRecoveryHandler(
            recovery=restarted_store,
            operations=SqlAlchemyOperationStore(sessions=sessions, clock=clock),
            observation_factory=lambda: client,
            compatibility_projection=projection,
        )

        result = handler.handle(claimed[0])

        assert result.outcome == "succeeded"
        assert operations.get(operation_id).status == "succeeded"
        assert restarted_store.get(operation_id).status == "completed"
        assert locks.current(cluster_id="gjallar-mvp", vmid=vmid) is None
        assert client.calls == [
            ("get_task_status", "node-pg", "UPID:node-pg:test:qmshutdown"),
            ("get_vm_status", "node-pg", vmid),
        ]
        assert not hasattr(client, "shutdown_vm")
        assert len(projection.calls) == 1
    finally:
        with sessions() as session:
            session.query(OperationRecoveryItemRecord).filter(
                OperationRecoveryItemRecord.operation_id == operation_id
            ).delete(synchronize_session=False)
            session.query(OperationLockRecord).filter(
                OperationLockRecord.owner_id == operation_id
            ).delete(synchronize_session=False)
            from app.operations.core.infrastructure.models import OperationEventRecord, OperationRecord

            session.query(OperationEventRecord).filter(
                OperationEventRecord.operation_id == operation_id
            ).delete(synchronize_session=False)
            session.query(OperationRecord).filter(
                OperationRecord.operation_id == operation_id
            ).delete(synchronize_session=False)
        engine.dispose()
