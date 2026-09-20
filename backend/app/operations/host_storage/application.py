"""Review, durable admission, one config write, and GET-only verification."""
from app.operations.core.domain import OperationActor, OperationSpec, operation_digest
from app.operations.recovery.domain import RecoveryLease
from app.operations.host_storage.domain import StorageChange, StorageError, make_review, validate_target


class StorageService:
    def __init__(self, *, client, admission, operations, recovery, cluster_id):
        self.client, self.admission = client, admission
        self.operations, self.recovery, self.cluster_id = operations, recovery, cluster_id

    def review(self, *, node_id, storage_id, change):
        validate_target(node_id,storage_id)
        self.client.check_permissions(storage_id=storage_id)
        config = self.client.read(node_id=node_id,storage_id=storage_id)
        return make_review(node_id=node_id,storage_id=storage_id,change=change,config=config)

    @staticmethod
    def check_expected(plan, request):
        if plan['review_digest'] != request.expected_review_digest:
            raise StorageError('HOST_STORAGE_STATE_CHANGED', '검토 후 설정이 변경됐습니다. 다시 조회·검토하세요.')
        if request.confirmation != plan['confirmation']:
            raise StorageError('HOST_STORAGE_CONFIRMATION_INVALID', '노드/storage/작업 종류를 정확히 입력하세요.', 422)

    def execute(self, *, node_id, storage_id, request, actor):
        target_type,target_id = validate_target(node_id,storage_id)
        target = {'node_id':node_id,'storage_id':storage_id}
        identity = operation_digest({'cluster_id':self.cluster_id,'target':target,'key':request.idempotency_key})
        operation_id = 'host-storage-' + identity.split(':')[1]
        intent_digest = operation_digest({'target':target,'request':request.model_dump()})
        existing = self.operations.get(operation_id)
        if existing is not None:
            if existing.intent_digest != intent_digest:
                raise StorageError('HOST_STORAGE_IDEMPOTENCY_CONFLICT', '같은 요청 ID에 다른 변경을 사용할 수 없습니다.')
            return self.result(existing,replay=True)
        change = StorageChange.model_validate({key:getattr(request,key) for key in StorageChange.model_fields})
        plan = self.review(node_id=node_id,storage_id=storage_id,change=change)
        self.check_expected(plan,request)
        spec = OperationSpec(operation_id=operation_id,operation_type='host_storage',execution_mode='managed_api',
            target_type=target_type,target_id=target_id,idempotency_key=identity,intent_digest=intent_digest,
            plan_digest=plan['review_digest'],actor=OperationActor.from_mapping(actor),
            details={'target':target,'requested':request.model_dump(),'review':plan,
                     'mutation_dispatched':False,'dispatch_acknowledged':False})
        operation,lease = self.admission.prepare(spec,cluster_id=self.cluster_id)
        if lease is None:
            return self.result(operation,replay=True)
        try:
            self.check_expected(self.review(node_id=node_id,storage_id=storage_id,change=change),request)
        except StorageError as exc:
            self.recovery.commit_observation(lease,next_status='blocked',event_type='storage_precheck_blocked',stage='precheck',
                details_patch={'failure_code':exc.code},expected_statuses=['planned'],recovery_status='completed',release_target_lock=True)
            raise StorageError(exc.code,str(exc),exc.status_code,{'operation_id':operation_id}) from None
        operation,item = self.recovery.commit_observation(lease,next_status='dispatching',event_type='storage_dispatching',stage='dispatch',
            details_patch={'mutation_dispatched':True},expected_statuses=['planned'],recovery_status='leased')
        lease = RecoveryLease(item=item,token=lease.token)
        try:
            self.client.apply(node_id=node_id,storage_id=storage_id,change=change,before=plan['observed_before'])
        except StorageError as exc:
            operation,_ = self.recovery.commit_observation(lease,next_status='needs_reconciliation',event_type='storage_dispatch_unknown',
                stage='reconciliation',details_patch={'failure_code':exc.code},expected_statuses=['dispatching'],
                recovery_status='paused',error_code=exc.code)
            return self.result(operation)
        operation,item = self.recovery.commit_observation(lease,next_status='running',event_type='storage_dispatch_acknowledged',stage='post_check',
            details_patch={'dispatch_acknowledged':True},expected_statuses=['dispatching'],recovery_status='leased')
        self.verify(RecoveryLease(item=item,token=lease.token),operation)
        return self.result(self.operations.get(operation_id))

    @staticmethod
    def matches(observed, review):
        config = observed['configuration']
        before = review['observed_before']
        return (all(config.get(key) == value for key,value in review['desired'].items())
                and (before is None or config['preserved_fingerprint'] == before['preserved_fingerprint'])
                and (not config['enabled'] or observed['activation_checked'] is True and observed['active'] is True))

    def verify(self, lease, operation):
        target = operation.details['target']
        observed,error_code = None,None
        try:
            observed = self.client.observe(**target)
        except StorageError as exc:
            error_code = exc.code
        if (operation.details.get('dispatch_acknowledged') is not True or observed is None
                or not self.matches(observed,operation.details['review'])):
            self.recovery.commit_observation(lease,next_status=None if operation.status == 'needs_reconciliation' else 'needs_reconciliation',
                event_type='storage_result_unconfirmed',stage='reconciliation',
                details_patch={'observed_after':observed,'failure_code':error_code or 'HOST_STORAGE_RESULT_UNCONFIRMED'},
                expected_statuses=[operation.status],expected_operation_version=operation.version,
                expected_operation_checksum=operation.last_event_checksum,recovery_status='paused',
                error_code=error_code or 'HOST_STORAGE_RESULT_UNCONFIRMED')
            return 'paused'
        if operation.status != 'verifying':
            operation,item = self.recovery.commit_observation(lease,next_status='verifying',event_type='storage_state_observed',stage='post_check',
                details_patch={'observed_after':observed},expected_statuses=[operation.status],expected_operation_version=operation.version,
                expected_operation_checksum=operation.last_event_checksum,recovery_status='leased')
            lease = RecoveryLease(item=item,token=lease.token)
        self.recovery.commit_observation(lease,next_status='succeeded',event_type='storage_verified',stage='completed',
            details_patch={'observed_after':observed,'failure_code':None},expected_statuses=['verifying'],
            expected_operation_version=operation.version,expected_operation_checksum=operation.last_event_checksum,
            recovery_status='completed',release_target_lock=True)
        return 'succeeded'

    @staticmethod
    def result(operation,replay=False):
        return {'operation_id':operation.operation_id,'status':operation.status,'target':operation.details['target'],
            'operation':{'operation_id':operation.operation_id,'status':operation.status},
            'requested':operation.details['requested'],'review':operation.details['review'],
            'observed_after':operation.details.get('observed_after'),'failure_code':operation.details.get('failure_code'),
            'idempotent_replay':replay,'automatic_retry_allowed':False}
