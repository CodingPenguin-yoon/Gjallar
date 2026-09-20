"""Directory configuration rules without storage or network side effects."""
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.operations.core.domain import operation_digest
from app.operations.host_config.domain import target_identity

CONTENTS = frozenset({'images', 'iso', 'backup', 'import', 'snippets', 'vztmpl', 'rootdir'})
CHANGEABLE = frozenset({'content', 'disable', 'create-base-path', 'create-subdirs', 'digest'})


class StorageError(RuntimeError):
    def __init__(self, code, message, status_code=409, details=None):
        super().__init__(message)
        self.code, self.status_code, self.details = code, status_code, details or {}

    def to_detail(self):
        return {'code': self.code, 'message': str(self), 'details': self.details}


def directory_path(value):
    return (isinstance(value, str) and len(value) <= 512 and bool(re.fullmatch(r'/[-a-zA-Z0-9_.@/]+', value))
            and not value.endswith('/') and all(part not in {'', '.', '..'} for part in value.split('/')[1:]))


class StorageChange(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    mode: Literal['create', 'update']
    path: str | None = Field(default=None, max_length=512)
    content: list[str] = Field(min_length=1, max_length=7)
    enabled: bool = True

    @field_validator('content')
    @classmethod
    def supported_content(cls, value):
        if not set(value) <= CONTENTS:
            raise ValueError('Unsupported storage content')
        return sorted(set(value))

    @model_validator(mode='after')
    def check_mode(self):
        if self.mode == 'create' and (not directory_path(self.path) or not self.enabled):
            raise ValueError('Creation requires an existing absolute directory and enabled storage')
        if self.mode == 'update' and self.path is not None:
            raise ValueError('Existing storage paths cannot be changed')
        return self


class StorageRequest(StorageChange):
    idempotency_key: str = Field(min_length=1, max_length=160, pattern=r'^[A-Za-z0-9_.:-]+$')
    expected_review_digest: str = Field(pattern=r'^sha256:[a-f0-9]{64}$')
    confirmation: str = Field(max_length=180)
    acknowledge_cluster_impact: Literal[True]

    @field_validator('acknowledge_cluster_impact', mode='before')
    @classmethod
    def explicit_acknowledgement(cls, value):
        if value is not True:
            raise ValueError('Explicit acknowledgement is required')
        return value


def validate_target(node_id, storage_id):
    try:
        return target_identity('host_storage', {'node_id':node_id, 'storage_id':storage_id})
    except ValueError:
        raise StorageError('HOST_STORAGE_TARGET_INVALID', '노드와 storage ID 형식을 확인하세요.', 422) from None


def _flag(config, key, default):
    value = config.get(key, default)
    if type(value) is bool or type(value) is int and value in (0, 1) or type(value) is str and value in ('0', '1'):
        return str(int(value)) == '1'
    raise StorageError('HOST_STORAGE_CONFIG_INVALID', 'storage 사용 설정을 확인할 수 없습니다.', 503)


def summarize_config(config, *, node_id, storage_id):
    if not isinstance(config, dict) or config.get('type') != 'dir' or config.get('storage') != storage_id:
        raise StorageError('HOST_STORAGE_TYPE_UNSUPPORTED', '정확한 directory storage 설정만 지원합니다.')
    if not directory_path(config.get('path')):
        raise StorageError('HOST_STORAGE_PATH_UNSUPPORTED', '기존 directory 경로를 확인하세요.')
    nodes = config.get('nodes')
    if nodes is None:
        nodes = []
    elif isinstance(nodes, str) and re.fullmatch(r'[A-Za-z0-9_.-]+(?:,[A-Za-z0-9_.-]+)*', nodes):
        nodes = sorted(set(nodes.split(',')))
    else:
        raise StorageError('HOST_STORAGE_CONFIG_INVALID', 'storage 노드 범위를 확인할 수 없습니다.', 503)
    if nodes and node_id not in nodes:
        raise StorageError('HOST_STORAGE_NODE_OUTSIDE_CONFIG', '선택 노드가 기존 storage의 적용 범위에 없습니다.')
    digest = config.get('digest')
    content = config.get('content')
    if (not isinstance(digest, str) or not re.fullmatch(r'[a-fA-F0-9]{40}', digest)
            or not isinstance(content, str) or not content or not set(content.split(',')) <= CONTENTS | {'none'}):
        raise StorageError('HOST_STORAGE_CONFIG_INVALID', 'storage content 또는 변경 감지값을 확인할 수 없습니다.', 503)
    return {'storage_id':storage_id, 'type':'dir', 'path':config['path'], 'nodes':nodes,
            'all_nodes':not nodes, 'shared':_flag(config,'shared',0), 'enabled':not _flag(config,'disable',0),
            'content':sorted(set(content.split(','))), 'digest':digest,
            'create_base_path':_flag(config,'create-base-path',config.get('mkdir',1)),
            'create_subdirs':_flag(config,'create-subdirs',1) and _flag(config,'mkdir',1),
            'preserved_fingerprint':operation_digest({key:value for key,value in config.items() if key not in CHANGEABLE})}


def make_review(*, node_id, storage_id, change, config):
    validate_target(node_id, storage_id)
    before = None if config is None else summarize_config(config,node_id=node_id,storage_id=storage_id)
    if (change.mode == 'create') != (before is None):
        raise StorageError('HOST_STORAGE_EXISTENCE_CHANGED', 'storage의 존재 여부가 요청과 다릅니다. 다시 검토하세요.')
    desired = {'type':'dir', 'path':change.path if before is None else before['path'],
        'nodes':[node_id] if before is None else before['nodes'], 'all_nodes':False if before is None else before['all_nodes'],
        'shared':False if before is None else before['shared'], 'content':change.content, 'enabled':change.enabled,
        'create_base_path':False, 'create_subdirs':False}
    if before and all(before[key] == value for key,value in desired.items()):
        raise StorageError('HOST_STORAGE_NO_CHANGE', '현재 설정과 같습니다.', 422)
    plan = {'target':{'node_id':node_id,'storage_id':storage_id}, 'mode':change.mode,
            'observed_before':before, 'desired':desired}
    return {**plan, 'review_digest':operation_digest(plan), 'confirmation':f'{node_id}/{storage_id}/{change.mode}',
        'warnings':['storage 설정은 클러스터 공용입니다. 기존 적용 노드 전체에 content·사용 여부 변경이 영향을 줍니다.',
                    '기존 디렉터리를 자동 생성하지 않습니다. 하위 content 디렉터리와 실제 VM·백업 작성은 별도 확인이 필요합니다.',
                    '활성 조회는 PVE의 노드 storage 상태 갱신을 사용합니다. PVE가 다른 활성 storage도 점검·활성화할 수 있습니다.',
                    '선택 노드에서만 활성 상태를 검사합니다. 사용 중지 확인은 unmount나 파일 삭제를 뜻하지 않습니다.']}


def mutation_body(change, *, node_id, storage_id, before):
    fields = {'content':','.join(change.content), 'disable':int(not change.enabled), 'create-base-path':0, 'create-subdirs':0}
    if change.mode == 'create':
        return {**fields, 'type':'dir', 'storage':storage_id, 'path':change.path, 'nodes':node_id, 'shared':0}
    return {**fields, 'digest':before['digest']}


def storage_request_allowed(method, path, data, scope):
    """Additional host capability; it never grants volume mutation or arbitrary config."""
    selected = scope.get('host_storages', [])
    if method == 'GET':
        if path == '/storage':
            return data is None
        return data is None and path in {f'/storage/{storage}' for storage in selected}
    if not isinstance(data, dict):
        return False
    base = {'content','disable','create-base-path','create-subdirs'}
    if (not isinstance(data.get('content'),str) or not data['content'] or not set(data['content'].split(',')) <= CONTENTS
            or type(data.get('disable')) is not int or data['disable'] not in (0,1)
            or type(data.get('create-base-path')) is not int or data['create-base-path'] != 0
            or type(data.get('create-subdirs')) is not int or data['create-subdirs'] != 0):
        return False
    if method == 'POST' and path == '/storage':
        return (set(data) == base | {'type','storage','path','nodes','shared'} and data['type'] == 'dir'
            and data['storage'] in selected and data['nodes'] in scope['nodes'] and directory_path(data['path'])
            and type(data['shared']) is int and data['shared'] == 0 and data['disable'] == 0)
    return (method == 'PUT' and path in {f'/storage/{storage}' for storage in selected}
        and set(data) == base | {'digest'} and isinstance(data['digest'],str) and bool(re.fullmatch(r'[a-fA-F0-9]{40}',data['digest'])))
