"""Exact PVE backup request policy shared by adapter and managed transport."""
import re

ID = r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}'
OPERATION = r'vm-backup-[a-f0-9]{64}'
ARCHIVE = rf'({ID}):backup/vzdump-qemu-([1-9][0-9]{{2,8}})-(\d{{4}}_\d{{2}}_\d{{2}}-\d{{2}}_\d{{2}}_\d{{2}})\.vma(?:\.(zst|gz|lzo))?'


def backup_body(vmid, storage, operation_id):
    return {'vmid': str(vmid), 'storage': storage, 'mode': 'snapshot', 'compress': 'zstd',
            'remove': 0, 'all': 0, 'stop': 0, 'fleecing': 'enabled=0', 'lockwait': 0,
            'notification-mode': 'legacy-sendmail', 'mailto': '', 'notes-template': operation_id}


def backup_request_allowed(method, pieces, data, scope):
    if method != 'POST' or len(pieces) != 3 or pieces[2] != 'vzdump' or not isinstance(data, dict): return False
    vmid, storage, marker = data.get('vmid'), data.get('storage'), data.get('notes-template')
    return (isinstance(vmid, str) and vmid in {str(value) for value in scope['vmids']}
            and storage in scope.get('backup_storages', []) and isinstance(marker, str) and bool(re.fullmatch(OPERATION, marker))
            and data == backup_body(int(vmid), storage, marker)
            and all(type(data[key]) is int for key in ('remove', 'all', 'stop', 'lockwait')))


def restore_body(*, new_vmid, name, archive, storage, bridge, mac, firewall, operation_id):
    return {'vmid': new_vmid, 'name': name, 'archive': archive, 'storage': storage, 'description': operation_id,
            'net0': f'virtio={mac},bridge={bridge},link_down=1,firewall={firewall}',
            'force': 0, 'unique': 1, 'start': 0, 'live-restore': 0, 'onboot': 0}


def restore_request_allowed(method, pieces, data, scope):
    if method != 'POST' or len(pieces) != 3 or pieces[2] != 'qemu' or not isinstance(data, dict): return False
    required = {'vmid','name','archive','storage','description','net0','force','unique','start','live-restore','onboot'}
    if set(data) != required: return False
    archive = re.fullmatch(ARCHIVE, data['archive']) if isinstance(data['archive'], str) else None
    nic = re.fullmatch(rf'virtio=(02:(?:[0-9A-F]{{2}}:){{4}}[0-9A-F]{{2}}),bridge=({ID}),link_down=1,firewall=([01])', data['net0']) if isinstance(data['net0'], str) else None
    return (type(data['vmid']) is int and data['vmid'] in scope.get('restore_vmids', [])
            and archive is not None and archive[1] in scope.get('backup_storages', []) and int(archive[2]) in scope['vmids']
            and data['vmid'] != int(archive[2]) and data['storage'] in scope.get('restore_storages', [])
            and nic is not None and nic[2] in scope['bridges']
            and isinstance(data['name'], str) and bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,62}', data['name']))
            and isinstance(data['description'], str) and bool(re.fullmatch(r'vm-restore-[a-f0-9]{64}', data['description']))
            and all(type(data[key]) is int and data[key] == expected for key,expected in
                    [('force',0),('unique',1),('start',0),('live-restore',0),('onboot',0)]))


def selected_archive(volume, scope):
    match = re.fullmatch(ARCHIVE, volume) if isinstance(volume, str) else None
    return match is not None and match[1] in scope.get('backup_storages', []) and int(match[2]) in scope['vmids']
