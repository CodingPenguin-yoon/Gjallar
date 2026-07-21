"""Application-facing durable target lock port."""

from __future__ import annotations

from typing import Protocol

from app.operations.locks.domain import DurableTargetLock


class DurableTargetLockPort(Protocol):
    def acquire(
        self,
        *,
        operation_type: str,
        cluster_id: str,
        vmid: int,
        owner_id: str,
        reason: str,
    ) -> DurableTargetLock: ...

    def current(self, *, cluster_id: str, vmid: int) -> DurableTargetLock | None: ...

    def release(self, lock: DurableTargetLock, *, reason: str) -> bool: ...

    def release_owned(self, *, cluster_id: str, vmid: int, owner_id: str, reason: str) -> bool: ...
