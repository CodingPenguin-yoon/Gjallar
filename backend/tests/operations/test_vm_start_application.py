"""Architecture tests for the VM Start vertical slice."""

from __future__ import annotations

import ast
import hashlib
import inspect
from unittest.mock import Mock, patch

import pytest

from app.operations.vm_start.application import VmStartUseCase
from app.operations.vm_start.domain import VmStartCommand, build_vm_start_job_id
from app.operations.vm_start.ports import VmStartExecutionPorts


class RecordingWorkflow:
    def __init__(self, result: dict | None = None, error: Exception | None = None) -> None:
        self.result = result or {"status": "completed"}
        self.error = error
        self.calls = []

    def execute(self, command, ports):
        self.calls.append((command, ports))
        if self.error is not None:
            raise self.error
        return self.result


def execution_ports() -> VmStartExecutionPorts:
    return VmStartExecutionPorts(
        operations=object(),
        workloads=object(),
        mutation_factory=lambda: None,
        jobs=object(),
        evidence=object(),
        locks=object(),
    )


def test_use_case_delegates_command_and_explicit_ports():
    command = VmStartCommand.from_request(node_id="node-a", vmid=306, payload={}, actor={})
    ports = execution_ports()
    workflow = RecordingWorkflow(result={"job_id": "job-1", "status": "completed"})

    result = VmStartUseCase(workflow=workflow, ports=ports).execute(command)

    assert result == {"job_id": "job-1", "status": "completed"}
    assert workflow.calls == [(command, ports)]


def test_use_case_preserves_workflow_errors():
    expected = RuntimeError("workflow failed")
    use_case = VmStartUseCase(workflow=RecordingWorkflow(error=expected), ports=execution_ports())

    with pytest.raises(RuntimeError) as raised:
        use_case.execute(VmStartCommand.from_request(node_id="node-a", vmid=306, payload={}, actor={}))

    assert raised.value is expected


def test_command_owns_request_values_and_builds_stable_legacy_contracts():
    payload = {"expected_name": " stopped-app ", "expected_status": " stopped ", "ignored": "value"}
    actor = {"subject": "operator-a"}
    command = VmStartCommand.from_request(node_id="node/a", vmid="306", payload=payload, actor=actor)
    payload["expected_name"] = "changed"
    actor["subject"] = "changed"

    digest = hashlib.sha256("node/a:306:idem-1".encode("utf-8")).hexdigest()[:16]
    assert build_vm_start_job_id(node_id="node/a", vmid=306, idempotency_key="idem-1") == (
        f"vm-start-node-a-306-{digest}"
    )
    assert command.expected == {"expected_name": "stopped-app", "expected_status": "stopped"}
    assert command.actor == {"subject": "operator-a"}
    assert command.stable_intent == {
        "schema": "vm_start_intent.v1",
        "operation": "vm_start",
        "target": {"node_id": "node/a", "vmid": 306},
        "expected": {"expected_name": "stopped-app", "expected_status": "stopped"},
    }


@pytest.mark.parametrize("module", [
    __import__("app.operations.core.domain", fromlist=["*"]),
    __import__("app.operations.core.ports", fromlist=["*"]),
    __import__("app.operations.vm_start.domain", fromlist=["*"]),
    __import__("app.operations.vm_start.ports", fromlist=["*"]),
    __import__("app.operations.vm_start.application", fromlist=["*"]),
    __import__("app.operations.vm_start.errors", fromlist=["*"]),
    __import__("app.operations.vm_start.precheck", fromlist=["*"]),
    __import__("app.operations.vm_start.tracking", fromlist=["*"]),
    __import__("app.operations.vm_start.workflow", fromlist=["*"]),
    __import__("app.operations.guided_qm.domain", fromlist=["*"]),
    __import__("app.operations.guided_qm.ports", fromlist=["*"]),
    __import__("app.operations.guided_qm.application", fromlist=["*"]),
    __import__("app.operations.vm_create.domain", fromlist=["*"]),
    __import__("app.operations.vm_create.application", fromlist=["*"]),
])
def test_application_slice_does_not_import_concrete_infrastructure(module):
    tree = ast.parse(inspect.getsource(module))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = ("fastapi", "sqlalchemy", "app.db", "app.jobs", "app.proxmox", "app.vm_actions")
    assert not any(name == prefix or name.startswith(f"{prefix}.") for name in imported for prefix in forbidden)


def test_public_facade_composes_command_ports_and_use_case():
    from app.vm_actions.start import run_vm_start

    client = Mock()
    client.redacted_connection_context.return_value = {"mode": "test"}
    inventory = object()
    actor = {"user_id": "user-1", "username": "operator-a", "role": "operator"}
    expected = {"job_id": "job-1", "status": "completed"}
    use_case = Mock()
    use_case.execute.return_value = expected

    with patch("app.vm_actions.start.VmStartUseCase", return_value=use_case) as use_case_type:
        result = run_vm_start(
            node_id="node-a",
            vmid=306,
            payload={"vm_start_acknowledged": True},
            inventory_adapter=inventory,
            actor=actor,
            client=client,
        )

    assert result == expected
    command = use_case.execute.call_args.args[0]
    assert command == VmStartCommand.from_request(
        node_id="node-a",
        vmid=306,
        payload={"vm_start_acknowledged": True},
        actor=actor,
    )
    ports = use_case_type.call_args.kwargs["ports"]
    assert ports.workloads is inventory
    assert ports.mutation_factory().redacted_connection_context() == {"mode": "test"}
