"""Application-facing persistence contract for Operations."""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from app.operations.core.domain import (
    OperationActor,
    OperationCreateResult,
    OperationEvent,
    OperationSnapshot,
    OperationSpec,
)


class OperationStorePort(Protocol):
    def create(self, spec: OperationSpec, *, event_payload: Mapping[str, Any] | None = None) -> OperationCreateResult: ...

    def get(self, operation_id: str) -> OperationSnapshot | None: ...

    def list(
        self,
        *,
        status: str | None = None,
        operation_type: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        limit: int = 50,
    ) -> list[OperationSnapshot]: ...

    def transition(
        self,
        operation_id: str,
        *,
        next_status: str,
        event_type: str,
        stage: str,
        payload: Mapping[str, Any] | None = None,
        details_patch: Mapping[str, Any] | None = None,
        actor: OperationActor | None = None,
        expected_statuses: Sequence[str] | None = None,
    ) -> OperationSnapshot: ...

    def append_event(
        self,
        operation_id: str,
        *,
        event_type: str,
        stage: str,
        payload: Mapping[str, Any] | None = None,
        details_patch: Mapping[str, Any] | None = None,
        actor: OperationActor | None = None,
        expected_statuses: Sequence[str] | None = None,
    ) -> OperationSnapshot: ...

    def transition_for_target_lock_conflict(
        self,
        operation_id: str,
        *,
        conflicting_lock_id: str,
        conflicting_owner_id: str,
        next_status: str,
        event_type: str,
        stage: str,
        payload: Mapping[str, Any] | None = None,
        details_patch: Mapping[str, Any] | None = None,
    ) -> OperationSnapshot: ...

    def list_events(self, operation_id: str) -> list[OperationEvent]: ...

    def transition_pre_dispatch_failure(
        self,
        operation_id: str,
        *,
        target_lock_id: str,
        event_type: str,
        stage: str,
        payload: Mapping[str, Any] | None = None,
        details_patch: Mapping[str, Any] | None = None,
    ) -> bool: ...
