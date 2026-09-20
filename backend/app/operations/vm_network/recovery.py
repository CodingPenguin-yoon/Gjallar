"""GET-only network recovery. Missing dispatch acknowledgements remain paused."""
from app.operations.recovery.application import (
    RecoveryBindingError, RecoveryRunResult, _pause_binding_failure, _validate_recovery_binding,
)
from app.operations.target_lock import get_target_operation_lock
from app.operations.vm_network.domain import NetworkError


class NetworkRecoveryHandler:
    def __init__(self, *, operations, recovery, service_factory):
        self.operations, self.recovery, self.service_factory = operations, recovery, service_factory

    def handle(self, lease):
        operation = self.operations.get(lease.operation_id)
        if operation is None:
            raise RuntimeError("Network recovery Operation is missing")
        try:
            _validate_recovery_binding(lease, operation, recovery_kind="vm_network_observation",
                operation_type="vm_network", execution_mode="managed_api", target_lock_reader=get_target_operation_lock)
        except RecoveryBindingError as exc:
            return _pause_binding_failure(self.recovery, lease, operation, exc)
        if operation.status == "planned" and operation.details.get("mutation_dispatched") is False:
            self.recovery.commit_observation(
                lease, next_status="blocked", event_type="network_interrupted_before_dispatch", stage="precheck",
                details_patch={"failure_code": "VM_NETWORK_INTERRUPTED_BEFORE_DISPATCH"},
                expected_statuses=["planned"], expected_operation_version=operation.version,
                expected_operation_checksum=operation.last_event_checksum,
                recovery_status="completed", release_target_lock=True,
            )
            return RecoveryRunResult(operation.operation_id, "blocked")
        try:
            outcome = self.service_factory().verify(lease, operation)
        except NetworkError as exc:
            self.recovery.commit_observation(lease, event_type="network_recovery_unavailable", stage="reconciliation",
                expected_statuses=[operation.status], recovery_status="paused", error_code=exc.code)
            outcome = "paused"
        return RecoveryRunResult(operation.operation_id, outcome)
