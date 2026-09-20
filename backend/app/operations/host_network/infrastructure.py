"""One bridge stage, one node reload, and sanitized observation adapters."""
from app.operations.core.evidence import compact_proxmox_task
from app.operations.host_network.domain import BridgeError, task_reference
from app.proxmox.client import ProxmoxMutationError


class BridgeClient:
    def __init__(self, client):
        self.client = client

    def check_permissions(self, *, node_id):
        try:
            permissions = self.client.get_host_network_permissions(node=node_id)
        except ProxmoxMutationError:
            raise BridgeError('HOST_NETWORK_PERMISSION_UNAVAILABLE', '호스트 네트워크 권한을 확인하지 못했습니다.', 503) from None
        if (not {'Sys.Audit', 'Sys.Modify'} <= permissions.get(f'/nodes/{node_id}', set())
                or 'SDN.Audit' not in permissions.get('/sdn/zones/localnetwork', set())):
            raise BridgeError('HOST_NETWORK_PERMISSION_DENIED', '노드 수정·전체 local bridge 조회 권한을 갱신하세요.', 403)

    def read(self, *, node_id):
        try:
            nodes = [row for row in self.client.list_nodes() if row.get('node') == node_id]
            if len(nodes) != 1 or nodes[0].get('status') != 'online':
                raise BridgeError('HOST_NETWORK_NODE_UNAVAILABLE', '선택 노드의 online 상태를 확인하세요.')
            return self.client.get_host_network_snapshot(node=node_id)
        except ProxmoxMutationError:
            raise BridgeError('HOST_NETWORK_OBSERVATION_UNAVAILABLE', '노드 전체 네트워크 설정을 확인하지 못했습니다.', 503) from None

    def stage(self, *, node_id, bridge_id, change):
        try:
            response = self.client.stage_host_bridge(node=node_id, bridge=bridge_id, change=change)
        except ProxmoxMutationError:
            raise BridgeError('HOST_NETWORK_STAGE_UNKNOWN', '설정 저장 결과가 불명확합니다. 자동 반영하지 마세요.', 503) from None
        if response is not None:
            raise BridgeError('HOST_NETWORK_STAGE_UNKNOWN', '설정 저장 응답 형식을 확인하지 못했습니다.', 503)

    def reload(self, *, node_id):
        try:
            response = self.client.reload_host_network(node=node_id)
        except ProxmoxMutationError:
            raise BridgeError('HOST_NETWORK_RELOAD_UNKNOWN', '노드 전체 반영 결과가 불명확합니다. 자동 재실행하지 마세요.', 503) from None
        return task_reference(response, node_id=node_id)

    def task(self, *, node_id, upid, heartbeat=None):
        task_reference(upid, node_id=node_id)
        try:
            value = (self.client.wait_for_task(node=node_id, upid=upid, heartbeat=heartbeat) if heartbeat
                     else self.client.get_task_status(node=node_id, upid=upid))
        except ProxmoxMutationError:
            raise BridgeError('HOST_NETWORK_TASK_UNAVAILABLE', '네트워크 반영 task 상태를 확인하지 못했습니다.', 503) from None
        if not isinstance(value, dict):
            raise BridgeError('HOST_NETWORK_TASK_UNAVAILABLE', 'task 응답을 확인하지 못했습니다.', 503)
        # wait_for_task aggregates polls; inspect their identities before compacting.
        polls = value.get('polls', [])
        if not isinstance(polls, list) or any(not isinstance(row, dict) for row in polls):
            raise BridgeError('HOST_NETWORK_TASK_UNKNOWN', 'task 관찰 형식을 확인하지 못했습니다.', 503)
        for row in [value, *polls]:
            for key, expected in {'node': node_id, 'upid': upid, 'type': 'srvreload', 'id': 'networking'}.items():
                if key in row and row[key] != expected:
                    raise BridgeError('HOST_NETWORK_TASK_UNKNOWN', '다른 대상의 task 관찰입니다.', 503)
        return compact_proxmox_task(value, node=node_id, upid=upid)
