"""Sanitized Proxmox storage configuration reads and one exact write."""
from app.operations.host_storage.domain import StorageError, summarize_config
from app.proxmox.client import ProxmoxMutationError


class StorageClient:
    def __init__(self, client):
        self.client = client

    def check_permissions(self, *, storage_id):
        try:
            global_permissions = self.client.get_storage_configuration_permissions()
            selected = self.client.get_storage_permissions(storage=storage_id)
        except ProxmoxMutationError:
            raise StorageError('HOST_STORAGE_PERMISSION_UNAVAILABLE', '호스트 storage 권한을 확인하지 못했습니다.', 503) from None
        if 'Datastore.Allocate' not in global_permissions or not {'Datastore.Allocate','Datastore.Audit'} <= selected:
            raise StorageError('HOST_STORAGE_PERMISSION_DENIED', '관리형 연결에서 호스트 storage 설정 권한을 갱신하세요.', 403)

    def read(self, *, node_id, storage_id):
        try:
            nodes = [row for row in self.client.list_nodes() if row.get('node') == node_id]
            if len(nodes) != 1 or nodes[0].get('status') != 'online':
                raise StorageError('HOST_STORAGE_NODE_UNAVAILABLE', '선택 노드의 online 상태를 확인하세요.')
            rows = [row for row in self.client.list_storage_configurations() if row.get('storage') == storage_id]
            if len(rows) > 1:
                raise StorageError('HOST_STORAGE_CONFIG_INVALID', '중복 storage 관찰을 확인하세요.', 503)
            return self.client.get_storage_configuration(storage=storage_id) if rows else None
        except ProxmoxMutationError:
            raise StorageError('HOST_STORAGE_OBSERVATION_UNAVAILABLE', 'storage 설정을 확인하지 못했습니다.', 503) from None

    def observe(self, *, node_id, storage_id):
        config = self.read(node_id=node_id,storage_id=storage_id)
        if config is None:
            raise StorageError('HOST_STORAGE_RESULT_ABSENT', '변경 대상 storage가 관찰되지 않습니다.')
        observed = summarize_config(config,node_id=node_id,storage_id=storage_id)
        result = {'configuration':observed, 'activation_checked':False, 'active':None,
                  'content_directories_verified':False, 'write_test_performed':False}
        if not observed['enabled'] or observed['create_base_path'] or observed['create_subdirs']:
            return result
        try:
            rows = [row for row in self.client.get_node_storages(node=node_id) if row.get('storage') == storage_id]
        except ProxmoxMutationError:
            raise StorageError('HOST_STORAGE_ACTIVATION_UNAVAILABLE', '저장한 설정의 실제 활성 상태를 확인하지 못했습니다.', 503) from None
        if len(rows) != 1 or rows[0].get('type') != 'dir':
            raise StorageError('HOST_STORAGE_ACTIVATION_UNAVAILABLE', '선택 노드에서 directory storage가 관찰되지 않습니다.', 503)
        row = rows[0]
        if str(row.get('active')) not in {'0','1'} or str(row.get('enabled')) not in {'0','1'}:
            raise StorageError('HOST_STORAGE_ACTIVATION_UNAVAILABLE', 'storage 활성 응답 형식을 확인하지 못했습니다.', 503)
        return {**result, 'activation_checked':True, 'active':str(row['active']) == '1' and str(row['enabled']) == '1'}

    def apply(self, *, node_id, storage_id, change, before):
        try:
            response = self.client.configure_directory_storage(node=node_id,storage=storage_id,change=change,before=before)
        except ProxmoxMutationError:
            raise StorageError('HOST_STORAGE_DISPATCH_UNKNOWN', '설정 요청 결과가 불명확합니다. 자동 재실행하지 마세요.', 503) from None
        if response is not None and (not isinstance(response,dict) or response.get('storage') != storage_id or response.get('type') != 'dir'):
            raise StorageError('HOST_STORAGE_DISPATCH_UNKNOWN', '설정 응답의 대상을 확인하지 못했습니다.', 503)
