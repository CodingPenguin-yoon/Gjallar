"""Exact immutable lock references for multi-VM operation coordination."""
import re
from collections.abc import Mapping


def expected_lock_count(operation_type):
    return 2 if operation_type in {'vm_clone', 'vm_restore'} else 1


def lock_references(*, operation_type, target_id, operation_details, recovery_details):
    """Return no references when multi-target evidence is incomplete or differs.

    Legacy single-target operations keep their original primary binding contract.
    A clone or restore must also bind the distinct source, identically in both ledgers.
    """
    match = re.fullmatch(r'vmid:([0-9]+)', target_id)
    lock_id = recovery_details.get('target_lock_id')
    if match is None or not isinstance(lock_id, str) or not lock_id.strip():
        return []
    primary = {'lock_id': lock_id, 'vmid': int(match[1])}
    extra = recovery_details.get('related_target_locks', [])
    if expected_lock_count(operation_type) == 1:
        return [] if extra else [primary]
    if (operation_details.get('target_lock_id') != lock_id
            or not isinstance(extra, list) or len(extra) != 1
            or operation_details.get('related_target_locks') != extra):
        return []
    source = operation_details.get('source')
    row = extra[0]
    if (not isinstance(source, Mapping) or not isinstance(row, Mapping) or set(row) != {'lock_id', 'vmid'}
            or type(row['vmid']) is not int or not 100 <= row['vmid'] <= 999999999
            or row['vmid'] != source.get('vmid') or row['vmid'] == primary['vmid']
            or not isinstance(row['lock_id'], str) or not row['lock_id'].strip() or row['lock_id'] == lock_id):
        return []
    return [primary, dict(row)]
