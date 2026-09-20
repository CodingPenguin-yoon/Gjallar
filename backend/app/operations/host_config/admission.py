"""Atomically admit a non-VM host operation, lock, and recovery lease."""
from contextlib import contextmanager
from dataclasses import replace
import uuid
from app.db.session import session_scope
from app.operations.core.domain import OperationIntentConflict
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.host_config.domain import target_identity
from app.operations.host_config.infrastructure import ConfigurationLockRepository
from app.operations.recovery.domain import RecoverySpec
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore


class HostConfigurationAdmission:
    def prepare(self, spec, *, cluster_id):
        target = spec.details.get('target')
        expected_type, expected_id = target_identity(spec.operation_type, target)
        if (spec.target_type, spec.target_id, spec.execution_mode) != (expected_type, expected_id, 'managed_api'):
            raise ValueError('Host Operation target identity is not exact')
        with session_scope() as session:
            @contextmanager
            def shared():
                yield session
            # Take the same gate before the first idempotency read; competing identical
            # requests must see the committed operation without acquiring a second lock.
            from app.setup_integration.repository import lock_connection
            lock_connection(session)
            operations = SqlAlchemyOperationStore(sessions=shared)
            existing = operations.get(spec.operation_id)
            if existing is not None:
                if existing.intent_digest != spec.intent_digest:
                    raise OperationIntentConflict(spec.operation_id)
                return existing, None
            lock = ConfigurationLockRepository(sessions=shared).acquire(operation_type=spec.operation_type,
                cluster_id=cluster_id, owner_id=spec.operation_id, target=target)
            binding = {'target_lock_id': lock.lock_id, 'cluster_id': lock.cluster_id, 'scope_key': lock.scope_key,
                'target_type': spec.target_type, 'target_id': spec.target_id, 'target': dict(target),
                'operation_type': spec.operation_type, 'execution_mode': spec.execution_mode}
            operation = operations.create(replace(spec, details={**spec.details, **binding})).operation
            lease = SqlAlchemyRecoveryStore(sessions=shared).prepare_and_claim(
                RecoverySpec(spec.operation_id, spec.operation_type + '_observation', binding),
                lease_owner=spec.operation_type + ':' + uuid.uuid4().hex, lease_seconds=60)
            return operation, lease
