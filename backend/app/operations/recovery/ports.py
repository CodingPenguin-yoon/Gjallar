"""Application-facing persistence contract for durable recovery."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol, Sequence

from app.operations.core.domain import OperationActor, OperationSnapshot
from app.operations.recovery.domain import RecoveryItem, RecoveryLease, RecoverySpec


class RecoveryStorePort(Protocol):
    def prepare_and_claim(
        self,
        spec: RecoverySpec,
        *,
        lease_owner: str,
        lease_seconds: float,
        expected_operation_version: int | None = None,
        expected_operation_checksum: str | None = None,
    ) -> RecoveryLease: ...

    def get(self, operation_id: str) -> RecoveryItem | None: ...

    def claim_operation(
        self,
        operation_id: str,
        *,
        lease_owner: str,
        lease_seconds: float,
        expected_operation_version: int | None = None,
        expected_operation_checksum: str | None = None,
    ) -> RecoveryLease: ...

    def claim_due(
        self,
        *,
        lease_owner: str,
        lease_seconds: float,
        limit: int = 1,
    ) -> list[RecoveryLease]: ...

    def heartbeat(self, lease: RecoveryLease, *, lease_seconds: float) -> RecoveryLease: ...

    def commit_observation(
        self,
        lease: RecoveryLease,
        *,
        event_type: str,
        stage: str,
        payload: Mapping[str, Any] | None = None,
        details_patch: Mapping[str, Any] | None = None,
        next_status: str | None = None,
        expected_statuses: Sequence[str] | None = None,
        actor: OperationActor | None = None,
        recovery_status: str,
        retry_delay_seconds: float = 0,
        error_code: str | None = None,
        recovery_details_patch: Mapping[str, Any] | None = None,
        release_target_lock: bool = False,
        require_exact_reconciliation_lock: bool = True,
        bind_target_lock: bool = False,
        expected_operation_version: int | None = None,
        expected_operation_checksum: str | None = None,
        projector: Callable[[Any], Mapping[str, Any] | None] | None = None,
    ) -> tuple[OperationSnapshot, RecoveryItem]: ...
