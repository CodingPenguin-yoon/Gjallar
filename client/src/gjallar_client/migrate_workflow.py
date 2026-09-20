"""Explicit offline migration with source-bound intent and no automatic retry."""
import re
from urllib.parse import urlencode
from . import resource_review
from .errors import ClientError
from .workflows import identifier, request_identity, segment


def validate(payload):
    fields={'destination_node','idempotency_key','expected_name','expected_review_digest','confirmation','migration_acknowledged'}
    if not isinstance(payload,dict) or set(payload)!=fields:raise ClientError('INVALID_REVIEW','이동 검토 필드를 확인하세요.',2)
    identifier(payload['destination_node']);request_identity(payload['idempotency_key'])
    name,digest=payload['expected_name'],payload['expected_review_digest']
    if (not isinstance(name,str) or not 1<=len(name)<=255 or not isinstance(digest,str)
            or not re.fullmatch(r'sha256:[a-f0-9]{64}',digest) or not isinstance(payload['confirmation'],str)
            or not re.fullmatch(r'[1-9][0-9]{2,8}/'+re.escape(name)+r'/[A-Za-z0-9][A-Za-z0-9_.-]{0,63}->'+re.escape(payload['destination_node']),payload['confirmation'])
            or payload['migration_acknowledged'] is not True):
        raise ClientError('MIGRATION_CONFIRMATION_REQUIRED','VMID/이름/원본->목적 node와 이동 영향을 확인하세요.',2)


def show(app, *, vmid, node, destination):
    identifier(node);identifier(destination)
    if type(vmid) is not int or not 100<=vmid<=999999999 or node==destination:
        raise ClientError('INVALID_TARGET','정확한 VMID와 서로 다른 node를 선택하세요.',2)
    return app.request(f'nodes/{segment(node)}/vms/{vmid}/migrate?'+urlencode({'destination_node':destination}),operator=True)


def plan(app, *, vmid, node, destination, confirmation, ack_migration, request_id, review_file):
    result=show(app,vmid=vmid,node=node,destination=destination)
    review=result['data'];before=review.get('observed_before',{})
    if review.get('target')!={'node_id':node,'vmid':vmid} or before.get('destination',{}).get('node_id')!=destination:
        raise ClientError('TARGET_CHANGED','조회한 원본/목적 node가 선택한 대상과 다릅니다.',8)
    payload={'destination_node':destination,'idempotency_key':request_id,'expected_name':before.get('name'),
        'expected_review_digest':before.get('review_digest'),'confirmation':confirmation,'migration_acknowledged':ack_migration}
    validate(payload)
    if confirmation!=f"{vmid}/{before['name']}/{node}->{destination}":
        raise ClientError('MIGRATION_CONFIRMATION_REQUIRED','조회한 원본 VM/node와 목적 node를 확인하세요.',2)
    resource_review.save(app,schema='gjallar.cli.migrate.v1',review=review,payload=payload,path=review_file)
    return {**result,'review_file':str(review_file),'exit_code':0,'message':'정지 VM 노드 이동 검토를 저장했습니다. 아직 이동하지 않았습니다.',
        'next':'gjallar vm migrate execute --review-file <파일>'}


def execute(app, review_file, confirm):
    return resource_review.execute(app,review_file,confirm,schema='gjallar.cli.migrate.v1',validate=validate,
        action='migrate',operation_type='vm_migrate',label='정지 VM node 이동 (shared disk/identity 보존·자동 시작 없음)')
