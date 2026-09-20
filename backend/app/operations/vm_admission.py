"""Atomic VM admission shared by scoped operations and GET-only recovery."""
from contextlib import contextmanager
from dataclasses import replace
import uuid

from app.db.session import session_scope
from app.operations.core.domain import OperationIntentConflict
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.locks.infrastructure.repository import SqlAlchemyDurableTargetLockRepository
from app.operations.recovery.domain import RecoverySpec
from app.operations.locks.binding import expected_lock_count
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore


class VmMutationAdmission:
    def __init__(self, *, recovery_kind):
        self.recovery_kind = recovery_kind

    def prepare(self, spec, *, cluster_id, vmid, related_vmids=()):
        if related_vmids and (expected_lock_count(spec.operation_type) != 2 or len(related_vmids) != 1
                              or related_vmids[0] == vmid or spec.details.get("source", {}).get("vmid") != related_vmids[0]):
            raise ValueError("Invalid related VM lock scope")
        if expected_lock_count(spec.operation_type) == 2 and len(related_vmids) != 1:
            raise ValueError("Multi-VM admission requires both source and destination locks")
        with session_scope() as session:
            @contextmanager
            def shared():
                yield session

            operations = SqlAlchemyOperationStore(sessions=shared)
            existing = operations.get(spec.operation_id)
            if existing is not None:
                if existing.intent_digest != spec.intent_digest:
                    raise OperationIntentConflict(spec.operation_id)
                return existing, None
            locks = SqlAlchemyDurableTargetLockRepository(sessions=shared)
            acquired = {target: locks.acquire(
                operation_type=spec.operation_type, cluster_id=cluster_id, vmid=target,
                owner_id=spec.operation_id, reason=spec.operation_type + "_dispatch",
            ) for target in sorted({vmid, *related_vmids})}
            lock = acquired[vmid]
            # A competing request can finish between the first lookup and lock
            # acquisition. Never redispatch its already recorded operation.
            existing = operations.get(spec.operation_id)
            if existing is not None:
                if existing.intent_digest != spec.intent_digest:
                    raise OperationIntentConflict(spec.operation_id)
                for held in acquired.values():
                    locks.release(held, reason=spec.operation_type + "_completed_replay")
                return existing, None
            binding = {"target_lock_id": lock.lock_id, "cluster_id": cluster_id,
                       "node_id": spec.details["target"]["node_id"], "vmid": vmid,
                       "operation_type": spec.operation_type, "execution_mode": spec.execution_mode}
            if related_vmids:
                binding["related_target_locks"] = [{"lock_id": acquired[target].lock_id, "vmid": target}
                                                   for target in sorted(related_vmids)]
            created = operations.create(replace(spec, details={**spec.details, **binding}))
            lease = SqlAlchemyRecoveryStore(sessions=shared).prepare_and_claim(
                RecoverySpec(spec.operation_id, self.recovery_kind, binding),
                lease_owner=spec.operation_type + ":" + uuid.uuid4().hex, lease_seconds=60,
            )
            return created.operation, lease

