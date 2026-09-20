import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AlertTriangle, ArrowLeft, Eye, RefreshCw } from 'lucide-react'
import { apiV1Client } from '../../shared/api/apiV1'
import { authFailureMessage } from '../../shared/auth/permissions'
import { vmDetailPathFromTarget } from '../../shared/navigation/targetPaths'
import {
  buildRecoveryObservationPayload,
  createOperationRequestGuard,
  formatOperationTime,
  isTargetLockOpen,
  normalizeOperationDetail,
  OPERATION_POLL_INTERVAL_MS,
  OPERATION_POLL_MAX_ATTEMPTS,
  operationTypeLabel,
  recoveryObserveAction,
  shouldPollOperation,
  TERMINAL_OPERATION_STATUSES,
} from '../../entities/operation/model'
import OperationStatusBadge from '../../entities/operation/ui/OperationStatusBadge'
import GuidedQmOperationActions from '../../features/guided-qm-unlock/GuidedQmOperationActions'

export default function OperationDetailPage({ canExecute = false, canObserveRecovery = canExecute }) {
  const { operationId = '' } = useParams()
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [recoveryActionPending, setRecoveryActionPending] = useState(false)
  const pollAttemptsRef = useRef(0)
  const requestGuardRef = useRef(null)
  if (!requestGuardRef.current) requestGuardRef.current = createOperationRequestGuard()

  const loadOperation = useCallback(async ({ background = false } = {}) => {
    const requestGeneration = requestGuardRef.current.next()
    if (!background) setLoading(true)
    setError('')
    try {
      const nextDetail = normalizeOperationDetail(await apiV1Client.getOperation(operationId))
      if (!requestGuardRef.current.isCurrent(requestGeneration)) return null
      setDetail(nextDetail)
      return nextDetail
    } catch (err) {
      if (!requestGuardRef.current.isCurrent(requestGeneration)) return null
      setError(authFailureMessage(err, 'Operation 상세를 불러오지 못했습니다.'))
      return null
    } finally {
      if (!background && requestGuardRef.current.isCurrent(requestGeneration)) setLoading(false)
    }
  }, [operationId])

  useEffect(() => {
    pollAttemptsRef.current = 0
    setDetail(null)
    loadOperation()
    return () => requestGuardRef.current.invalidate()
  }, [loadOperation])

  const operationStatus = detail?.operation?.status || ''
  const operationVersion = detail?.operation?.version || 0
  const operationUpdatedAt = detail?.operation?.updatedAt || ''
  const recoveryStatus = detail?.recovery?.status || ''
  const targetLockStatus = detail?.targetLock?.status || ''

  useEffect(() => {
    if (
      !detail
      || error
      || loading
      || recoveryActionPending
      || !shouldPollOperation(operationStatus, pollAttemptsRef.current, detail)
    ) return undefined

    const timer = window.setTimeout(() => {
      pollAttemptsRef.current += 1
      loadOperation({ background: true })
    }, OPERATION_POLL_INTERVAL_MS)

    return () => window.clearTimeout(timer)
  }, [detail, error, loadOperation, loading, operationStatus, operationUpdatedAt, operationVersion, recoveryActionPending, recoveryStatus, targetLockStatus])

  const refreshOperation = () => {
    pollAttemptsRef.current = 0
    setRecoveryActionPending(false)
    loadOperation()
  }

  const acceptChanged = () => {
    requestGuardRef.current.invalidate()
    pollAttemptsRef.current = 0
    setRecoveryActionPending(false)
    setError('')
    loadOperation({ background: true })
  }

  const observeRecovery = async () => {
    const action = recoveryObserveAction(detail)
    if (!canObserveRecovery || !action || recoveryActionPending) return
    const requestGeneration = requestGuardRef.current.next()
    setRecoveryActionPending(true)
    setError('')
    try {
      const payload = buildRecoveryObservationPayload(detail.operation)
      const next = normalizeOperationDetail(await apiV1Client.observeOperationRecovery(detail.operation.id, payload))
      if (!requestGuardRef.current.isCurrent(requestGeneration)) return
      pollAttemptsRef.current = 0
      setDetail(next)
    } catch (err) {
      if (!requestGuardRef.current.isCurrent(requestGeneration)) return
      setError(authFailureMessage(err, 'Recovery evidence를 다시 관찰하지 못했습니다.'))
    } finally {
      if (requestGuardRef.current.isCurrent(requestGeneration)) setRecoveryActionPending(false)
    }
  }

  if (loading && !detail) return <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">Loading operation...</div>

  if (!detail) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-5 text-red-700">
        <div className="flex items-start gap-2"><AlertTriangle className="mt-0.5 h-4 w-4" /><span>{error}</span></div>
        <Link to="/operations" className="mt-4 inline-flex font-semibold text-blue-700">Back to Operations</Link>
      </div>
    )
  }

  const operation = detail.operation
  const targetPath = vmDetailPathFromTarget(operation.targetType, operation.targetId)
  const createReadiness = detail.createReadiness
  const readinessChecks = Object.entries(createReadiness?.readiness?.checks || {})
  const observeAction = recoveryObserveAction(detail)
  const recoveryActions = detail.recovery?.availableActions?.length > 0
    ? detail.recovery.availableActions
    : detail.recoveryAvailableActions
  const manualRecoveryActionRequired = detail.recovery?.manualActionRequired === true
  const terminalWithOpenTargetLock = TERMINAL_OPERATION_STATUSES.includes(operation.status)
    && isTargetLockOpen(detail.targetLock)

  return (
    <section className="space-y-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <Link to="/operations" className="inline-flex items-center gap-2 text-sm font-semibold text-slate-600 hover:text-slate-950">
            <ArrowLeft className="h-4 w-4" /> Operations
          </Link>
          <h2 className="mt-3 text-3xl font-semibold text-slate-950">{operationTypeLabel(operation.type)}</h2>
          <div className="mt-2 break-all font-mono text-xs text-slate-500">{operation.id}</div>
        </div>
        <button
          type="button"
          onClick={refreshOperation}
          disabled={loading || recoveryActionPending}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 disabled:opacity-60"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      {error ? <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}

      {terminalWithOpenTargetLock ? (
        <div className="flex items-start gap-2 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <div className="font-semibold">Operation은 terminal이지만 target lock이 아직 열려 있습니다.</div>
            <div className="mt-1">동일 target mutation은 계속 차단됩니다. Recovery coordination이 완료되거나 운영자 판단이 기록되기 전에는 새 mutation을 재시도하지 마세요.</div>
          </div>
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Status</div>
          <div className="mt-3"><OperationStatusBadge status={operation.status} /></div>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Target</div>
          {targetPath ? (
            <Link to={targetPath} className="mt-3 block break-all font-mono text-sm font-semibold text-blue-800 hover:text-blue-950 hover:underline">
              {operation.targetId}
            </Link>
          ) : (
            <div className="mt-3 break-all font-mono text-sm text-slate-900">{operation.targetId}</div>
          )}
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Execution mode</div>
          <div className="mt-3 text-sm font-semibold text-slate-900">{operation.executionMode}</div>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Current stage</div>
          <div className="mt-3 text-sm font-semibold text-slate-900">{operation.stage}</div>
        </div>
      </div>

      <GuidedQmOperationActions
        detail={detail}
        canAttest={canObserveRecovery}
        canVerifyWithProxmox={canExecute}
        onChanged={acceptChanged}
      />

      {operation.type === 'vm_restore' && operation.status === 'succeeded' && <Link className="block rounded-xl border border-slate-200 bg-white p-5 text-sm font-semibold underline" to={`/instances/restore-tests/${encodeURIComponent(operation.id)}`}>별도 VM 복원 검사·현재 원본/백업 보존·부팅 안내</Link>}
      {operation.type === 'vm_create' && createReadiness ? (
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm" aria-labelledby="create-readiness-title">
          <div>
            <h2 id="create-readiness-title" className="text-xl font-semibold text-slate-950">Post-create readiness evidence</h2>
            <p className="mt-1 text-sm text-slate-600">Create Operation이 소유한 관찰 결과와 artifact checksum입니다.</p>
            <Link className="mt-2 inline-block text-sm font-semibold underline" to={`/instances/templates/tests/${encodeURIComponent(operation.id)}`}>배포 검사·접속 결과 기록·테스트 VM 정리</Link>
          </div>
          <dl className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-lg border border-slate-200 p-4">
              <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Observed VM</dt>
              <dd className="mt-2 font-semibold text-slate-950">{createReadiness.exists ? 'exists' : 'not confirmed'} · {createReadiness.status || 'unknown'}</dd>
              {createReadiness.fingerprintHash ? <dd className="mt-1 break-all font-mono text-xs text-slate-500">{createReadiness.fingerprintHash}</dd> : null}
            </div>
            <div className="rounded-lg border border-slate-200 p-4">
              <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Workload</dt>
              {targetPath ? (
                <dd className="mt-2"><Link to={targetPath} className="break-all font-mono text-sm font-semibold text-blue-800 hover:underline">{createReadiness.workload.id || operation.targetId}</Link></dd>
              ) : (
                <dd className="mt-2 break-all font-mono text-sm text-slate-900">{createReadiness.workload.id || operation.targetId}</dd>
              )}
              <dd className="mt-1 text-xs text-slate-500">{createReadiness.workload.status || 'status not projected'}</dd>
            </div>
            <div className="rounded-lg border border-slate-200 p-4">
              <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Readiness</dt>
              <dd className="mt-2 font-semibold text-slate-950">{createReadiness.readiness.postCheckStatus || 'recorded'}</dd>
              {createReadiness.readiness.message ? <dd className="mt-1 text-xs text-slate-500">{createReadiness.readiness.message}</dd> : null}
            </div>
            <div className="rounded-lg border border-slate-200 p-4">
              <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Observed-after artifact</dt>
              <dd className="mt-2 break-all font-mono text-xs text-slate-900">{createReadiness.artifact.id || 'not recorded'}</dd>
              <dd className="mt-1 break-all font-mono text-xs text-slate-500">{createReadiness.artifact.checksum || 'checksum unavailable'}</dd>
            </div>
          </dl>
          {readinessChecks.length > 0 ? (
            <ul className="mt-4 grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
              {readinessChecks.map(([name, passed]) => (
                <li key={name} className={`rounded-lg border px-3 py-2 ${passed ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-amber-200 bg-amber-50 text-amber-800'}`}>
                  <span className="font-semibold">{name.replaceAll('_', ' ')}</span>: {passed ? 'verified' : 'not verified'}
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm" aria-labelledby="operation-integrity-title">
        <div>
          <h2 id="operation-integrity-title" className="text-xl font-semibold text-slate-950">Evidence integrity</h2>
          <p className="mt-1 text-sm text-slate-600">계획 의도와 append-only event chain을 식별하는 digest입니다.</p>
        </div>
        <dl className="mt-5 grid gap-4 lg:grid-cols-3">
          <div className="rounded-lg border border-slate-200 p-4">
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Intent digest</dt>
            <dd className="mt-2 break-all font-mono text-xs text-slate-900">{operation.intentDigest || '-'}</dd>
          </div>
          <div className="rounded-lg border border-slate-200 p-4">
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Plan digest</dt>
            <dd className="mt-2 break-all font-mono text-xs text-slate-900">{operation.planDigest || '-'}</dd>
          </div>
          <div className="rounded-lg border border-slate-200 p-4">
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Last event checksum</dt>
            <dd className="mt-2 break-all font-mono text-xs text-slate-900">{operation.lastEventChecksum || '-'}</dd>
          </div>
        </dl>
      </section>

      {detail.recovery || detail.targetLock || detail.coordinationIncomplete || recoveryActions.length > 0 ? (
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm" aria-labelledby="operation-recovery-title">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 id="operation-recovery-title" className="text-xl font-semibold text-slate-950">Recovery coordination</h2>
              <p className="mt-1 text-sm text-slate-600">읽기 전용 복구 lease와 동일 target mutation 차단 상태입니다.</p>
            </div>
            {observeAction && canObserveRecovery ? (
              <div className="shrink-0 sm:text-right">
                <button
                  type="button"
                  onClick={observeRecovery}
                  disabled={recoveryActionPending || loading}
                  className="inline-flex items-center gap-2 rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <Eye className={`h-4 w-4 ${recoveryActionPending ? 'animate-pulse' : ''}`} />
                  {recoveryActionPending ? '관찰 중...' : '다시 관찰'}
                </button>
                <div className="mt-1 text-xs text-slate-500">GET-only evidence observation · mutation 재호출 없음</div>
              </div>
            ) : null}
          </div>
          <dl className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {detail.recovery ? (
              <>
                <div className="rounded-lg border border-slate-200 p-4">
                  <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Recovery status</dt>
                  <dd className="mt-2 font-semibold text-slate-950">{detail.recovery.status}</dd>
                  <dd className="mt-1 text-xs text-slate-500">{detail.recovery.kind}</dd>
                  {detail.recovery.phase ? <dd className="mt-1 text-xs text-slate-500">phase {detail.recovery.phase}</dd> : null}
                </div>
                <div className="rounded-lg border border-slate-200 p-4">
                  <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Attempts</dt>
                  <dd className="mt-2 font-semibold text-slate-950">{detail.recovery.attemptCount}</dd>
                  <dd className="mt-1 text-xs text-slate-500">Next {formatOperationTime(detail.recovery.availableAt)}</dd>
                </div>
                <div className="rounded-lg border border-slate-200 p-4">
                  <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Observer lease</dt>
                  <dd className="mt-2 break-all font-mono text-xs text-slate-900">{detail.recovery.leaseOwner || 'unclaimed'}</dd>
                  <dd className="mt-1 text-xs text-slate-500">generation {detail.recovery.leaseGeneration} · until {formatOperationTime(detail.recovery.leaseExpiresAt)}</dd>
                </div>
              </>
            ) : null}
            {detail.targetLock ? (
              <div className="rounded-lg border border-slate-200 p-4">
                <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Target lock</dt>
                <dd className="mt-2 font-semibold text-slate-950">{detail.targetLock.status}</dd>
                <dd className="mt-1 break-all text-xs text-slate-500">{detail.targetLock.operationType} · {detail.targetLock.ownerId}</dd>
              </div>
            ) : null}
          </dl>
          {detail.recovery?.lastErrorCode ? (
            <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              Last recovery error: <span className="font-mono">{detail.recovery.lastErrorCode}</span>
            </div>
          ) : null}
          {detail.recovery?.reason ? (
            <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
              <span className="font-semibold">Recovery reason:</span> {detail.recovery.reason.replaceAll('_', ' ')}
            </div>
          ) : null}
          {detail.coordinationIncomplete && !detail.recovery ? (
            <div className="mt-4 flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <div className="font-semibold">Durable recovery item이 아직 준비되지 않았습니다.</div>
                <div className="mt-1">
                  {observeAction
                    ? '동일 Operation evidence version을 기준으로 GET-only 관찰만 요청할 수 있습니다. 원래 mutation은 재호출하지 않습니다.'
                    : '이 상태에는 자동 관찰이 승인되지 않았습니다. 기존 evidence와 exact target lock을 action별 절차로 수동 판단해야 합니다.'}
                </div>
              </div>
            </div>
          ) : null}
          {manualRecoveryActionRequired ? (
            <div className="mt-4 flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <div className="font-semibold">자동 recovery와 polling이 중지되었습니다.</div>
                <div className="mt-1">Mutation은 자동 재호출되지 않습니다. 최신 evidence를 다시 관찰할 수 있으면 operator가 “다시 관찰”을 요청하고, 그 밖의 ambiguity는 수동 판단이 필요합니다.</div>
              </div>
            </div>
          ) : null}
          {observeAction && !canObserveRecovery ? (
            <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              읽기 전용 “다시 관찰”은 operator/admin 권한이 필요합니다. Authoritative Proxmox GET이 필요한 복구는 연결 불가 시 안전하게 실패합니다.
            </div>
          ) : null}
          {recoveryActions.length > 0 ? (
            <div className="mt-4 rounded-lg border border-slate-200 p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Available actions</div>
              <ul className="mt-2 space-y-2 text-sm text-slate-700">
                {recoveryActions.map((action) => (
                  <li key={action.id}>
                    <span className="font-semibold">{action.label}</span>
                    {!action.enabled ? <span className="ml-2 text-amber-700">현재 사용할 수 없음</span> : null}
                    {action.description ? <div className="mt-0.5 text-xs text-slate-500">{action.description}</div> : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {Object.keys(detail.recovery?.latestObservation || {}).length > 0 ? (
            <details className="mt-4 rounded-lg border border-slate-200 bg-white" open={manualRecoveryActionRequired}>
              <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-700">Latest recovery observation</summary>
              <pre className="max-h-80 overflow-auto border-t border-slate-200 bg-slate-950 p-4 text-xs text-slate-100">{JSON.stringify(detail.recovery.latestObservation, null, 2)}</pre>
            </details>
          ) : null}
          {Object.keys(detail.recovery?.details || {}).length > 0 ? (
            <details className="mt-4 rounded-lg border border-slate-200 bg-white">
              <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-700">Recovery details</summary>
              <pre className="max-h-80 overflow-auto border-t border-slate-200 bg-slate-950 p-4 text-xs text-slate-100">{JSON.stringify(detail.recovery.details, null, 2)}</pre>
            </details>
          ) : null}
        </section>
      ) : null}

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm" aria-labelledby="operation-timeline-title">
        <div className="flex items-end justify-between gap-3">
          <div>
            <h2 id="operation-timeline-title" className="text-xl font-semibold text-slate-950">Evidence timeline</h2>
            <p className="mt-1 text-sm text-slate-600">projection version {operation.version} · actor {operation.actor.username}</p>
          </div>
          <div className="text-right text-xs text-slate-500">
            <div>Updated {formatOperationTime(operation.updatedAt)}</div>
            {shouldPollOperation(operation.status, pollAttemptsRef.current, detail) && !error ? (
              <div className="mt-1 text-blue-700">Auto-refreshing every {OPERATION_POLL_INTERVAL_MS / 1000}s</div>
            ) : pollAttemptsRef.current >= OPERATION_POLL_MAX_ATTEMPTS ? (
              <div className="mt-1 text-amber-700">Auto-refresh paused after {OPERATION_POLL_MAX_ATTEMPTS} attempts</div>
            ) : null}
          </div>
        </div>
        <ol className="mt-5 space-y-3">
          {detail.events.map((event) => (
            <li key={event.id || event.sequence} className="grid gap-2 rounded-lg border border-slate-200 p-4 sm:grid-cols-[3rem_minmax(0,1fr)_auto]">
              <div className="font-mono text-xs font-semibold text-slate-500">#{event.sequence}</div>
              <div>
                <div className="font-semibold text-slate-950">{event.type.replaceAll('_', ' ')}</div>
                <div className="mt-1 text-xs text-slate-500">{event.stage} · {event.actor?.username || 'system'} · {event.fromStatus || 'created'} → {event.toStatus}</div>
                <dl className="mt-3 grid gap-2 rounded-md bg-slate-50 p-3 text-xs sm:grid-cols-2">
                  <div>
                    <dt className="font-semibold uppercase tracking-wide text-slate-500">Previous checksum</dt>
                    <dd className="mt-1 break-all font-mono text-slate-700">{event.previousChecksum || 'chain root'}</dd>
                  </div>
                  <div>
                    <dt className="font-semibold uppercase tracking-wide text-slate-500">Event checksum</dt>
                    <dd className="mt-1 break-all font-mono text-slate-700">{event.checksum || '-'}</dd>
                  </div>
                </dl>
                {Object.keys(event.payload).length > 0 ? (
                  <details className="mt-3 rounded-md border border-slate-200 bg-white">
                    <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-slate-700">Event payload</summary>
                    <pre className="max-h-80 overflow-auto border-t border-slate-200 bg-slate-950 p-3 text-xs text-slate-100">{JSON.stringify(event.payload, null, 2)}</pre>
                  </details>
                ) : (
                  <div className="mt-3 text-xs text-slate-500">Event payload: none</div>
                )}
              </div>
              <time className="text-xs text-slate-500">{formatOperationTime(event.createdAt)}</time>
            </li>
          ))}
        </ol>
      </section>
    </section>
  )
}
