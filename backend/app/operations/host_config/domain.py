"""Exact non-VM target and immutable host configuration lock binding."""
import hashlib
import re
from collections.abc import Mapping

HOST_OPERATION_TYPES = frozenset({'host_storage', 'host_network'})
HOST_SCOPE_TYPE = 'proxmox_configuration'
HOST_BINDING_FIELDS = frozenset({'target_lock_id', 'cluster_id', 'scope_key', 'target_type', 'target_id',
    'target', 'operation_type', 'execution_mode', 'related_target_locks', 'vmid'})
IDENTIFIER = r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}'


def configuration_scope_key(cluster_id):
    if not isinstance(cluster_id, str) or not cluster_id.strip() or len(cluster_id.strip()) > 120:
        raise ValueError('Host configuration cluster identity is required')
    return 'proxmox_configuration:' + hashlib.sha256(cluster_id.strip().encode()).hexdigest()


def target_identity(operation_type, target):
    if not isinstance(target, Mapping) or not isinstance(target.get('node_id'), str) or not re.fullmatch(IDENTIFIER, target['node_id']):
        raise ValueError('An exact host node is required')
    if operation_type == 'host_storage' and set(target) == {'node_id', 'storage_id'}:
        if isinstance(target['storage_id'], str) and re.fullmatch(IDENTIFIER, target['storage_id']):
            return 'proxmox_storage', 'storage:' + target['storage_id']
    if operation_type == 'host_network' and set(target) == {'node_id', 'bridge_id'}:
        if isinstance(target['bridge_id'], str) and re.fullmatch(r'vmbr[0-9]{1,4}', target['bridge_id']):
            return 'proxmox_network', f"node:{target['node_id']}/bridge:{target['bridge_id']}"
    raise ValueError('Unsupported host configuration target')


def lock_binding(*, operation_type, target_type, target_id, operation_details, recovery_details):
    if operation_type not in HOST_OPERATION_TYPES:
        return None
    fields = ('target_lock_id', 'cluster_id', 'scope_key', 'target_type', 'target_id', 'target', 'operation_type', 'execution_mode')
    if any(field not in operation_details or operation_details[field] != recovery_details.get(field) for field in fields):
        return None
    value = {field: operation_details[field] for field in fields}
    try:
        exact_type, exact_id = target_identity(operation_type, value['target'])
        scope = configuration_scope_key(value['cluster_id'])
    except ValueError:
        return None
    if (not isinstance(value['target_lock_id'], str) or not value['target_lock_id'].strip()
            or value['scope_key'] != scope or value['target_type'] != target_type or value['target_id'] != target_id
            or (exact_type, exact_id) != (target_type, target_id) or value['operation_type'] != operation_type
            or value['execution_mode'] != 'managed_api' or operation_details.get('related_target_locks')
            or recovery_details.get('related_target_locks') or operation_details.get('vmid') is not None or recovery_details.get('vmid') is not None):
        return None
    return value


def preserves_lock_binding(current, patch):
    """A checkpoint may add observations but cannot replace its admitted target."""
    return all(field not in patch or patch[field] == current.get(field) for field in HOST_BINDING_FIELDS)
