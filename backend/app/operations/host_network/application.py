"""Durable bridge stage/reload with observation-only recovery at every interruption."""
from app.operations.core.domain import OperationActor, OperationSpec, operation_digest
from app.operations.host_network.domain import (
    BridgeChange, BridgeError, make_review, observe_configuration, task_reference, validate_target,
)
from app.operations.recovery.domain import RecoveryLease


class BridgeService:
    def __init__(self, *, client, admission, operations, recovery, cluster_id):
        self.client = client
        self.admission = admission
        self.operations = operations
        self.recovery = recovery
        self.cluster_id = cluster_id

    def review(self, *, node_id, bridge_id, change):
        validate_target(node_id, bridge_id)
        self.client.check_permissions(node_id=node_id)
        return make_review(node_id=node_id, bridge_id=bridge_id, change=change,
                           snapshot=self.client.read(node_id=node_id))

    @staticmethod
    def check_expected(review, request):
        if review['review_digest'] != request.expected_review_digest:
            raise BridgeError('HOST_NETWORK_STATE_CHANGED', '검토 후 네트워크 설정이 변경됐습니다. 다시 검토하세요.')
        if review['confirmation'] != request.confirmation:
            raise BridgeError('HOST_NETWORK_CONFIRMATION_INVALID', '노드/bridge/작업 종류를 정확히 입력하세요.', 422)

    def checkpoint(self, lease, operation, *, event, stage, patch=None, recovery_patch=None, next_status=None):
        operation, item = self.recovery.commit_observation(
            lease, next_status=next_status, event_type=event, stage=stage,
            details_patch=patch or {}, recovery_details_patch=recovery_patch or {},
            expected_statuses=[operation.status], expected_operation_version=operation.version,
            expected_operation_checksum=operation.last_event_checksum, recovery_status='leased')
        return operation, RecoveryLease(item=item, token=lease.token)

    def pause(self, lease, operation, code, **evidence):
        self.recovery.commit_observation(
            lease, next_status=None if operation.status == 'needs_reconciliation' else 'needs_reconciliation',
            event_type='host_network_result_unconfirmed', stage='reconciliation',
            details_patch={'failure_code': code, **evidence}, expected_statuses=[operation.status],
            expected_operation_version=operation.version, expected_operation_checksum=operation.last_event_checksum,
            recovery_status='paused', error_code=code)
        return 'paused'

    def execute(self, *, node_id, bridge_id, request, actor):
        target_type, target_id = validate_target(node_id, bridge_id)
        target = {'node_id': node_id, 'bridge_id': bridge_id}
        identity = operation_digest({'cluster_id': self.cluster_id, 'target': target, 'key': request.idempotency_key})
        operation_id = 'host-network-' + identity.split(':')[1]
        intent_digest = operation_digest({'target': target, 'request': request.model_dump()})
        existing = self.operations.get(operation_id)
        if existing is not None:
            if existing.intent_digest != intent_digest:
                raise BridgeError('HOST_NETWORK_IDEMPOTENCY_CONFLICT', '같은 요청 ID에 다른 변경을 사용할 수 없습니다.')
            return self.result(existing, replay=True)
        change = BridgeChange.model_validate({key: getattr(request, key) for key in BridgeChange.model_fields})
        plan = self.review(node_id=node_id, bridge_id=bridge_id, change=change)
        self.check_expected(plan, request)
        spec = OperationSpec(operation_id=operation_id, operation_type='host_network', execution_mode='managed_api',
            target_type=target_type, target_id=target_id, idempotency_key=identity, intent_digest=intent_digest,
            plan_digest=plan['review_digest'], actor=OperationActor.from_mapping(actor),
            details={'target': target, 'requested': request.model_dump(), 'review': plan,
                     'mutation_dispatched': False, 'stage_acknowledged': False, 'reload_dispatched': False})
        operation, lease = self.admission.prepare(spec, cluster_id=self.cluster_id)
        if lease is None:
            return self.result(operation, replay=True)
        try:
            self.check_expected(self.review(node_id=node_id, bridge_id=bridge_id, change=change), request)
        except BridgeError as exc:
            self.recovery.commit_observation(lease, next_status='blocked', event_type='host_network_precheck_blocked',
                stage='precheck', details_patch={'failure_code': exc.code}, expected_statuses=['planned'],
                recovery_status='completed', release_target_lock=True)
            raise BridgeError(exc.code, str(exc), exc.status_code, {'operation_id': operation_id}) from None
        operation, lease = self.checkpoint(lease, operation, event='host_network_stage_dispatching',
            stage='stage', next_status='dispatching', patch={'mutation_dispatched': True})
        try:
            self.client.stage(node_id=node_id, bridge_id=bridge_id, change=change)
        except BridgeError as exc:
            self.pause(lease, operation, exc.code)
            return self.result(self.operations.get(operation_id))
        operation, lease = self.checkpoint(lease, operation, event='host_network_stage_acknowledged',
            stage='stage', patch={'stage_acknowledged': True})
        try:
            staged = observe_configuration(snapshot=self.client.read(node_id=node_id), review=plan, staged=True)
        except BridgeError as exc:
            self.pause(lease, operation, exc.code)
            return self.result(self.operations.get(operation_id))
        operation, lease = self.checkpoint(lease, operation, event='host_network_stage_verified',
            stage='reload_precheck', patch={'staged_observation': staged})
        # Reobserve after committing the checkpoint; no pending data is cached across dispatch.
        try:
            latest = observe_configuration(snapshot=self.client.read(node_id=node_id), review=plan, staged=True)
            if latest['configuration']['preserved_fingerprint'] != staged['configuration']['preserved_fingerprint']:
                raise BridgeError('HOST_NETWORK_CONFIGURATION_CHANGED', '저장 검증 이후 bridge 설정이 변경됐습니다.')
        except BridgeError as exc:
            self.pause(lease, operation, exc.code)
            return self.result(self.operations.get(operation_id))
        operation, lease = self.checkpoint(lease, operation, event='host_network_reload_dispatching',
            stage='reload', patch={'reload_dispatched': True})
        try:
            upid = self.client.reload(node_id=node_id)
        except BridgeError as exc:
            self.pause(lease, operation, exc.code)
            return self.result(self.operations.get(operation_id))
        operation, lease = self.checkpoint(lease, operation, event='host_network_reload_task_bound',
            stage='task', next_status='running', patch={'proxmox_upid': upid}, recovery_patch={'upid': upid})

        def heartbeat():
            nonlocal lease
            lease = self.recovery.heartbeat(lease, lease_seconds=60)

        try:
            task = self.client.task(node_id=node_id, upid=upid, heartbeat=heartbeat)
        except BridgeError as exc:
            self.pause(lease, operation, exc.code)
        else:
            self.verify(lease, operation, task=task)
        return self.result(self.operations.get(operation_id))

    def verify(self, lease, operation, task=None):
        """No writes to Proxmox, including when only the staged config exists."""
        target = operation.details['target']
        upid = operation.details.get('proxmox_upid')
        if (operation.details.get('stage_acknowledged') is not True
                or operation.details.get('reload_dispatched') is not True or not upid):
            # A saved stage is useful evidence, but is never permission to dispatch reload.
            try:
                staged = observe_configuration(snapshot=self.client.read(node_id=target['node_id']),
                    review=operation.details['review'], staged=True)
            except BridgeError as exc:
                return self.pause(lease, operation, exc.code)
            return self.pause(lease, operation, 'HOST_NETWORK_RELOAD_REFERENCE_MISSING', staged_observation=staged)
        if upid != lease.item.details.get('upid'):
            return self.pause(lease, operation, 'HOST_NETWORK_TASK_BINDING_MISMATCH')
        try:
            task_reference(upid, node_id=target['node_id'])
            task = task or self.client.task(node_id=target['node_id'], upid=upid)
            if task['status'] in {'running', 'queued'}:
                self.recovery.commit_observation(lease, event_type='host_network_reload_running', stage='task',
                    details_patch={'task': task}, expected_statuses=[operation.status],
                    expected_operation_version=operation.version, expected_operation_checksum=operation.last_event_checksum,
                    recovery_status='retry_wait', retry_delay_seconds=5)
                return 'retry_wait'
            if task['status'] != 'stopped' or task['exitstatus'] != 'OK':
                return self.pause(lease, operation, 'HOST_NETWORK_RELOAD_FAILED', task=task)
            observed = observe_configuration(snapshot=self.client.read(node_id=target['node_id']),
                review=operation.details['review'], staged=False)
            original = operation.details.get('staged_observation', {}).get('configuration', {})
            if observed['configuration']['preserved_fingerprint'] != original.get('preserved_fingerprint'):
                raise BridgeError('HOST_NETWORK_CONFIGURATION_CHANGED', '반영 전후 bridge 보존 설정이 다릅니다.')
        except BridgeError as exc:
            return self.pause(lease, operation, exc.code)
        if operation.status != 'verifying':
            operation, lease = self.checkpoint(lease, operation, event='host_network_state_observed',
                stage='post_check', next_status='verifying', patch={'observed_after': observed, 'task': task})
        self.recovery.commit_observation(lease, next_status='succeeded', event_type='host_network_verified',
            stage='completed', details_patch={'observed_after': observed, 'task': task, 'failure_code': None},
            expected_statuses=['verifying'], expected_operation_version=operation.version,
            expected_operation_checksum=operation.last_event_checksum, recovery_status='completed', release_target_lock=True)
        return 'succeeded'

    @staticmethod
    def result(operation, replay=False):
        return {'operation_id': operation.operation_id, 'status': operation.status,
            'operation': {'operation_id': operation.operation_id, 'status': operation.status},
            'target': operation.details['target'], 'requested': operation.details['requested'],
            'review': operation.details['review'], 'staged_observation': operation.details.get('staged_observation'),
            'observed_after': operation.details.get('observed_after'), 'task': operation.details.get('task'),
            'failure_code': operation.details.get('failure_code'), 'idempotent_replay': replay,
            'automatic_retry_allowed': False}
