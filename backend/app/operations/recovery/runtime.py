"""Opt-in FastAPI lifecycle runtime for durable recovery."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from dataclasses import dataclass

from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.recovery.application import OperationRecoveryRunner, VmShutdownRecoveryHandler, VmStartRecoveryHandler
from app.operations.recovery.infrastructure.job_projection import (
    SqlAlchemyVmShutdownRecoveryJobProjection,
    SqlAlchemyVmStartRecoveryJobProjection,
)
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.target_lock import release_target_operation_lock_for_owner
from app.proxmox.client import get_default_proxmox_mutation_client


logger = logging.getLogger(__name__)


def _read_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _read_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


@dataclass(frozen=True)
class RecoveryRuntimeConfig:
    enabled: bool
    poll_seconds: float
    lease_seconds: float

    @classmethod
    def from_env(cls) -> "RecoveryRuntimeConfig":
        return cls(
            enabled=_read_bool("GJALLAR_OPERATION_RECOVERY_ENABLED", False),
            poll_seconds=_read_float("GJALLAR_OPERATION_RECOVERY_POLL_SECONDS", 5, minimum=1, maximum=300),
            lease_seconds=_read_float("GJALLAR_OPERATION_RECOVERY_LEASE_SECONDS", 60, minimum=10, maximum=900),
        )


def build_recovery_runner(*, config: RecoveryRuntimeConfig | None = None) -> OperationRecoveryRunner:
    effective = config or RecoveryRuntimeConfig.from_env()
    recovery = SqlAlchemyRecoveryStore()
    start_handler = VmStartRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(),
        observation_factory=get_default_proxmox_mutation_client,
        compatibility_projection=SqlAlchemyVmStartRecoveryJobProjection(),
        release_compatibility_lock=release_target_operation_lock_for_owner,
    )
    shutdown_handler = VmShutdownRecoveryHandler(
        recovery=recovery,
        operations=SqlAlchemyOperationStore(),
        observation_factory=get_default_proxmox_mutation_client,
        compatibility_projection=SqlAlchemyVmShutdownRecoveryJobProjection(),
        release_compatibility_lock=release_target_operation_lock_for_owner,
    )
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"
    return OperationRecoveryRunner(
        recovery=recovery,
        handlers={
            "vm_start_observation": start_handler,
            "vm_shutdown_observation": shutdown_handler,
        },
        worker_id=worker_id,
        lease_seconds=effective.lease_seconds,
    )


async def run_recovery_loop(stop_event: asyncio.Event, *, config: RecoveryRuntimeConfig) -> None:
    """Run one bounded claim at a time until application shutdown."""

    runner = build_recovery_runner(config=config)
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(runner.run_once)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # A transient DB/pool failure must not permanently kill the
            # application-owned observer. Log only the exception type because
            # upstream messages can contain connection details.
            logger.warning("Operation recovery iteration failed: %s", type(exc).__name__)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=config.poll_seconds)
        except TimeoutError:
            pass
