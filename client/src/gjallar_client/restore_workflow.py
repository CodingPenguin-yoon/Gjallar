"""Review an isolated restore to a separate VMID, then explicitly dispatch once."""
import re
from urllib.parse import urlencode
from . import resource_review
from .errors import ClientError
from .workflows import identifier, request_identity, segment

ARCHIVE = r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}:backup/vzdump-qemu-([1-9][0-9]{2,8})-\d{4}_\d{2}_\d{2}-\d{2}_\d{2}_\d{2}\.vma(?:\.(?:zst|gz|lzo))?'


def validate(payload):
    fields={'archive','new_vmid','name','storage_id','bridge_id','idempotency_key','expected_name','expected_review_digest','confirmation','isolation_acknowledged'}
    if not isinstance(payload,dict) or set(payload)!=fields:
        raise ClientError('INVALID_REVIEW','복원 검토 필드를 확인하세요.',2)
    request_identity(payload['idempotency_key']);identifier(payload['storage_id']);identifier(payload['bridge_id'])
    archive=re.fullmatch(ARCHIVE,payload['archive']) if isinstance(payload['archive'],str) else None
    if (not archive or type(payload['new_vmid']) is not int or not 100<=payload['new_vmid']<=999999999
            or int(archive[1])==payload['new_vmid'] or not isinstance(payload['name'],str)
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,62}',payload['name'])
            or not isinstance(payload['expected_name'],str) or not 1<=len(payload['expected_name'])<=255
            or not isinstance(payload['expected_review_digest'],str) or not re.fullmatch(r'sha256:[a-f0-9]{64}',payload['expected_review_digest'])):
        raise ClientError('INVALID_REVIEW','원본 archive·새 VMID·이름·변경 감지값을 확인하세요.',2)
    if payload['isolation_acknowledged'] is not True or payload['confirmation']!=f"{archive[1]}/{payload['new_vmid']}/{payload['name']}":
        raise ClientError('RESTORE_CONFIRMATION_REQUIRED','원본/새 VMID/이름과 네트워크 격리 영향을 확인하세요.',2)


def plan(app, *, vmid, node, archive, new_vmid, name, storage, bridge, confirmation, ack_isolation, request_id, review_file):
    identifier(node);identifier(storage);identifier(bridge)
    query={'archive':archive,'new_vmid':new_vmid,'storage_id':storage,'bridge_id':bridge}
    result=app.request(f'nodes/{segment(node)}/vms/{vmid}/restore-review?'+urlencode(query),operator=True)
    review=result['data'];before=review.get('observed_before',{});destination=before.get('destination',{})
    if (review.get('target')!={'node_id':node,'vmid':vmid} or destination.get('vmid')!=new_vmid
            or destination.get('storage_id')!=storage or destination.get('bridge_id')!=bridge
            or before.get('archive',{}).get('file',{}).get('volume_id')!=archive):
        raise ClientError('TARGET_CHANGED','조회한 원본/archive/복원 대상이 선택한 값과 다릅니다.',8)
    payload={**query,'name':name,'idempotency_key':request_id,'expected_name':before.get('name'),
        'expected_review_digest':before.get('review_digest'),'confirmation':confirmation,'isolation_acknowledged':ack_isolation}
    validate(payload)
    if int(re.fullmatch(ARCHIVE,archive)[1])!=vmid:raise ClientError('TARGET_CHANGED','archive 원본 VMID가 다릅니다.',8)
    resource_review.save(app,schema='gjallar.cli.restore.v1',review=review,payload=payload,path=review_file)
    return {**result,'review_file':str(review_file),'exit_code':0,
        'message':'격리 복원 검토를 저장했습니다. 원본은 보존하고 새 VM은 자동 시작하지 않습니다. 아직 복원하지 않았습니다.',
        'next':'gjallar vm restore execute --review-file <파일>'}


def execute(app, review_file, confirm):
    return resource_review.execute(app,review_file,confirm,schema='gjallar.cli.restore.v1',validate=validate,
        action='restore',operation_type='vm_restore',operation_vmid_from_payload=lambda payload:payload['new_vmid'],
        label='별도 VMID로 격리 복원 (원본 보존·NIC 링크 끊김·자동 시작 없음)')


def report(app, operation_id):
    return app.request(f'operations/{segment(operation_id)}/restore-report')
