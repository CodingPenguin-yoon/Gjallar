"""Current restoration checks without booting or attaching the guest network."""
from datetime import datetime, timezone
from app.backups.domain import BackupError
from app.operations.vm_restore.application import RestoreService
from app.proxmox.client import ProxmoxMutationError


def restore_report(result, client):
    operation = result.get('operation', {})
    details = operation.get('details', {})
    target, source = details.get('target', {}), details.get('source', {})
    operation_id = operation.get('operation_id')
    if (operation.get('operation_type') != 'vm_restore' or operation.get('execution_mode') != 'managed_api'
            or operation.get('target_type') != 'proxmox_vm' or type(target.get('vmid')) is not int
            or operation.get('target_id') != f"vmid:{target.get('vmid')}" or not target.get('node_id')
            or target.get('node_id') != source.get('node_id') or type(source.get('vmid')) is not int
            or target['vmid'] == source['vmid'] or operation.get('status') != 'succeeded'
            or operation.get('coordination_incomplete') or result.get('coordination_incomplete')):
        raise BackupError('VM_RESTORE_REPORT_NOT_READY', '정확한 대상에 연결된 복원 완료 Operation을 먼저 확인하세요.')
    before, requested = details['observed_before'], details['requested']
    checks = []
    def check(name, status, limitation):
        checks.append({'name': name, 'status': status, 'limitation': limitation})
    check('restore_task', 'passed', '이 Operation이 완료될 때 기록한 task·disk·격리 결과입니다.')
    observations = {}
    for name, read, expected in (
        ('source_preserved', lambda: client.source(node_id=source['node_id'], vmid=source['vmid']), before['source']),
        ('archive_preserved', lambda: client.archive(node_id=source['node_id'], vmid=source['vmid'], archive=requested['archive']), before['archive']),
    ):
        try:
            observations[name] = read()
        except (BackupError, ProxmoxMutationError):
            check(name, 'unavailable', '원본 상태 또는 archive를 현재 조회·대조하지 못했습니다. 보존 성공으로 간주하지 않습니다.')
        else:
            check(name, 'passed' if observations[name] == expected else 'not_verified',
                '복원 검토 시점과 현재 metadata/config를 비교합니다. disk 내용 전체 hash 검사가 아닙니다.')
    try:
        current = client.destination(node_id=target['node_id'], vmid=target['vmid'], allow_running=True)
    except (BackupError, ProxmoxMutationError):
        for name in ('restored_configuration','network_isolation','power','guest_agent'):
            check(name, 'unavailable', '복원 대상의 현재 상태를 확인하지 못했습니다.')
        power = 'unknown'
    else:
        power = current['status']
        # The original restore required stopped power. Current boot is reported separately.
        comparison = {'source': before['source'], 'archive': before['archive'],
            'destination': {**current, 'status':'stopped'}, 'expected_marker':operation_id}
        same = RestoreService.matches(comparison, requested, before)
        isolated = (current['nic_supported'] and current['nic']['link_down'] == '1'
                    and current['nic']['virtio'] == before['destination']['mac']
                    and current['nic']['bridge'] == requested['bridge_id'])
        check('restored_configuration', 'passed' if same else 'not_verified', '소유 Operation·이름·disk·hardware·새 identity를 현재 대조합니다.')
        check('network_isolation', 'passed' if isolated else 'not_verified', '현재 PVE net0 link_down 관찰입니다. 이후 외부 설정 변경을 막지는 않습니다.')
        check('power', 'running' if power == 'running' else 'stopped', 'QEMU 전원 상태입니다. running만으로 OS·서비스 성공을 뜻하지 않습니다.')
        agent = 'not_run'
        if same and isolated and power == 'running':
            try:
                agent = 'passed' if client.agent_available(node_id=target['node_id'], vmid=target['vmid']) else 'unavailable'
            except ProxmoxMutationError:
                agent = 'unavailable'
        check('guest_agent', agent, '실행 중인 동일 복원 VM의 agent 읽기 응답만 확인합니다. IP·접속 성공은 검증하지 않습니다.')
    return {'operation_id': operation_id, 'target': target, 'source': source, 'read_only': True,
        'observed_at': datetime.now(timezone.utc).isoformat(), 'power': power, 'checks': checks,
        'external_access_verified': False, 'automatic_boot': False, 'automatic_cleanup': False,
        'instructions': ['VM 상세의 시작·정상 종료는 별도 명시적 작업입니다. NIC 링크는 연결하지 마세요.',
            '원본 IP·hostname·SSH key가 복제됩니다. identity 정리와 네트워크 연결은 별도 운영 검토가 필요합니다.',
            '정리는 현재 대상 재검토·정상 종료·명시적 삭제와 실제 부재 확인으로 수행하세요. 관리형 delete 범위 갱신이 필요할 수 있습니다.']}
