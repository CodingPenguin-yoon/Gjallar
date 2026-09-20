"""Configuration locks share the existing credential/admission transaction gate."""
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.db.models import OperationLockRecord
from app.db.session import session_scope
from app.operations.locks.domain import DurableTargetLockBusy, OPEN_TARGET_LOCK_STATUSES
from app.operations.host_config.domain import HOST_SCOPE_TYPE, configuration_scope_key, target_identity


@dataclass(frozen=True)
class ConfigurationLock:
    lock_id: str
    operation_type: str
    cluster_id: str
    owner_id: str
    scope_key: str
    status: str
    target_type: str
    target_id: str
    target: dict

    def to_dict(self):
        return {'operation_lock_id': self.lock_id, 'operation_type': self.operation_type, 'cluster_id': self.cluster_id,
            'owner_id': self.owner_id, 'scope_type': HOST_SCOPE_TYPE, 'scope_key': self.scope_key, 'status': self.status,
            'vmid': None, 'target_type': self.target_type, 'target_id': self.target_id, 'target': self.target}


def _lock(row):
    evidence = row.evidence or {}
    return ConfigurationLock(row.operation_lock_id, row.operation_type, row.cluster_id, row.owner_id, row.scope_key,
        row.status, evidence.get('target_type'), evidence.get('target_id'), evidence.get('target', {}))


class ConfigurationLockRepository:
    def __init__(self, *, sessions=session_scope):
        self.sessions = sessions

    def current(self, *, cluster_id):
        with self.sessions() as session:
            row = session.scalar(select(OperationLockRecord).where(OperationLockRecord.scope_type == HOST_SCOPE_TYPE,
                OperationLockRecord.scope_key == configuration_scope_key(cluster_id), OperationLockRecord.status.in_(OPEN_TARGET_LOCK_STATUSES)))
            return _lock(row) if row is not None else None

    def acquire(self, *, operation_type, cluster_id, owner_id, target):
        target_type, target_id = target_identity(operation_type, target)
        scope_key = configuration_scope_key(cluster_id)
        cluster_id = cluster_id.strip()
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise ValueError('Host lock owner is required')
        with self.sessions() as session:
            from app.setup_integration.contracts import SetupError
            from app.setup_integration.runtime import admit_host_mutation
            try:
                admit_host_mutation(session, cluster_id=cluster_id, operation_type=operation_type, target=target)
            except SetupError as exc:
                raise DurableTargetLockBusy(scope_key=scope_key, existing={'reason': exc.code}) from None
            # The shared admission gate remains held until lock + Operation + recovery commit.
            existing = session.scalar(select(OperationLockRecord).where(OperationLockRecord.cluster_id == cluster_id,
                OperationLockRecord.status.in_(OPEN_TARGET_LOCK_STATUSES)).order_by(OperationLockRecord.operation_lock_id))
            if existing is not None:
                raise DurableTargetLockBusy(scope_key=scope_key, existing={'reason': 'HOST_CONFIGURATION_TARGET_BUSY',
                    'owner_id': existing.owner_id, 'scope_type': existing.scope_type})
            now = datetime.now(timezone.utc)
            row = OperationLockRecord(operation_lock_id='configuration-lock-' + uuid.uuid4().hex,
                operation_type=operation_type, scope_type=HOST_SCOPE_TYPE, scope_key=scope_key, status='active',
                cluster_id=cluster_id, vmid=None, owner_id=owner_id.strip(), reason='host_configuration_dispatch',
                evidence={'operation_id': owner_id.strip(), 'target_type': target_type, 'target_id': target_id, 'target': dict(target)},
                created_at=now, updated_at=now)
            try:
                with session.begin_nested():
                    session.add(row)
                    session.flush()
            except IntegrityError as exc:
                raise DurableTargetLockBusy(scope_key=scope_key, existing={'reason': 'HOST_CONFIGURATION_TARGET_BUSY'}) from exc
            return _lock(row)
