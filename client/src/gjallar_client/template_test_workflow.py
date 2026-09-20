"""Inspect deployment evidence and record a bounded operator access result."""
from datetime import datetime, timezone
import re
from .errors import ClientError
from .workflows import request_identity, segment


def _same_target(left, right):
    return (isinstance(left, dict) and isinstance(right, dict)
            and left.get('node_id') == right.get('node_id') and left.get('vmid') == right.get('vmid'))


def _access_check(value):
    checks = value.get('checks') if isinstance(value, dict) else None
    matching = [row for row in checks if isinstance(row, dict) and row.get('name') == 'access'] if isinstance(checks, list) else []
    return matching[0] if len(matching) == 1 else {}


def show(app, operation_id):
    request_identity(operation_id)
    result = app.request(f'operations/{segment(operation_id)}/template-test')
    report = result.get('data')
    target = report.get('target') if isinstance(report, dict) else None
    if (not isinstance(report, dict) or report.get('operation_id') != operation_id
            or report.get('historical') is not True or report.get('live_checks_performed') is not False
            or not isinstance(target, dict) or not isinstance(target.get('node_id'), str)
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', target['node_id'])
            or type(target.get('vmid')) is not int or not 100 <= target['vmid'] <= 999999999):
        raise ClientError('TEMPLATE_TEST_REPORT_INVALID', '배포 검사 보고서의 생성 작업·대상을 확인할 수 없습니다.', 8)
    return result


def record_access(app, operation_id, *, status, request_id, acknowledged):
    request_identity(request_id)
    if status not in {'passed', 'failed', 'not_run', 'unavailable'} or acknowledged is not True:
        raise ClientError('ACCESS_EVIDENCE_ACK_REQUIRED', '직접 확인한 접속 결과와 운영자 증거 기록에 동의하세요.', 2)
    report = show(app, operation_id)['data']
    if report.get('can_record_access') is not True:
        raise ClientError('CREATE_NOT_VERIFIED', '생성 작업의 확정 결과와 증거 기록 가능 여부를 확인하세요.', 8)
    target = report.get('target', {})
    node, vmid = target.get('node_id'), target.get('vmid')
    check = {'name': 'access', 'status': status, 'observed_at': datetime.now(timezone.utc).isoformat()}
    result = app.request(f'nodes/{segment(node)}/vms/{vmid}/post-create-readiness-evidence', method='POST', operator=True,
        body={'create_operation_id': operation_id, 'idempotency_key': request_id,
                 'post_create_readiness_evidence_acknowledged': True,
                 'summary': '템플릿 테스트 배포의 운영자 접속 확인',
                 'limitations': '운영자 직접 확인. Gjallar 접속 실행 없음.',
                 'checks': [check]})
    evidence = result['data']
    artifact = evidence.get('artifact') or {}
    saved = _access_check(evidence)
    replayed = evidence.get('idempotent_replay') is True
    if (evidence.get('operation', {}).get('operation_id') != operation_id
            or evidence.get('create_operation_id') != operation_id or evidence.get('operation_linked') is not True
            or not _same_target(evidence.get('target'), target)
            or saved.get('status') not in {'passed', 'failed', 'not_run', 'unavailable'} or not saved.get('observed_at')
            or (not replayed and any(saved.get(key) != check[key] for key in ('status', 'observed_at')))
            or not isinstance(artifact, dict) or not artifact.get('artifact_id') or not artifact.get('checksum')):
        raise ClientError('EVIDENCE_LINK_UNCONFIRMED', '접속 결과와 생성 작업의 연결을 확인하지 못했습니다. 요청 ID와 증거 기록을 보존하세요.', 8)
    check = saved
    result = show(app, operation_id)
    current = result['data']
    saved = _access_check(current)
    linked = saved.get('artifact') or {}
    if (not _same_target(current.get('target'), target)
            or any(saved.get(key) != check[key] for key in ('status', 'observed_at'))
            or not isinstance(linked, dict)
            or any(linked.get(key) != artifact[key] for key in ('artifact_id', 'checksum'))):
        raise ClientError('EVIDENCE_LINK_UNCONFIRMED', '재조회한 보고서에 저장한 접속 증거가 연결됐는지 확인하지 못했습니다. 자동 재전송하지 않았습니다.', 8)
    if replayed:
        return {**result, 'idempotent_replay': True, 'message': '같은 요청 ID에 저장된 기존 접속 결과를 확인했습니다.'}
    return result
