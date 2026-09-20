"""Checkpoint every upload/import/conversion; recovery never sends a mutation."""
from app.cloud_images.catalog import ImageError, image_by_id
from app.cloud_images.contracts import BuildRequest, upload_filename, validate_build
from app.cloud_images.download import verified_download
from app.operations.core.domain import OperationActor, OperationSpec, operation_digest
from app.operations.recovery.domain import RecoveryLease
from app.operations.vm_template.facade import conversion_matches


class ImageBuildService:
    def __init__(self, *, client, admission, operations, recovery, cluster_id, downloader=verified_download):
        self.client, self.admission, self.operations = client, admission, operations
        self.recovery, self.cluster_id, self.downloader = recovery, cluster_id, downloader

    def review(self, *, node_id, vmid, request):
        validate_build(node_id, vmid, request)
        target = {'node_id': node_id, 'vmid': vmid, 'name': request.name}
        evidence = self.client.preflight(node_id=node_id, vmid=vmid, request=request)
        digest = operation_digest({'target': target, 'configuration': evidence})
        return {'target': target, 'observed_before': evidence, 'review_digest': digest, 'warnings': [
            '고정 공식 이미지를 SHA-256 검증한 뒤 staging 업로드·새 VMID import·템플릿 전환을 수행합니다. 부팅하지 않습니다.',
            'Gjallar와 PVE 업로드 임시 공간, staging 파일과 10 GiB 가상 디스크가 필요합니다.',
            'PVE upload는 덮어쓰기를 허용합니다. 이 작업의 고유 staging 파일과 대상 VMID를 외부에서 동시에 변경하지 마세요.',
            '실패·응답 유실 시 부분 자원을 자동 재생성·삭제하지 않습니다. 단계와 잔여 자원을 확인하세요.',
            '제작 성공은 실제 배포 검증이 아닙니다. staging 원본은 보존되며 별도 테스트 배포와 명시적 정리가 필요합니다.']}

    def execute(self, *, node_id, vmid, request, actor):
        validate_build(node_id, vmid, request)
        identity = operation_digest({'cluster_id': self.cluster_id, 'node_id': node_id, 'vmid': vmid,
                                     'idempotency_key': request.idempotency_key})
        operation_id = 'vm-image-build-' + identity.split(':', 1)[1]
        target = {'node_id': node_id, 'vmid': vmid, 'name': request.name}
        intent_digest = operation_digest({'target': target, **request.model_dump()})
        existing = self.operations.get(operation_id)
        if existing:
            if existing.intent_digest != intent_digest:
                raise ImageError('IMAGE_BUILD_IDEMPOTENCY_CONFLICT', '같은 요청 ID에 다른 제작 입력을 사용할 수 없습니다.')
            return self.result(existing, replay=True)
        review = self.review(node_id=node_id, vmid=vmid, request=request)
        if review['review_digest'] != request.expected_review_digest:
            raise ImageError('IMAGE_BUILD_REVIEW_CHANGED', '검토한 이미지·연결·제작 대상이 변경됐습니다. 다시 검토하세요.')
        filename = upload_filename(vmid, operation_id)
        spec = OperationSpec(operation_id=operation_id, operation_type='vm_image_build', execution_mode='managed_api',
            target_type='proxmox_vm', target_id=f'vmid:{vmid}', idempotency_key=identity,
            intent_digest=intent_digest, plan_digest=intent_digest, actor=OperationActor.from_mapping(actor),
            details={'target': target, 'observed_before': review['observed_before'], 'requested': request.model_dump(),
                     'mutation_dispatched': False, 'build_stage': 'download', 'stages': {}, 'upload_filename': filename})
        operation, lease = self.admission.prepare(spec, cluster_id=self.cluster_id, vmid=vmid)
        if lease is None:
            return self.result(operation, replay=True)

        def heartbeat():
            nonlocal lease
            lease = self.recovery.heartbeat(lease, lease_seconds=60)

        def checkpoint(*, stage, patch, next_status=None):
            nonlocal operation, lease
            recovery_patch = {key: patch[key] for key in ('build_stage', 'stage_dispatch_state') if key in patch}
            if 'proxmox_upid' in patch:
                recovery_patch['upid'] = patch['proxmox_upid']
            if 'stages' in patch:
                recovery_patch['stages_digest'] = operation_digest(patch['stages'])
            operation, item = self.recovery.commit_observation(lease, next_status=next_status, event_type='image_build_' + stage,
                stage=stage, details_patch=patch, recovery_details_patch=recovery_patch, expected_statuses=[operation.status],
                expected_operation_version=operation.version, expected_operation_checksum=operation.last_event_checksum,
                recovery_status='leased')
            lease = RecoveryLease(item=item, token=lease.token)

        def dispatch_stage(stage, action):
            checkpoint(stage=stage + '_dispatching', next_status='dispatching' if operation.status == 'planned' else None,
                       patch={'mutation_dispatched': True, 'build_stage': stage, 'stage_dispatch_state': 'dispatching', 'proxmox_upid': None,
                              'stages': operation.details['stages']})
            upid = action()
            stages = {**operation.details['stages'], stage: {'upid': upid}}
            checkpoint(stage=stage + '_task_bound', next_status='running' if operation.status == 'dispatching' else None,
                       patch={'stages': stages, 'proxmox_upid': upid, 'stage_dispatch_state': 'task_bound'})
            task = self.client.task(node_id=node_id, upid=upid, heartbeat=heartbeat)
            if task['status'] != 'stopped' or task['exitstatus'] != 'OK':
                raise ImageError('IMAGE_BUILD_TASK_UNCONFIRMED', '제작 단계가 완료되지 않았습니다. 다음 mutation을 시작하지 않습니다.')
            stages = {**operation.details['stages'], stage: {'upid': upid, 'task': task}}
            checkpoint(stage=stage + '_task_complete', patch={'stages': stages, 'stage_dispatch_state': 'task_complete'})

        try:
            with self.downloader(request.image_id, heartbeat=heartbeat) as (file, source):
                fresh = self.review(node_id=node_id, vmid=vmid, request=request)
                if fresh['review_digest'] != request.expected_review_digest:
                    raise ImageError('IMAGE_BUILD_REVIEW_CHANGED', '다운로드 후 연결·제작 검토 조건이 변경됐습니다.')
                self.client.assert_upload_absent(node_id=node_id, vmid=vmid, storage=request.staging_storage_id, filename=filename)
                checkpoint(stage='download_verified', patch={'source_integrity': source})
                dispatch_stage('upload', lambda: self.client.upload(node_id=node_id, vmid=vmid, request=request,
                    operation_id=operation_id, file=file, heartbeat=heartbeat))
            staging = self.client.observe_staging(node_id=node_id, vmid=vmid, request=request, operation_id=operation_id)
            checkpoint(stage='upload_verified', patch={'staging': staging})
            # Recheck VMID absence and allocation conditions after the potentially long upload.
            self.client.preflight(node_id=node_id, vmid=vmid, request=request)
            dispatch_stage('create', lambda: self.client.create(node_id=node_id, vmid=vmid, request=request, operation_id=operation_id))
            prepared = self.client.observe_vm(node_id=node_id, vmid=vmid, request=request, operation_id=operation_id)
            checkpoint(stage='created_vm_verified', patch={'prepared_vm': prepared})
            # Conversion has no PVE digest parameter: repeat the prepared observation immediately before dispatch.
            latest = self.client.observe_vm(node_id=node_id, vmid=vmid, request=request, operation_id=operation_id)
            if latest['digest'] != prepared['digest'] or latest['resources_digest'] != prepared['resources_digest']:
                raise ImageError('IMAGE_BUILD_PREPARED_CHANGED', '전환 직전 VM 또는 volume이 변경됐습니다.')
            dispatch_stage('template', lambda: self.client.convert(node_id=node_id, vmid=vmid))
            self.verify(lease, operation)
        except ImageError as exc:
            if not operation.details.get('mutation_dispatched'):
                self.recovery.commit_observation(lease, next_status='blocked', event_type='image_build_precheck_blocked', stage='precheck',
                    details_patch={'failure_code': exc.code}, expected_statuses=['planned'], recovery_status='completed', release_target_lock=True)
                raise ImageError(exc.code, str(exc), exc.status_code, {'operation_id': operation_id}) from None
            self.pause(lease, operation, exc.code)
        return self.result(self.operations.get(operation_id))

    def pause(self, lease, operation, code, **evidence):
        self.recovery.commit_observation(lease,
            next_status=None if operation.status == 'needs_reconciliation' else 'needs_reconciliation',
            event_type='image_build_result_unconfirmed', stage='reconciliation',
            details_patch={'failure_code': code, **evidence}, expected_statuses=[operation.status],
            expected_operation_version=operation.version, expected_operation_checksum=operation.last_event_checksum,
            recovery_status='paused', error_code=code)
        return 'paused'

    def verify(self, lease, operation):
        target = operation.details['target']
        stages = operation.details.get('stages', {})
        stage = operation.details.get('build_stage')
        latest = stages.get(stage, {})
        if operation.details.get('stage_dispatch_state') == 'dispatching' or not latest.get('upid'):
            return self.pause(lease, operation, 'IMAGE_BUILD_TASK_REFERENCE_MISSING')
        try:
            task = self.client.task(node_id=target['node_id'], upid=latest['upid'])
            if task['status'] in {'running', 'queued'}:
                self.recovery.commit_observation(lease, event_type='image_build_task_running', stage=stage,
                    details_patch={'task': task}, expected_statuses=[operation.status], recovery_status='retry_wait', retry_delay_seconds=5)
                return 'retry_wait'
            if task['status'] != 'stopped' or task['exitstatus'] != 'OK':
                return self.pause(lease, operation, 'IMAGE_BUILD_TASK_UNCONFIRMED', task=task)
            request = BuildRequest.model_validate(operation.details['requested'])
            if stage != 'template':
                evidence = {'task': task, 'completed_stage': stage, 'next_stage_dispatched': False}
                if stage == 'upload':
                    evidence['staging'] = self.client.observe_staging(node_id=target['node_id'], vmid=target['vmid'], request=request, operation_id=operation.operation_id)
                if stage == 'create':
                    evidence['prepared_vm'] = self.client.observe_vm(node_id=target['node_id'], vmid=target['vmid'], request=request, operation_id=operation.operation_id)
                return self.pause(lease, operation, 'IMAGE_BUILD_NEXT_STAGE_NOT_DISPATCHED', **evidence)
            if any(stages.get(name, {}).get('task', {}).get('exitstatus') != 'OK' or stages.get(name, {}).get('task', {}).get('status') != 'stopped' for name in ('upload', 'create')):
                return self.pause(lease, operation, 'IMAGE_BUILD_STAGE_EVIDENCE_MISSING')
            image = image_by_id(request.image_id)
            source = operation.details.get('source_integrity', {})
            if source != {'image_id': image.image_id, 'sha256': image.sha256, 'download_bytes': image.download_bytes, 'virtual_size_bytes': image.virtual_size_bytes}:
                return self.pause(lease, operation, 'IMAGE_BUILD_SOURCE_EVIDENCE_MISSING')
            staging = self.client.observe_staging(node_id=target['node_id'], vmid=target['vmid'], request=request, operation_id=operation.operation_id)
            after = self.client.observe_vm(node_id=target['node_id'], vmid=target['vmid'], request=request,
                                           operation_id=operation.operation_id, converted=True)
        except ImageError as exc:
            return self.pause(lease, operation, exc.code)
        prepared = operation.details.get('prepared_vm')
        if not prepared or not conversion_matches(prepared, after):
            return self.pause(lease, operation, 'IMAGE_BUILD_RESULT_UNCONFIRMED', observed_after=after)
        if operation.status != 'verifying':
            operation, item = self.recovery.commit_observation(lease, next_status='verifying', event_type='image_build_observed', stage='post_check',
                details_patch={'observed_after': after, 'staging': staging, 'task': task}, expected_statuses=[operation.status],
                recovery_status='leased')
            lease = RecoveryLease(item=item, token=lease.token)
        self.recovery.commit_observation(lease, next_status='succeeded', event_type='image_build_verified', stage='completed',
            details_patch={'failure_code': None}, expected_statuses=['verifying'], recovery_status='completed', release_target_lock=True)
        return 'succeeded'

    @staticmethod
    def result(operation, replay=False):
        return {'operation_id': operation.operation_id, 'status': operation.status,
                'operation': {'operation_id': operation.operation_id, 'status': operation.status},
                **{key: operation.details.get(key) for key in ('target', 'observed_before', 'observed_after', 'requested',
                    'build_stage', 'stage_dispatch_state', 'stages', 'task', 'staging', 'prepared_vm', 'source_integrity', 'failure_code')},
                'idempotent_replay': replay, 'automatic_retry_allowed': False}
