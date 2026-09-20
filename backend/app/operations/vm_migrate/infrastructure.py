"""Observe two nodes and shared resources; dispatch one PVE offline migration."""
from app.operations.core.domain import operation_digest
from app.operations.core.evidence import compact_proxmox_task
from app.operations.vm_migrate.domain import MigrateError, check_preconditions, identity, task_reference, validate_target
from app.proxmox.client import ProxmoxMutationError


class MigrateClient:
    def __init__(self, client): self.client = client

    def location(self, vmid):
        rows = [row for row in self.client.list_vm_resources() if row.get('vmid') == vmid]
        if len(rows) != 1 or rows[0].get('type') != 'qemu' or not isinstance(rows[0].get('node'), str):
            raise MigrateError('VM_MIGRATE_LOCATION_UNCONFIRMED','cluster index에서 정확한 단일 QEMU 위치를 확인하지 못했습니다.',503)
        return rows[0]['node']

    def vm(self, *, node_id, vmid):
        config = self.client.get_vm_current_config(node=node_id, vmid=vmid)
        result = identity(config, self.client.get_vm_status(node=node_id, vmid=vmid),
            self.client.get_vm_pending(node=node_id, vmid=vmid), self.client.get_vm_snapshots(node=node_id, vmid=vmid), vmid=vmid)
        volumes = []
        for volume in result['volumes']:
            info = self.client.get_volume_info(node=node_id, storage=volume['storage_id'], volume=volume['volume_id'])
            if (type(info.get('size')) is not int or info['size'] <= 0 or info.get('format') != volume['format']
                    or volume['configured_size_bytes'] is not None and info['size'] != volume['configured_size_bytes']):
                raise MigrateError('VM_MIGRATE_VOLUME_UNCONFIRMED','VM 설정과 실제 disk의 크기·형식이 일치하지 않습니다.',503)
            volumes.append({**volume,'size_bytes':info['size']})
        return {**result, 'volumes':volumes}

    def environment(self, *, node_id, vm):
        if not self.client.has_node_task_audit(node=node_id):
            raise MigrateError('VM_MIGRATE_PERMISSION_DENIED','양쪽 node의 Sys.Audit 권한을 확인하세요.',403)
        status = self.client.get_node_status(node=node_id)
        version, model = status.get('pveversion'), status.get('cpuinfo',{}).get('model')
        if not isinstance(version,str) or not version.startswith('pve-manager/9.') or not isinstance(model,str) or not model:
            raise MigrateError('VM_MIGRATE_NODE_UNCONFIRMED','PVE 9 version·CPU model을 확인할 수 없습니다.',503)
        stores = self.client.get_node_storages(node=node_id)
        shared = []
        for storage_id in sorted({volume['storage_id'] for volume in vm['volumes']}):
            rows = [row for row in stores if row.get('storage') == storage_id]
            if (len(rows)!=1 or rows[0].get('type')!='nfs' or rows[0].get('shared') not in (1,'1')
                    or rows[0].get('active') not in (1,'1') or rows[0].get('enabled') not in (1,'1')
                    or 'images' not in str(rows[0].get('content','')).split(',')):
                raise MigrateError('VM_MIGRATE_STORAGE_UNSUPPORTED','동일 ID의 활성 shared NFS images storage를 양쪽에서 확인하세요.')
            shared.append(storage_id)
        network = self.client.get_node_network_snapshot(node=node_id)
        bridge = vm['nic']['bridge']
        rows = [row for row in network['interfaces'] if row.get('iface')==bridge]
        if network['pending_changes'] or len(rows)!=1 or rows[0].get('type')!='bridge' or rows[0].get('active') not in (1,'1'):
            raise MigrateError('VM_MIGRATE_BRIDGE_UNAVAILABLE','대기 변경이 없는 동일 이름의 활성 Linux bridge가 필요합니다.')
        return {'node_id':node_id,'pve_version':version,'cpu_model':model,'shared_storages':shared,
            'bridge_id':bridge,'bridge_fingerprint':operation_digest(rows[0])}

    def review(self, *, node_id, vmid, destination_node):
        validate_target(node_id,vmid,destination_node)
        try:
            if not {'VM.Audit','VM.Migrate','VM.Config.Disk'} <= self.client.get_vm_permissions(vmid=vmid):
                raise MigrateError('VM_MIGRATE_PERMISSION_DENIED','선택 VM Audit/Migrate/Config.Disk 권한을 확인하세요.',403)
            if self.location(vmid)!=node_id:
                raise MigrateError('VM_MIGRATE_LOCATION_CHANGED','VM의 현재 node가 선택한 원본과 다릅니다.')
            nodes=self.client.list_nodes()
            for node in (node_id,destination_node):
                selected=[row for row in nodes if row.get('node')==node]
                if len(selected)!=1 or selected[0].get('status')!='online':
                    raise MigrateError('VM_MIGRATE_NODE_UNAVAILABLE','서로 다른 두 online node가 필요합니다.')
            vm=self.vm(node_id=node_id,vmid=vmid)
            for storage in {volume['storage_id'] for volume in vm['volumes']}:
                if 'Datastore.Audit' not in self.client.get_storage_permissions(storage=storage):
                    raise MigrateError('VM_MIGRATE_PERMISSION_DENIED','shared storage Audit 권한을 확인하세요.',403)
            if 'SDN.Use' not in self.client.get_bridge_permissions(bridge=vm['nic']['bridge']):
                raise MigrateError('VM_MIGRATE_PERMISSION_DENIED','동일 bridge 사용 권한을 확인하세요.',403)
            original=self.environment(node_id=node_id,vm=vm)
            destination=self.environment(node_id=destination_node,vm=vm)
            if any(original[key]!=destination[key] for key in ('pve_version','cpu_model','shared_storages','bridge_id')):
                raise MigrateError('VM_MIGRATE_NODE_INCOMPATIBLE','첫 지원은 동일 PVE version/CPU model·shared NFS·bridge 조합입니다.')
            # Actual target-side visibility is required even for declared shared storage.
            for volume in vm['volumes']:
                actual=self.client.get_volume_info(node=destination_node,storage=volume['storage_id'],volume=volume['volume_id'])
                if actual.get('size')!=volume['size_bytes'] or actual.get('format')!=volume['format']:
                    raise MigrateError('VM_MIGRATE_SHARED_VOLUME_UNCONFIRMED','목적 node에서 동일 shared volume의 크기/형식을 확인하지 못했습니다.')
            precondition=check_preconditions(self.client.get_vm_migration_preconditions(node=node_id,vmid=vmid,destination=destination_node),destination_node)
            manifest={'node_id':node_id,'vmid':vmid,'name':vm['name'],'vm':vm,'source_node':original,'destination':destination,'preconditions':precondition}
            return {**manifest,'review_digest':operation_digest(manifest)}
        except ProxmoxMutationError:
            raise MigrateError('VM_MIGRATE_OBSERVATION_UNAVAILABLE','VM·이동 사전조건·양쪽 node/shared 자원을 확인하지 못했습니다.',503) from None

    def apply(self, *, node_id, vmid, request):
        try:
            result=self.client.migrate_vm_reviewed(node=node_id,vmid=vmid,destination=request.destination_node)
        except ProxmoxMutationError:
            raise MigrateError('VM_MIGRATE_DISPATCH_UNKNOWN','이동 요청 결과가 불명확합니다. 자동 재이동하지 마세요.',503) from None
        return task_reference(result,node_id=node_id,vmid=vmid)

    def observe(self, *, vmid, destination_node):
        try:
            location=self.location(vmid)
            if location!=destination_node:
                raise MigrateError('VM_MIGRATE_LOCATION_UNCONFIRMED','VM이 정확한 목적 node에 있음을 확인하지 못했습니다.',503)
            vm=self.vm(node_id=destination_node,vmid=vmid)
            environment=self.environment(node_id=destination_node,vm=vm)
            return {'node_id':location,'vm':vm,'destination':environment,'source_location_absent':True,'boot_verified':False}
        except ProxmoxMutationError:
            raise MigrateError('VM_MIGRATE_RESULT_UNAVAILABLE','이동 후 위치·VM·shared 자원을 확인하지 못했습니다.',503) from None

    def task(self, *, node_id, upid, heartbeat=None):
        try:
            value=(self.client.wait_for_task(node=node_id,upid=upid,heartbeat=heartbeat) if heartbeat
                else self.client.get_task_status(node=node_id,upid=upid))
        except ProxmoxMutationError:
            raise MigrateError('VM_MIGRATE_TASK_UNAVAILABLE','원본 node의 이동 task를 확인하지 못했습니다.',503) from None
        return compact_proxmox_task(value,node=node_id,upid=upid)
