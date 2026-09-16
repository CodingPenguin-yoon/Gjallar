"""Action-specific GET-only recovery handler for Guided `qm unlock`."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from app.operations.core.ports import OperationStorePort
from app.operations.guided_qm.application import GuidedQmUnlockUseCase
from app.operations.guided_qm.errors import GuidedQmError
from app.operations.guided_qm.ports import (
    GuidedQmExecutionPorts,
    GuidedQmObservationPort,
    GuidedQmTargetLockPort,
)
from app.operations.recovery.application import RecoveryRunResult, SYSTEM_RECOVERY_ACTOR
from app.operations.recovery.domain import RecoveryLease
from app.operations.recovery.ports import RecoveryStorePort


Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class GuidedQmUnlockRecoveryHandler:
    """Resume only Proxmox API observation and local fenced coordination.

    The handler receives an observation-only port. It has no shell-command or
    Proxmox mutation capability, so a stale `qm unlock` instruction cannot be
    executed or replayed by recovery.
    """

    def __init__(
        self,
        *,
        operations: OperationStorePort,
        recovery: RecoveryStorePort,
        observation_factory: Callable[[], GuidedQmObservationPort],
        locks: GuidedQmTargetLockPort,
        clock: Clock = _utc_now,
        recovery_lease_seconds: float = 60.0,
        max_attempts: int = 5,
    ) -> None:
        self._operations = operations
        self._recovery = recovery
        self._observation_factory = observation_factory
        self._locks = locks
        self._clock = clock
        self._recovery_lease_seconds = max(float(recovery_lease_seconds), 1.0)
        self._max_attempts = max(int(max_attempts), 1)

    def handle(self, lease: RecoveryLease) -> RecoveryRunResult:
        use_case = GuidedQmUnlockUseCase(
            ports=GuidedQmExecutionPorts(
                operations=self._operations,
                observation=self._observation_factory(),
                locks=self._locks,
                recovery=self._recovery,
                recovery_lease_seconds=self._recovery_lease_seconds,
            ),
            clock=self._clock,
            recovery_max_attempts=self._max_attempts,
        )
        try:
            result = use_case.recover(lease)
        except GuidedQmError as exc:
            if exc.code != "GUIDED_QM_RECOVERY_BINDING_MISMATCH":
                raise
            operation = self._operations.get(lease.operation_id)
            if operation is None:
                raise
            next_status = (
                "needs_reconciliation"
                if operation.status
                in {"awaiting_operator", "awaiting_verification", "verifying", "expired"}
                else None
            )
            self._recovery.commit_observation(
                lease,
                next_status=next_status,
                event_type="guided_qm_recovery_binding_mismatch",
                stage="reconciliation",
                payload={"code": exc.code},
                details_patch={"reconciliation_code": exc.code},
                expected_statuses=[operation.status],
                actor=SYSTEM_RECOVERY_ACTOR,
                recovery_status="paused",
                error_code=exc.code,
                recovery_details_patch={"binding_error": exc.code},
                require_exact_reconciliation_lock=False,
            )
            return RecoveryRunResult(
                operation_id=lease.operation_id,
                outcome="paused_binding_mismatch",
            )
        operation = result["operation"]
        return RecoveryRunResult(
            operation_id=lease.operation_id,
            outcome=f"guided_qm_{operation['status']}",
        )


__all__ = ["GuidedQmUnlockRecoveryHandler"]
