"""Explicit NFS backup review, with source/server-bound persistent intent."""
import re
from urllib.parse import urlencode
from . import resource_review
from .errors import ClientError
from .workflows import identifier, request_identity, segment


def show(app, *, vmid, node, storage, review=False):
    identifier(node); identifier(storage)
    if type(vmid) is not int or not 100 <= vmid <= 999999999:
        raise ClientError('INVALID_VMID', 'VMID를 확인하세요.', 2)
    suffix = 'backup-review' if review else 'backups'
    return app.request(f'nodes/{segment(node)}/vms/{vmid}/{suffix}?' + urlencode({'storage': storage}), **({'operator': True} if review else {}))


def validate(payload):
    fields = {'storage_id','idempotency_key','expected_name','expected_review_digest','confirmation','backup_acknowledged'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ClientError('INVALID_REVIEW','백업 검토 필드를 확인하세요.',2)
    request_identity(payload['idempotency_key']); identifier(payload['storage_id'])
    name, digest, confirmation = payload['expected_name'], payload['expected_review_digest'], payload['confirmation']
    if (not isinstance(name,str) or not 1 <= len(name) <= 255 or not isinstance(digest,str) or not re.fullmatch(r'sha256:[a-f0-9]{64}',digest)
            or not isinstance(confirmation,str) or not re.fullmatch(r'[1-9][0-9]{2,8}/'+re.escape(name),confirmation)
            or payload['backup_acknowledged'] is not True):
        raise ClientError('BACKUP_CONFIRMATION_REQUIRED','VMID/이름과 백업 영향을 확인하세요.',2)


def plan(app, *, vmid, node, storage, confirmation, backup_acknowledged, request_id, review_file):
    result = show(app, vmid=vmid, node=node, storage=storage, review=True)
    review = result['data']; before = review.get('observed_before', {})
    if review.get('target') != {'node_id':node,'vmid':vmid} or before.get('storage_id') != storage:
        raise ClientError('TARGET_CHANGED','검토한 VM·storage가 선택 대상과 다릅니다.',8)
    payload = {'storage_id':storage,'idempotency_key':request_id,'expected_name':before.get('name'),
        'expected_review_digest':before.get('review_digest'),'confirmation':confirmation,'backup_acknowledged':backup_acknowledged}
    validate(payload)
    if confirmation != f"{vmid}/{before['name']}": raise ClientError('BACKUP_CONFIRMATION_REQUIRED','조회한 VMID/이름을 입력하세요.',2)
    resource_review.save(app,schema='gjallar.cli.backup.v1',review=review,payload=payload,path=review_file)
    return {**result,'review_file':str(review_file),'exit_code':0,'message':'백업 검토를 저장했습니다. 공간·IO 영향과 기존 파일 보존을 확인하세요. 아직 실행하지 않았습니다.',
        'next':'gjallar vm backup execute --review-file <파일>'}


def execute(app, review_file, confirm):
    return resource_review.execute(app,review_file,confirm,schema='gjallar.cli.backup.v1',validate=validate,
        action='backup',operation_type='vm_backup',label='정지 VM의 새 NFS 백업 생성 (기존 백업 보존·IO/공간 사용)')
