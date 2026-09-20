"""Private server-bound review followed by one explicit host storage request."""
import re
from .errors import ClientError
from .resource_review import save
from .workflows import mutation, read_json, request_identity, segment

CONTENTS = {'images','iso','backup','import','snippets','vztmpl','rootdir'}


def target_identity(node, storage):
    if any(not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',value) for value in (node,storage)):
        raise ClientError('INVALID_TARGET','정확한 노드와 storage ID를 입력하세요.',2)
    return {'node_id':node,'storage_id':storage}


def validate_change(change):
    if (not isinstance(change,dict) or set(change) != {'mode','path','content','enabled'}
            or change['mode'] not in {'create','update'} or type(change['enabled']) is not bool
            or not isinstance(change['content'],list) or not change['content']
            or any(not isinstance(value,str) or value not in CONTENTS for value in change['content'])
            or change['content'] != sorted(set(change['content']))):
        raise ClientError('INVALID_REVIEW','directory storage 변경 내용을 확인하세요.',2)
    path = change['path']
    if (change['mode'] == 'update' and path is not None or change['mode'] == 'create' and
        (not isinstance(path,str) or not re.fullmatch(r'/[-A-Za-z0-9_.@/]+',path) or len(path)>512
         or any(part in {'','.','..'} for part in path.split('/')[1:]) or not change['enabled'])):
        raise ClientError('INVALID_REVIEW','신규 등록은 기존 절대 directory, 수정은 경로 유지가 필요합니다.',2)


def validate(payload,target):
    fields = {'mode','path','content','enabled','idempotency_key','expected_review_digest','confirmation','acknowledge_cluster_impact'}
    if not isinstance(payload,dict) or set(payload) != fields:
        raise ClientError('INVALID_REVIEW','storage 검토 필드를 확인하세요.',2)
    validate_change({key:payload[key] for key in ('mode','path','content','enabled')})
    request_identity(payload['idempotency_key'])
    if (not isinstance(payload['expected_review_digest'],str) or not re.fullmatch(r'sha256:[a-f0-9]{64}',payload['expected_review_digest'])
            or payload['confirmation'] != f"{target['node_id']}/{target['storage_id']}/{payload['mode']}"
            or payload['acknowledge_cluster_impact'] is not True):
        raise ClientError('HOST_STORAGE_CONFIRMATION_REQUIRED','노드/storage/작업 종류와 클러스터 전체 설정 영향을 확인하세요.',2)


def plan(app, *, node, storage, mode, directory, content, enabled, request_id, confirmation, acknowledge, review_file):
    target = target_identity(node,storage)
    change = {'mode':mode,'path':directory,'content':sorted(set(content)),'enabled':enabled}
    validate_change(change)
    result = app.request(f'nodes/{segment(node)}/host-storage/{segment(storage)}/review',method='POST',body=change,operator=True)
    review = result['data']
    desired = review.get('desired') if isinstance(review,dict) else None
    if (not isinstance(review,dict) or review.get('target') != target or review.get('mode') != mode
            or not isinstance(desired,dict) or desired.get('content') != change['content'] or desired.get('enabled') != enabled
            or (mode == 'create' and desired.get('path') != directory)):
        raise ClientError('TARGET_CHANGED','조회한 storage 대상과 작업 종류가 다릅니다.',8)
    payload = {**change,'idempotency_key':request_id,'expected_review_digest':review.get('review_digest'),
               'confirmation':confirmation,'acknowledge_cluster_impact':acknowledge}
    validate(payload,target)
    save(app,schema='gjallar.cli.host-storage.v1',review=review,payload=payload,path=review_file)
    return {**result,'review_file':str(review_file),'exit_code':0,'message':'storage 검토를 저장했습니다. 아직 호스트 설정을 변경하지 않았습니다.',
            'next':'gjallar host storage execute --review-file <파일>'}


def execute(app, review_file, confirm):
    record = read_json(review_file)
    _,profile = app.connections.get(app.connection_name)
    if (record.get('schema') != 'gjallar.cli.host-storage.v1' or record.get('origin') != profile['origin'] or record.get('connection_id') != profile['id']):
        raise ClientError('REVIEW_CONNECTION_MISMATCH','검토 파일을 만든 서버 연결을 선택하세요.',2)
    target = record.get('target')
    if not isinstance(target,dict) or set(target) != {'node_id','storage_id'}:
        raise ClientError('INVALID_REVIEW','storage 대상 정보를 확인하세요.',2)
    target_identity(target['node_id'],target['storage_id'])
    payload = record.get('payload')
    validate(payload,target)
    review = record.get('review')
    if (not isinstance(review,dict) or review.get('target') != target or review.get('mode') != payload['mode']
            or review.get('review_digest') != payload['expected_review_digest'] or review.get('confirmation') != payload['confirmation']):
        raise ClientError('INVALID_REVIEW','저장된 대상과 검토 기록이 다릅니다.',2)
    confirm({'server':profile['origin'],'action':'directory storage 설정 (클러스터 공용)','target':target,'review':review,'requested':payload})
    return mutation(app,f"nodes/{segment(target['node_id'])}/host-storage/{segment(target['storage_id'])}/actions/configure",payload,
        'gjallar operations list',expected_operation={'type':'host_storage','target_type':'proxmox_storage',
        'target_id':'storage:'+target['storage_id'],'target':target})
