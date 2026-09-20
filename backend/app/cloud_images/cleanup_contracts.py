"""Scope policy for explicit cleanup of operation-owned image resources."""
from urllib.parse import unquote
from app.cloud_images.contracts import selected_import


def cleanup_request_allowed(method, pieces, data, scope):
    if method != 'DELETE':
        return False
    if len(pieces) == 4 and pieces[2] == 'qemu' and pieces[3].isdigit():
        return (int(pieces[3]) in scope['vmids'] and isinstance(data, dict)
                and data == {'purge': 0, 'destroy-unreferenced-disks': 0}
                and all(type(value) is int for value in data.values()))
    if len(pieces) == 6 and pieces[2] == 'storage' and pieces[4] == 'content':
        volume = unquote(pieces[5])
        return (data == {} and pieces[3] in scope.get('image_cleanup_storages', [])
                and volume.split(':', 1)[0] == pieces[3]
                and selected_import(volume, {**scope, 'image_vmids': []}, include_existing=True))
    return False
