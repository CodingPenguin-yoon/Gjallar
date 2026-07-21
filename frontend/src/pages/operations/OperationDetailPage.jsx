import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AlertTriangle, ArrowLeft, RefreshCw } from 'lucide-react'
import { apiV1Client } from '../../shared/api/apiV1'
import { authFailureMessage } from '../../shared/auth/permissions'
import {
  formatOperationTime,
  normalizeOperationDetail,
  operationTypeLabel,
} from '../../entities/operation/model'
import OperationStatusBadge from '../../entities/operation/ui/OperationStatusBadge'
import GuidedQmOperationActions from '../../features/guided-qm-unlock/GuidedQmOperationActions'

export default function OperationDetailPage({ canExecute = false }) {
  const { operationId = '' } = useParams()
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadOperation = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setDetail(normalizeOperationDetail(await apiV1Client.getOperation(operationId)))
    } catch (err) {
      setError(authFailureMessage(err, 'Operation 상세를 불러오지 못했습니다.'))
    } finally {
      setLoading(false)
    }
  }, [operationId])

  useEffect(() => {
    loadOperation()
  }, [loadOperation])

  const acceptChanged = (next) => setDetail(normalizeOperationDetail(next))

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
          onClick={loadOperation}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 disabled:opacity-60"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      {error ? <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Status</div>
          <div className="mt-3"><OperationStatusBadge status={operation.status} /></div>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Target</div>
          <div className="mt-3 break-all font-mono text-sm text-slate-900">{operation.targetId}</div>
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

      <GuidedQmOperationActions detail={detail} canExecute={canExecute} onChanged={acceptChanged} />

      {detail.recovery || detail.targetLock ? (
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm" aria-labelledby="operation-recovery-title">
          <div>
            <h2 id="operation-recovery-title" className="text-xl font-semibold text-slate-950">Recovery coordination</h2>
            <p className="mt-1 text-sm text-slate-600">읽기 전용 복구 lease와 동일 target mutation 차단 상태입니다.</p>
          </div>
          <dl className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {detail.recovery ? (
              <>
                <div className="rounded-lg border border-slate-200 p-4">
                  <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Recovery status</dt>
                  <dd className="mt-2 font-semibold text-slate-950">{detail.recovery.status}</dd>
                  <dd className="mt-1 text-xs text-slate-500">{detail.recovery.kind}</dd>
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
        </section>
      ) : null}

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm" aria-labelledby="operation-timeline-title">
        <div className="flex items-end justify-between gap-3">
          <div>
            <h2 id="operation-timeline-title" className="text-xl font-semibold text-slate-950">Evidence timeline</h2>
            <p className="mt-1 text-sm text-slate-600">projection version {operation.version} · actor {operation.actor.username}</p>
          </div>
          <div className="text-xs text-slate-500">Updated {formatOperationTime(operation.updatedAt)}</div>
        </div>
        <ol className="mt-5 space-y-3">
          {detail.events.map((event) => (
            <li key={event.id || event.sequence} className="grid gap-2 rounded-lg border border-slate-200 p-4 sm:grid-cols-[3rem_minmax(0,1fr)_auto]">
              <div className="font-mono text-xs font-semibold text-slate-500">#{event.sequence}</div>
              <div>
                <div className="font-semibold text-slate-950">{event.type.replaceAll('_', ' ')}</div>
                <div className="mt-1 text-xs text-slate-500">{event.stage} · {event.actor?.username || 'system'} · {event.fromStatus || 'created'} → {event.toStatus}</div>
              </div>
              <time className="text-xs text-slate-500">{formatOperationTime(event.createdAt)}</time>
            </li>
          ))}
        </ol>
      </section>
    </section>
  )
}
