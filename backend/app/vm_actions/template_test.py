"""Historical deployment checks composed from exact Create-owned evidence."""
from collections.abc import Mapping

from app.jobs.runs import get_job_run_strict
from app.operations.facade import get_operation
from app.vm_actions.post_create_readiness import PostCreateReadinessError


def mapping(value):
    return dict(value) if isinstance(value, Mapping) else {}


def template_test_report(operation_id):
    result = get_operation(operation_id)
    operation = mapping(result.get('operation'))
    details = mapping(operation.get('details'))
    target = mapping(details.get('target'))
    vmid = target.get('vmid')
    if (operation.get('operation_type') != 'vm_create' or operation.get('execution_mode') != 'managed_api'
            or operation.get('target_type') != 'proxmox_vm' or type(vmid) is not int or vmid < 100
            or operation.get('target_id') != f'vmid:{vmid}' or not target.get('node_id')):
        raise PostCreateReadinessError('TEMPLATE_TEST_TARGET_INVALID', 'VM 생성 작업과 정확한 배포 대상을 확인하세요.')
    readiness = mapping(mapping(result.get('create_readiness')).get('readiness'))
    evidence = mapping(readiness.get('checks'))
    power_policy = readiness.get('power_policy') or details.get('power_policy')
    checks = []
    for name, key, limitation in (
        ('boot', 'running', '생성 후 PVE running 관찰. 현재 상태를 다시 조회하지 않습니다.'),
        ('cloud_init', 'cloud_init_completed', '생성 시 고정 cloud-init status 명령의 종료 결과입니다.'),
        ('guest_agent', 'guest_agent_available', '생성 시 guest agent 응답과 IP 관찰 결과입니다.'),
        ('network', 'ip_observed', '게스트 IPv4 관찰만 확인합니다. 외부 통신·gateway·SSH 접속 성공을 뜻하지 않습니다.'),
    ):
        value = evidence.get(key)
        status = ('not_run' if power_policy == 'stopped' else
                  'passed' if value is True else 'not_verified' if value is False else 'unavailable')
        checks.append({'name': name, 'status': status, 'source': 'create_observation', 'limitation': limitation})
    access = {'name': 'access', 'status': 'not_run', 'source': 'operator_evidence',
              'limitation': '운영자가 별도 SSH 접속을 확인한 기록입니다. Gjallar는 접속하거나 개인키를 수집하지 않습니다.'}
    link = mapping(details.get('post_create_readiness_evidence'))
    job_id = link.get('readiness_job_id')
    if job_id:
        job = get_job_run_strict(job_id)
        stored = mapping(mapping(mapping(job).get('details')).get('post_create_readiness_result'))
        artifact = mapping(stored.get('artifact'))
        linked_artifact = mapping(link.get('artifact'))
        if (stored.get('create_operation_id') != operation_id
                or stored.get('target') != {'node_id': target['node_id'], 'vmid': vmid}
                or artifact.get('artifact_id') != linked_artifact.get('artifact_id')
                or not artifact.get('checksum') or artifact.get('checksum') != linked_artifact.get('checksum')):
            raise PostCreateReadinessError('TEMPLATE_TEST_EVIDENCE_INVALID', '접속 증거의 소유 작업·대상·artifact가 일치하지 않습니다.')
        matching = [row for row in stored.get('checks', []) if isinstance(row, dict) and row.get('name') == 'access']
        if len(matching) == 1 and matching[0].get('status') in {'passed', 'failed', 'not_run', 'unavailable'}:
            access.update(status=matching[0]['status'], observed_at=matching[0].get('observed_at', ''),
                          artifact=linked_artifact, actor=mapping(stored.get('actor')))
    checks.append(access)
    coordinated = not result.get('coordination_incomplete') and not operation.get('coordination_incomplete')
    return {'operation_id': operation_id, 'operation_status': operation.get('status'),
            'target': target, 'template_source': mapping(details.get('template_source')),
            'power_policy': power_policy, 'historical': True, 'live_checks_performed': False,
            'checks': checks, 'all_checks_passed': coordinated and operation.get('status') == 'succeeded'
                and all(row['status'] == 'passed' for row in checks),
            'can_record_access': coordinated and operation.get('status') == 'succeeded',
            'cleanup': {'automatic': False, 'status': 'separate_review_required',
                        'instruction': '현재 VM을 다시 조회하고 정상 종료한 후 VMID/이름과 삭제 자원을 검토해 명시적으로 삭제하세요. 삭제 Operation에서 VMID·volume 부재를 확인하세요.'}}
