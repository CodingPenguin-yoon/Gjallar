from app.operations.recovery.application import (
    RecoveryBindingError, RecoveryRunResult, _pause_binding_failure, _validate_recovery_binding,
)
from app.operations.core.domain import operation_digest
from app.operations.vm_image_build.infrastructure import task_reference
from app.operations.target_lock import get_target_operation_lock
from app.cloud_images.catalog import ImageError


class ImageBuildRecoveryHandler:
    def __init__(self, *, operations, recovery, service_factory):
        self.operations, self.recovery, self.service_factory = operations, recovery, service_factory

    def handle(self, lease):
        operation = self.operations.get(lease.operation_id)
        if operation is None:
            raise RuntimeError("ImageBuild recovery Operation is missing")
        try:
            _validate_recovery_binding(lease, operation, recovery_kind="vm_image_build_observation",
                operation_type="vm_image_build", execution_mode="managed_api", target_lock_reader=get_target_operation_lock)
            if operation.details.get('mutation_dispatched'):
                details = lease.item.details
                if any(details.get(key) != operation.details.get(key) for key in ('build_stage', 'stage_dispatch_state')):
                    raise RecoveryBindingError('image_build_stage_binding_mismatch')
                if details.get('stages_digest') != operation_digest(operation.details.get('stages', {})):
                    raise RecoveryBindingError('image_build_stage_evidence_mismatch')
                try:
                    for stage, evidence in operation.details.get('stages', {}).items():
                        kind = {'upload': 'imgcopy', 'create': 'qmcreate', 'template': 'qmtemplate'}.get(stage)
                        if not kind:
                            raise RecoveryBindingError('image_build_unknown_stage')
                        task_reference(evidence.get('upid'), node_id=operation.details['target']['node_id'],
                                       vmid='' if stage == 'upload' else operation.details['target']['vmid'], kind=kind)
                except ImageError:
                    raise RecoveryBindingError('image_build_task_binding_invalid') from None

        except RecoveryBindingError as exc:
            return _pause_binding_failure(self.recovery, lease, operation, exc)
        if operation.status == "planned" and operation.details.get("mutation_dispatched") is False:
            self.recovery.commit_observation(lease, next_status="blocked", event_type="image_build_interrupted_before_dispatch",
                stage="precheck", details_patch={"failure_code": "VM_IMAGE_BUILD_INTERRUPTED_BEFORE_DISPATCH"},
                expected_statuses=["planned"], expected_operation_version=operation.version,
                expected_operation_checksum=operation.last_event_checksum, recovery_status="completed", release_target_lock=True)
            return RecoveryRunResult(operation.operation_id, "blocked")
        try:
            outcome = self.service_factory().verify(lease, operation)
        except ImageError as exc:
            self.recovery.commit_observation(lease, event_type="image_build_recovery_unavailable", stage="reconciliation",
                expected_statuses=[operation.status], recovery_status="paused", error_code=exc.code)
            outcome = "paused"
        return RecoveryRunResult(operation.operation_id, outcome)
