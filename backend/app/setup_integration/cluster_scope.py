"""Project request targets into existing field policies for whole-cluster access.

These finite lists are NOT an authorization boundary for cluster connections.
They let the same operation/body validators check any current or future target,
without inventory snapshots, permanent allowlists, or wildcard collections.
"""
import re
from urllib.parse import parse_qsl, unquote, urlsplit

from app.setup_integration.contracts import Scope


def request_scope(configuration, path, data=None):
    if configuration.get('access_mode', 'scoped') != 'cluster':
        return configuration['scope']
    parsed = urlsplit(path)
    values = [unquote(parsed.path)]
    fields = dict(parse_qsl(parsed.query))
    if isinstance(data, dict):
        fields.update(data)
    for key in ('target', 'nodes', 'storage', 'archive', 'volume', 'net0', 'scsi0', 'vmid', 'newid', 'iface', 'path'):
        value = fields.get(key)
        if isinstance(value, str) or type(value) is int:
            values.append(str(value))
    identifiers, vmids = set(), set()
    for value in values:
        identifiers.update(part for part in re.split(r'[^A-Za-z0-9_.-]+', value)
                           if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', part))
        ids = [value] if value.isdigit() else re.findall(r'(?:/|vm-|base-|image-|qemu-)([0-9]+)(?=[/.-]|$)', value)
        vmids.update(int(item) for item in ids if len(item) <= 9 and 100 <= int(item) <= 999999999)
    return {key: sorted(vmids if key.endswith('vmids') else identifiers) for key in Scope.model_fields}
