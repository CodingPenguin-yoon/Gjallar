from app.operations.recovery.application import (
    RecoveryBindingError, RecoveryRunResult, _pause_binding_failure, _validate_recovery_binding,
)
from app.operations.target_lock import get_target_operation_lock
from app.cloud_images.catalog import ImageError
from app.operations.vm_image_cleanup.domain import task_reference


class ImageCleanupRecoveryHandler:
    def __init__(self, *, operations, recovery, service_factory):
        self.operations, self.recovery, self.service_factory = operations, recovery, service_factory

    def handle(self, lease):
        operation = self.operations.get(lease.operation_id)
        if operation is None:
            raise RuntimeError("Image cleanup recovery Operation is missing")
        try:
            _validate_recovery_binding(lease, operation, recovery_kind="vm_image_cleanup_observation",
                operation_type="vm_image_cleanup", execution_mode="managed_api", target_lock_reader=get_target_operation_lock)
            if operation.details.get("proxmox_upid"):
                before = operation.details["observed_before"]
                try:
                    task_reference(operation.details["proxmox_upid"], node_id=operation.details["target"]["node_id"],
                        vmid=operation.details["target"]["vmid"], resource=before["resource"], storage=before["storage_id"])
                except ImageError:
                    raise RecoveryBindingError("image_cleanup_task_target_mismatch") from None
        except RecoveryBindingError as exc:
            return _pause_binding_failure(self.recovery, lease, operation, exc)
        if operation.status == "planned" and operation.details.get("mutation_dispatched") is False:
            self.recovery.commit_observation(lease, next_status="blocked", event_type="image_cleanup_interrupted_before_dispatch",
                stage="precheck", details_patch={"failure_code": "IMAGE_CLEANUP_INTERRUPTED_BEFORE_DISPATCH"},
                expected_statuses=["planned"], expected_operation_version=operation.version,
                expected_operation_checksum=operation.last_event_checksum, recovery_status="completed", release_target_lock=True)
            return RecoveryRunResult(operation.operation_id, "blocked")
        try:
            outcome = self.service_factory().verify(lease, operation)
        except ImageError as exc:
            self.recovery.commit_observation(lease, event_type="image_cleanup_recovery_unavailable", stage="reconciliation",
                expected_statuses=[operation.status], recovery_status="paused", error_code=exc.code)
            outcome = "paused"
        return RecoveryRunResult(operation.operation_id, outcome)
