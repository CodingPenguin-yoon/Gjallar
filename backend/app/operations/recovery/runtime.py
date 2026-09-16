"""Opt-in FastAPI lifecycle runtime for durable recovery."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from dataclasses import dataclass

from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.guided_qm.infrastructure.adapters import SharedGuidedQmTargetLockAdapter
from app.operations.guided_qm.recovery import GuidedQmUnlockRecoveryHandler
from app.operations.recovery.application import (
    OperationRecoveryCoordinator,
    OperationRecoveryRunner,
    VmShutdownRecoveryHandler,
    VmStartRecoveryHandler,
)
from app.operations.recovery.infrastructure.job_projection import (
    SqlAlchemyVmShutdownRecoveryJobProjection,
    SqlAlchemyVmStartRecoveryJobProjection,
)
from app.operations.recovery.infrastructure.observation import ProxmoxRecoveryObservationAdapter
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.target_lock import get_target_operation_lock
from app.operations.vm_create.recovery import VmCreateRecoveryHandler
from app.operations.vm_create.recovery_adapters import (
    ProxmoxVmCreateRecoveryObservationAdapter,
    SqlAlchemyVmCreateRecoveryProjection,
)
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
    max_attempts: int = 5

    @classmethod
    def from_env(cls) -> "RecoveryRuntimeConfig":
        return cls(
            enabled=_read_bool("GJALLAR_OPERATION_RECOVERY_ENABLED", False),
            poll_seconds=_read_float("GJALLAR_OPERATION_RECOVERY_POLL_SECONDS", 5, minimum=1, maximum=300),
            lease_seconds=_read_float("GJALLAR_OPERATION_RECOVERY_LEASE_SECONDS", 60, minimum=10, maximum=900),
            max_attempts=int(
                _read_float("GJALLAR_OPERATION_RECOVERY_MAX_ATTEMPTS", 5, minimum=1, maximum=20)
            ),
        )


def build_recovery_runner(*, config: RecoveryRuntimeConfig | None = None) -> OperationRecoveryRunner:
    effective = config or RecoveryRuntimeConfig.from_env()
    recovery = SqlAlchemyRecoveryStore()
    operations = SqlAlchemyOperationStore()
    observation_factory = lambda: ProxmoxRecoveryObservationAdapter(get_default_proxmox_mutation_client())
    start_handler = VmStartRecoveryHandler(
        recovery=recovery,
        operations=operations,
        observation_factory=observation_factory,
        compatibility_projection=SqlAlchemyVmStartRecoveryJobProjection(),

        target_lock_reader=get_target_operation_lock,
        max_attempts=effective.max_attempts,
    )
    shutdown_handler = VmShutdownRecoveryHandler(
        recovery=recovery,
        operations=operations,
        observation_factory=observation_factory,
        compatibility_projection=SqlAlchemyVmShutdownRecoveryJobProjection(),

        target_lock_reader=get_target_operation_lock,
        max_attempts=effective.max_attempts,
    )
    create_handler = VmCreateRecoveryHandler(
        recovery=recovery,
        operations=operations,
        observation_factory=lambda: ProxmoxVmCreateRecoveryObservationAdapter(
            get_default_proxmox_mutation_client()
        ),
        compatibility_projection=SqlAlchemyVmCreateRecoveryProjection(),

        target_lock_reader=get_target_operation_lock,
        max_attempts=effective.max_attempts,
    )
    guided_handler = GuidedQmUnlockRecoveryHandler(
        operations=operations,
        recovery=recovery,
        observation_factory=observation_factory,
        locks=SharedGuidedQmTargetLockAdapter(),
        recovery_lease_seconds=effective.lease_seconds,
        max_attempts=effective.max_attempts,
    )
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"
    return OperationRecoveryRunner(
        recovery=recovery,
        handlers={
            "vm_start_observation": start_handler,
            "vm_shutdown_observation": shutdown_handler,
            "vm_create_observation": create_handler,
            "guided_qm_unlock_observation": guided_handler,
        },
        worker_id=worker_id,
        lease_seconds=effective.lease_seconds,
        max_attempts=effective.max_attempts,
    )


def build_recovery_coordinator(
    *,
    config: RecoveryRuntimeConfig | None = None,
) -> OperationRecoveryCoordinator:
    effective = config or RecoveryRuntimeConfig.from_env()
    worker_id = f"operator:{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"
    return OperationRecoveryCoordinator(
        recovery=SqlAlchemyRecoveryStore(),
        operations=SqlAlchemyOperationStore(),
        runner=build_recovery_runner(config=effective),
        lock_reader=get_target_operation_lock,
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
