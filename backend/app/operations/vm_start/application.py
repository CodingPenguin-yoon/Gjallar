"""Application entry point for the VM Start vertical architecture slice."""

from __future__ import annotations

from typing import Any

from app.operations.vm_start.domain import VmStartCommand
from app.operations.vm_start.ports import VmStartExecutionPorts, VmStartWorkflowPort


class VmStartUseCase:
    """Execute a VM Start command using only explicit application ports."""

    def __init__(self, *, workflow: VmStartWorkflowPort, ports: VmStartExecutionPorts) -> None:
        self._workflow = workflow
        self._ports = ports

    def execute(self, command: VmStartCommand) -> dict[str, Any]:
        return self._workflow.execute(command, self._ports)
