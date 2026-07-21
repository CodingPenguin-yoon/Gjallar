"""Application entry point for graceful VM Shutdown."""

from __future__ import annotations

from typing import Any

from app.operations.vm_shutdown.domain import VmShutdownCommand
from app.operations.vm_shutdown.ports import VmShutdownExecutionPorts, VmShutdownWorkflowPort


class VmShutdownUseCase:
    def __init__(self, *, workflow: VmShutdownWorkflowPort, ports: VmShutdownExecutionPorts) -> None:
        self._workflow = workflow
        self._ports = ports

    def execute(self, command: VmShutdownCommand) -> dict[str, Any]:
        return self._workflow.execute(command, self._ports)
