"""Host observers never dispatch a replacement or a pending mutation stage."""
from app.operations.host_config.domain import HOST_SCOPE_TYPE, lock_binding
from app.operations.recovery.application import RecoveryRunResult
from app.operations.target_lock import get_target_operation_lock


class HostConfigurationRecoveryHandler:
    def __init__(self, *, operation_type, operations, recovery, service_factory, error_type):
        self.operation_type, self.operations, self.recovery = operation_type, operations, recovery
        self.service_factory, self.error_type = service_factory, error_type

    def handle(self, lease):
        operation = self.operations.get(lease.operation_id)
        if operation is None:
            raise RuntimeError('Host recovery Operation is missing')
        binding = lock_binding(operation_type=operation.operation_type,target_type=operation.target_type,
            target_id=operation.target_id,operation_details=operation.details,recovery_details=lease.item.details)
        held = get_target_operation_lock(operation.target_type,operation.target_id) if binding else None
        durable = held.get('durable', {}) if held else {}
        exact = (binding is not None and operation.operation_type == self.operation_type
            and operation.execution_mode == 'managed_api' and lease.item.recovery_kind == self.operation_type + '_observation'
            and held is not None and held.get('owner_id') == operation.operation_id
            and durable.get('operation_type') == self.operation_type and durable.get('owner_id') == operation.operation_id
            and held.get('lock_id') == binding['target_lock_id'] == durable.get('operation_lock_id')
            and durable.get('cluster_id') == binding['cluster_id'] and durable.get('scope_key') == binding['scope_key']
            and durable.get('target') == binding['target'] and durable.get('scope_type') == HOST_SCOPE_TYPE and durable.get('vmid') is None)
        if not exact or (operation.status == 'planned' and operation.details.get('mutation_dispatched') is not False):
            self.recovery.commit_observation(lease,event_type='host_recovery_binding_mismatch',stage='reconciliation',
                expected_statuses=[operation.status],expected_operation_version=operation.version,
                expected_operation_checksum=operation.last_event_checksum,recovery_status='paused',
                error_code='OPERATION_RECOVERY_BINDING_MISMATCH')
            return RecoveryRunResult(operation.operation_id,'paused')
        if operation.status == 'planned':
            self.recovery.commit_observation(lease,next_status='blocked',event_type='host_interrupted_before_dispatch',stage='precheck',
                expected_statuses=['planned'],expected_operation_version=operation.version,
                expected_operation_checksum=operation.last_event_checksum,recovery_status='completed',release_target_lock=True)
            return RecoveryRunResult(operation.operation_id,'blocked')
        try:
            outcome = self.service_factory().verify(lease,operation)
        except self.error_type as exc:
            self.recovery.commit_observation(lease,event_type='host_recovery_unavailable',stage='reconciliation',
                expected_statuses=[operation.status],expected_operation_version=operation.version,
                expected_operation_checksum=operation.last_event_checksum,recovery_status='paused',error_code=exc.code)
            outcome = 'paused'
        return RecoveryRunResult(operation.operation_id,outcome)
