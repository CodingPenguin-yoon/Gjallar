from collections import Counter
from datetime import datetime, timezone
import re


class MaintenanceError(RuntimeError):
    def __init__(self, code, message, status_code=503):
        super().__init__(message)
        self.code, self.status_code = code, status_code


def _fresh(observed_at, now):
    try:
        observed = datetime.fromisoformat(observed_at.replace('Z', '+00:00'))
        return observed.tzinfo is not None and 0 <= (now - observed).total_seconds() <= 300
    except (TypeError, ValueError, AttributeError):
        return False


def _unknown(code, message, **extra):
    return {'status': 'unavailable', 'code': code, 'message': message, **extra}


class MaintenanceService:
    def __init__(self, inventory, migration_review, backup_listing, clock=lambda: datetime.now(timezone.utc)):
        self.inventory, self.migration_review, self.backup_listing, self.clock = inventory, migration_review, backup_listing, clock

    def report(self, *, node_id, destination_node=None, backup_storage=None, backup_max_age_hours=24, check_limit=10):
        pattern = r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}'
        if (not isinstance(node_id, str) or not re.fullmatch(pattern, node_id)
                or any(value is not None and (not isinstance(value, str) or not re.fullmatch(pattern, value)) for value in (destination_node, backup_storage))
                or destination_node == node_id or type(backup_max_age_hours) is not int or not 1 <= backup_max_age_hours <= 720
                or type(check_limit) is not int or not 1 <= check_limit <= 20):
            raise MaintenanceError('MAINTENANCE_INPUT_INVALID', '서로 다른 node·storage ID와 검사 개수/최근 백업 시간을 확인하세요.', 422)
        observation = self.inventory()
        now = self.clock()
        report = {'node_id': node_id, 'destination_node': destination_node, 'backup_storage': backup_storage,
            'backup_max_age_hours': backup_max_age_hours, 'check_limit': check_limit, 'read_only': True,
            'received_at': now.isoformat(), 'observed_at': observation.get('observed_at'), 'node_shutdown_safe': False,
            'coverage': 'visible_qemu_only', 'limitations': [
                '현재 연결 권한으로 보이는 QEMU VM/template만 포함합니다. 숨겨진 VM·LXC·클러스터 서비스·호스트 의존성은 별도 확인하세요.',
                '수동 이동 준비 확인은 실제 이동·복원·부팅·접속 완료나 노드 종료 안전성 판단이 아닙니다.',
                '최근 백업은 archive 시점·크기 관찰입니다. 복원 가능성·게스트 내용 최신성은 별도 검사하세요.',
                '조회 이후 상태가 바뀔 수 있습니다. 실제 백업·이동은 각 화면에서 다시 검토·확인하세요.'],
            'resources': {}, 'targets': [], 'total_observed_targets': 0, 'truncated': False, 'checks_complete': False}
        snapshot = observation.get('snapshot')
        if snapshot is None:
            return {**report, 'status': 'unavailable', 'code': 'MAINTENANCE_INVENTORY_UNAVAILABLE'}
        nodes = [row for row in snapshot['nodes'] if row['node_id'] == node_id]
        if len(nodes) != 1:
            raise MaintenanceError('MAINTENANCE_NODE_UNAVAILABLE', '선택한 node를 현재 연결의 inventory에서 확인할 수 없습니다.', 404)
        node = nodes[0]
        availability = snapshot.get('availability', {})
        report['observed_at'] = snapshot.get('observed_at')
        report['availability'] = availability
        report['inventory_fresh'] = _fresh(report['observed_at'], now)
        report['resources'] = {'status': node['status'], 'cpu_total': node['cpu_total'], 'memory_total_mb': node['memory_total_mb'],
            'storages': [{key: item[key] for key in ('storage_id', 'type', 'total_gb', 'free_gb', 'content')} for item in node['storage']],
            'bridges': [{key: item.get(key) for key in ('bridge_id', 'type', 'active', 'vlan_aware')} for item in node['networks']]}
        # Templates are a separate inventory collection; a matching template flag in vms is one target.
        targets = [row for row in snapshot['vms'] if row['node_id'] == node_id]
        template_ids = {row['vmid'] for row in targets if row.get('template')}
        targets += [{**row, 'template': True, 'status': 'template'} for row in snapshot['templates']
                    if row['node_id'] == node_id and row['vmid'] not in template_ids]
        targets.sort(key=lambda row: row['vmid'])
        counts = Counter(row['vmid'] for row in targets)
        report['total_observed_targets'] = len(targets)
        report['truncated'] = len(targets) > 200
        consulted = 0
        relevant_sources = ('storage', 'network', 'vm_config', 'vm_detail')
        complete = (report['inventory_fresh'] and node['status'] == 'online'
            and all(availability.get('sources', {}).get(key, {}).get('complete') is True for key in relevant_sources))
        report['required_observations_complete'] = complete
        for vm in targets[:200]:
            item = {'vmid': vm['vmid'], 'name': vm['name'], 'node_id': node_id, 'power_state': vm['status'],
                'template': bool(vm.get('template')), 'still_on_source': True, 'preparation': 'incomplete',
                'cpu': vm.get('cpu'), 'memory_mb': vm.get('memory_mb'),
                'storage_ids': sorted({disk['storage_id'] for disk in vm.get('disks', [])} | ({vm['storage_id']} if vm.get('storage_id') else set())),
                'bridges': sorted({nic['bridge_id'] for nic in vm.get('nic_bridge_evidence', [])})}
            if counts[vm['vmid']] != 1:
                item['migration'] = item['backup'] = _unknown('MAINTENANCE_IDENTITY_AMBIGUOUS', '중복 VMID 관찰을 먼저 해결하세요.')
            elif item['template']:
                item['migration'] = item['backup'] = {'status': 'unsupported', 'message': '첫 자동 검사는 일반 VM만 지원합니다. template 의존성을 수동 확인하세요.'}
            elif not complete:
                item['migration'] = item['backup'] = _unknown('MAINTENANCE_INVENTORY_INCOMPLETE', '5분 이내의 완전한 online node 관찰이 필요합니다.')
            elif consulted >= check_limit:
                item['migration'] = item['backup'] = {'status': 'not_checked', 'message': '한 보고서의 추가 검사 한도입니다. 개별 VM에서 확인하세요.'}
            else:
                consulted += 1
                item['migration'] = self._migration(node_id, vm, destination_node)
                item['backup'] = self._backup(node_id, vm['vmid'], backup_storage, backup_max_age_hours, now)
                if item['migration']['status'] == 'ready' and item['backup']['status'] == 'recent_archive':
                    item['preparation'] = 'ready_for_manual_migration'
            report['targets'].append(item)
        report['checked_target_count'] = consulted
        report['prepared_target_count'] = sum(row['preparation'] == 'ready_for_manual_migration' for row in report['targets'])
        report['checks_complete'] = bool(targets) and complete and not report['truncated'] and report['prepared_target_count'] == len(targets)
        report['status'] = ('unavailable' if not complete else 'preparation_checked' if report['checks_complete']
            else 'incomplete' if targets else 'no_visible_targets')
        return report

    def _migration(self, node, vm, destination):
        if destination is None:
            return {'status': 'not_checked', 'message': '목적 node를 선택하세요.'}
        if vm['status'] != 'stopped':
            return {'status': 'blocked', 'code': 'VM_MIGRATE_NOT_STOPPED', 'message': '정상 종료가 필요합니다. 실행 중 VM을 자동 종료하지 않습니다.'}
        try:
            review = self.migration_review(node_id=node, vmid=vm['vmid'], destination_node=destination)
            if (review.get('target') != {'node_id': node, 'vmid': vm['vmid']}
                    or review.get('observed_before', {}).get('destination', {}).get('node_id') != destination
                    or review.get('observed_before', {}).get('name') != vm['name']):
                return _unknown('MAINTENANCE_TARGET_CHANGED', '현재 검토 대상이 inventory와 달라졌습니다.')
            return {'status': 'ready', 'message': '현재 OPS-01 조건을 확인했습니다. 아직 이동하지 않았습니다.'}
        except MaintenanceError as exc:
            return {'status': 'blocked' if exc.status_code in (403, 409, 422) else 'unavailable', 'code': exc.code, 'message': str(exc)}

    def _backup(self, node, vmid, storage, hours, now):
        if storage is None:
            return {'status': 'not_checked', 'message': 'NFS backup storage를 선택하세요.'}
        try:
            listing = self.backup_listing(node_id=node, vmid=vmid, storage=storage)
            if listing.get('target') != {'node_id': node, 'vmid': vmid, 'storage_id': storage}:
                return _unknown('MAINTENANCE_BACKUP_TARGET_CHANGED', '백업 목록의 대상이 선택과 다릅니다.')
            archives = listing['archives']
            if not archives:
                return {'status': 'missing', 'message': '선택 storage에 백업이 없습니다. 명시적 백업이 필요합니다.'}
            latest = max(archives, key=lambda row: row['created_at'])
            age = now.timestamp() - latest['created_at']
            if age < 0:
                return _unknown('MAINTENANCE_BACKUP_TIME_INVALID', '백업 시각이 미래입니다. 호스트 시각을 확인하세요.')
            return {'status': 'recent_archive' if age <= hours * 3600 else 'old_archive',
                'latest_archive': {key: latest[key] for key in ('volume_id', 'created_at', 'size_bytes')},
                'age_hours': round(age / 3600, 2), 'restore_verified': False,
                'message': '최근 archive metadata를 확인했습니다. 복원 검사는 별도입니다.' if age <= hours * 3600 else '선택한 최근 시간보다 오래된 백업입니다. 새 백업 필요 여부를 확인하세요.'}
        except MaintenanceError as exc:
            return _unknown(exc.code, str(exc))
