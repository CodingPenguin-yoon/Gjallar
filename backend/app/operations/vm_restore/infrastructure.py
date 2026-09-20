"""Scoped archive reads, isolated restore dispatch and observed destination evidence."""
import re

from app.backups.archive import hardware_fingerprint, options, parse_archive_config
from app.backups.contracts import ARCHIVE
from app.backups.domain import BackupError, source, storage_available, target
from app.operations.core.domain import operation_digest
from app.operations.core.evidence import compact_proxmox_task
from app.operations.vm_backup.infrastructure import BackupClient
from app.operations.vm_restore.domain import isolated_mac, task_reference
from app.proxmox.client import ProxmoxMutationError


class RestoreClient:
    def __init__(self, client):
        self.client = client
        self.backups = BackupClient(client)

    def source(self, *, node_id, vmid):
        if 'VM.Audit' not in self.client.get_vm_permissions(vmid=vmid):
            raise BackupError('VM_RESTORE_PERMISSION_DENIED', '원본 VM.Audit 권한을 확인하세요.', 403)
        result = source(self.client.get_vm_current_config(node=node_id, vmid=vmid),
            self.client.get_vm_status(node=node_id, vmid=vmid), self.client.get_vm_pending(node=node_id, vmid=vmid),
            self.client.get_vm_snapshots(node=node_id, vmid=vmid), vmid=vmid)
        stores = self.client.get_node_storages(node=node_id)
        for volume in result['volumes']:
            storage_available(stores, volume['storage_id'], content='images')
        return result

    def archive(self, *, node_id, vmid, archive):
        match = re.fullmatch(ARCHIVE, archive) if isinstance(archive, str) else None
        if not match or int(match[2]) != vmid:
            raise BackupError('VM_RESTORE_ARCHIVE_INVALID', '선택 원본 VM 소유의 정확한 archive를 선택하세요.', 422)
        listing = self.backups.listing(node_id=node_id, vmid=vmid, storage=match[1])
        selected = [row for row in listing['archives'] if row['volume_id'] == archive]
        if len(selected) != 1:
            raise BackupError('VM_RESTORE_ARCHIVE_MISSING', '선택한 백업 파일을 확인하지 못했습니다.')
        _, manifest = parse_archive_config(self.client.get_backup_config(node=node_id, archive=archive), source_vmid=vmid)
        return {'file': selected[0], 'configuration': manifest}

    def review(self, *, node_id, vmid, archive, new_vmid, storage_id, bridge_id):
        target(node_id, vmid, storage_id)
        target(node_id, new_vmid, bridge_id)
        if vmid == new_vmid:
            raise BackupError('VM_RESTORE_TARGET_INVALID', '원본과 다른 새 VMID를 선택하세요.', 422)
        try:
            original = self.source(node_id=node_id, vmid=vmid)
            saved = self.archive(node_id=node_id, vmid=vmid, archive=archive)
            if (not {'VM.Audit', 'VM.Allocate', 'VM.Config.Disk', 'VM.PowerMgmt', 'VM.GuestAgent.Audit'} <= self.client.get_vm_permissions(vmid=new_vmid)
                    or not {'Datastore.Audit', 'Datastore.AllocateSpace'} <= self.client.get_storage_permissions(storage=storage_id)
                    or 'SDN.Use' not in self.client.get_bridge_permissions(bridge=bridge_id)
                    or not self.client.has_node_task_audit(node=node_id)):
                raise BackupError('VM_RESTORE_PERMISSION_DENIED', '새 VM 할당/조회·disk 확인·전원/agent 조회·storage 할당·bridge 사용·노드 조회 권한을 확인하세요.', 403)
            self.client.assert_vmid_unused(vmid=new_vmid)
            store = storage_available(self.client.get_node_storages(node=node_id), storage_id, content='images')
            available = store.get('avail')
            if type(available) is not int or available < saved['configuration']['required_free_bytes']:
                raise BackupError('VM_RESTORE_SPACE_UNCONFIRMED', '복원 disk 가상 용량과 여유 공간을 확보하세요.')
            network = self.client.get_node_network_snapshot(node=node_id)
            bridges = [row for row in network['interfaces'] if row.get('iface') == bridge_id]
            if (network['pending_changes'] or len(bridges) != 1 or bridges[0].get('type') != 'bridge'
                    or bridges[0].get('active') not in (1, '1')):
                raise BackupError('VM_RESTORE_BRIDGE_UNAVAILABLE', '대기 변경이 없는 활성 Linux bridge를 선택하세요.')
            destination = {'vmid': new_vmid, 'storage_id': storage_id, 'bridge_id': bridge_id,
                'bridge_fingerprint': operation_digest(bridges[0]),
                'mac': isolated_mac(archive=archive, node=node_id, new_vmid=new_vmid, source_mac=saved['configuration']['source_mac']),
                'firewall': saved['configuration']['firewall'], 'link_down': True, 'onboot': False}
            manifest = {'vmid': vmid, 'name': original['name'], 'source': original, 'archive': saved, 'destination': destination}
            return {**manifest, 'review_digest': operation_digest(manifest), 'available_bytes': available}
        except ProxmoxMutationError:
            raise BackupError('VM_RESTORE_OBSERVATION_UNAVAILABLE', '원본·archive·미사용 VMID·복원 범위를 확인하지 못했습니다.', 503) from None

    def apply(self, *, node_id, vmid, request, before, operation_id):
        destination = before['destination']
        try:
            result = self.client.restore_vm_backup(node=node_id, new_vmid=request.new_vmid, name=request.name,
                archive=request.archive, storage=request.storage_id, bridge=request.bridge_id,
                mac=destination['mac'], firewall=destination['firewall'], operation_id=operation_id)
        except ProxmoxMutationError:
            raise BackupError('VM_RESTORE_DISPATCH_UNKNOWN', '복원 요청 결과가 불명확합니다. 자동 재복원하지 마세요.', 503) from None
        return task_reference(result, node_id=node_id, vmid=request.new_vmid)

    def destination(self, *, node_id, vmid, allow_running=False):
        config = self.client.get_vm_current_config(node=node_id, vmid=vmid)
        status = self.client.get_vm_status(node=node_id, vmid=vmid)
        if allow_running and status.get('status') not in {'running', 'stopped'}:
            raise BackupError('VM_RESTORE_POWER_UNCONFIRMED', '현재 전원 상태를 확인할 수 없습니다.', 503)
        identity = source(config, {'status': 'stopped'} if allow_running else status,
            self.client.get_vm_pending(node=node_id, vmid=vmid), self.client.get_vm_snapshots(node=node_id, vmid=vmid), vmid=vmid)
        stores = self.client.get_node_storages(node=node_id)
        volumes = []
        for volume in identity['volumes']:
            storage_available(stores, volume['storage_id'], content='images')
            observed = self.client.get_volume_info(node=node_id, storage=volume['storage_id'], volume=volume['volume_id'])
            if (type(observed.get('size')) is not int or observed['size'] <= 0
                    or observed.get('format') != volume['format']):
                raise BackupError('VM_RESTORE_VOLUME_UNCONFIRMED', '복원 disk의 실제 크기·형식을 확인할 수 없습니다.', 503)
            volumes.append({**volume, 'size_bytes': observed['size']})
        nic = options(config.get('net0'))
        marker = config.get('description')
        return {**identity, 'status': status['status'], 'volumes': volumes, 'hardware_fingerprint': hardware_fingerprint(config),
            'nic': {key: nic.get(key) for key in ('virtio', 'bridge', 'link_down', 'firewall')},
            'nic_supported': set(nic) == {'virtio', 'bridge', 'link_down', 'firewall'},
            'onboot_disabled': str(config.get('onboot', 0)) == '0',
            'operation_marker': marker if isinstance(marker, str) and re.fullmatch(r'vm-restore-[a-f0-9]{64}', marker) else None,
            'smbios_uuid': options(config['smbios1']).get('uuid') if config.get('smbios1') else None,
            'vmgenid': config.get('vmgenid')}

    def observe(self, *, node_id, vmid, new_vmid, archive):
        try:
            return {'source': self.source(node_id=node_id, vmid=vmid),
                'archive': self.archive(node_id=node_id, vmid=vmid, archive=archive),
                'destination': self.destination(node_id=node_id, vmid=new_vmid),
                'boot_verified': False, 'guest_access_verified': False}
        except ProxmoxMutationError:
            raise BackupError('VM_RESTORE_RESULT_UNAVAILABLE', '복원 대상·원본·백업의 현재 결과를 확인하지 못했습니다.', 503) from None

    def agent_available(self, *, node_id, vmid):
        response = self.client.get_guest_network_interfaces(node=node_id, vmid=vmid)
        return isinstance(response, dict) and isinstance(response.get('result'), list)

    def task(self, *, node_id, upid, heartbeat=None):
        try:
            value = (self.client.wait_for_task(node=node_id, upid=upid, heartbeat=heartbeat) if heartbeat
                     else self.client.get_task_status(node=node_id, upid=upid))
        except ProxmoxMutationError:
            raise BackupError('VM_RESTORE_TASK_UNAVAILABLE', '복원 task 상태를 확인하지 못했습니다.', 503) from None
        return compact_proxmox_task(value, node=node_id, upid=upid)
