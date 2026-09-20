const sameTarget = (left, right) => left?.node_id === right?.node_id && left?.vmid === right?.vmid
const accessCheck = value => {
  const checks = Array.isArray(value?.checks) ? value.checks.filter(check => check?.name === 'access') : []
  return checks.length === 1 ? checks[0] : null
}

export function assertTemplateTestReport(report, operationId, target) {
  if (report?.operation_id !== operationId || report.historical !== true || report.live_checks_performed !== false
      || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(report.target?.node_id || '')
      || !Number.isInteger(report.target?.vmid) || report.target.vmid < 100 || report.target.vmid > 999999999
      || (target && !sameTarget(report.target, target))) {
    throw new Error('배포 검사 보고서의 생성 작업·대상이 일치하지 않습니다.')
  }
  return report
}

export function assertAccessEvidence(response, operationId, target, check) {
  const saved = accessCheck(response)
  const replayed = response?.idempotent_replay === true
  if (response?.operation?.operation_id !== operationId || response.create_operation_id !== operationId
      || response.operation_linked !== true || !sameTarget(response.target, target)
      || !['passed', 'failed', 'not_run', 'unavailable'].includes(saved?.status) || !saved?.observed_at
      || (!replayed && (saved.status !== check.status || saved.observed_at !== check.observed_at))
      || !response.artifact?.artifact_id || !response.artifact?.checksum) {
    throw new Error('저장한 접속 증거의 생성 작업·대상·확인 결과를 대조하지 못했습니다.')
  }
  return {artifact: response.artifact, check: saved, replayed}
}

export function assertRecordedAccess(report, operationId, target, check, artifact) {
  assertTemplateTestReport(report, operationId, target)
  const saved = accessCheck(report)
  if (saved?.status !== check.status || saved?.observed_at !== check.observed_at
      || saved?.artifact?.artifact_id !== artifact.artifact_id || saved?.artifact?.checksum !== artifact.checksum) {
    throw new Error('재조회한 보고서에 방금 저장한 접속 증거가 연결됐는지 확인하지 못했습니다.')
  }
  return report
}
