import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, RefreshCw, Terminal } from 'lucide-react'
import { apiV1Client } from '../../shared/api/apiV1'
import { authFailureMessage } from '../../shared/auth/permissions'
import { formatOperationTime } from '../../entities/operation/model'
import { guidedQmActionState } from './model'

export default function GuidedQmOperationActions({ detail, canExecute, onChanged }) {
  const operation = detail.operation
  const [nowMs, setNowMs] = useState(() => Date.now())
  const actionState = guidedQmActionState(operation, nowMs)
  const [executionAcknowledged, setExecutionAcknowledged] = useState(false)
  const [submitting, setSubmitting] = useState('')
  const [error, setError] = useState('')

  const bundle = detail.instructionBundle
  const command = bundle?.command?.display || ''

  useEffect(() => {
    const expiresMs = operation.expiresAt ? Date.parse(operation.expiresAt) : Number.NaN
    if (operation.status !== 'awaiting_operator' || !Number.isFinite(expiresMs) || expiresMs <= Date.now()) return undefined
    const timer = globalThis.setTimeout(() => setNowMs(Date.now()), Math.min(expiresMs - Date.now() + 50, 2_147_000_000))
    return () => globalThis.clearTimeout(timer)
  }, [operation.expiresAt, operation.status])

  if (!actionState.guided) return null

  const attest = async () => {
    if (!executionAcknowledged || !canExecute) return
    setSubmitting('attest')
    setError('')
    try {
      const next = await apiV1Client.attestOperation(operation.id, {
        plan_digest: operation.planDigest,
        command_executed: true,
      })
      setExecutionAcknowledged(false)
      onChanged(next)
    } catch (err) {
      setError(authFailureMessage(err, '실행 확인을 기록하지 못했습니다.'))
    } finally {
      setSubmitting('')
    }
  }

  const verify = async () => {
    if (!canExecute) return
    setSubmitting('verify')
    setError('')
    try {
      const next = await apiV1Client.verifyOperation(operation.id, { plan_digest: operation.planDigest })
      onChanged(next)
    } catch (err) {
      setError(authFailureMessage(err, 'Proxmox API 검증을 완료하지 못했습니다.'))
    } finally {
      setSubmitting('')
    }
  }

  return (
    <section className="rounded-xl border border-blue-200 bg-blue-50 p-5" aria-labelledby="guided-qm-actions-title">
      <div className="flex items-start gap-3">
        <Terminal className="mt-0.5 h-5 w-5 shrink-0 text-blue-700" />
        <div className="min-w-0 flex-1">
          <h2 id="guided-qm-actions-title" className="text-lg font-semibold text-slate-950">Guided qm handoff</h2>
          <p className="mt-1 text-sm text-slate-600">
            {actionState.lateAttestation
              ? '이 instruction은 더 이상 신규 실행에 사용할 수 없습니다. 이미 실행한 사실이 있을 때만 late evidence로 기록하세요.'
              : 'Gjallar는 이 명령을 실행하지 않습니다. 표시된 Proxmox node shell에서 운영자가 직접 실행한 뒤 결과를 확인합니다.'}
          </p>

          {actionState.lateAttestation ? (
            <div className="mt-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm font-semibold text-red-700">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>이 화면의 명령을 지금 실행하지 마세요. 새 plan을 발급하거나 이미 발생한 실행만 attest해야 합니다.</span>
            </div>
          ) : null}

          {command ? (
            <div className={`mt-4 rounded-lg border p-4 ${actionState.lateAttestation ? 'border-amber-300 bg-amber-100 text-amber-950' : 'border-slate-700 bg-slate-950 text-slate-100'}`}>
              <div className={`text-xs font-semibold uppercase tracking-wide ${actionState.lateAttestation ? 'text-amber-800' : 'text-slate-400'}`}>
                {actionState.lateAttestation ? 'Expired evidence — do not execute' : 'Allowlisted command'}
              </div>
              <code className="mt-2 block overflow-x-auto font-mono text-sm">{command}</code>
              <div className="mt-3 text-xs text-slate-400">Expires: {formatOperationTime(bundle?.expires_at || operation.expiresAt)}</div>
            </div>
          ) : (
            <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">Backend instruction bundle을 확인할 수 없습니다. 명령을 추정해서 실행하지 마세요.</div>
          )}

          {!canExecute ? (
            <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              operator/admin 권한과 live Proxmox 연결이 있어야 다음 단계를 수행할 수 있습니다.
            </div>
          ) : null}

          {error ? (
            <div className="mt-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          ) : null}

          {actionState.canAttest ? (
            <div className="mt-4 space-y-3">
              <label className="flex items-start gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={executionAcknowledged}
                  onChange={(event) => setExecutionAcknowledged(event.target.checked)}
                  disabled={!canExecute || Boolean(submitting)}
                  className="mt-0.5 h-4 w-4 rounded border-slate-300"
                />
                <span>{actionState.lateAttestation ? '이 명령을 이미 실행했으며, 지금은 신규 실행 없이 그 사실만 기록합니다.' : '위 명령을 지정된 Proxmox node shell에서 직접 실행했습니다.'}</span>
              </label>
              <button
                type="button"
                onClick={attest}
                disabled={!executionAcknowledged || !canExecute || Boolean(submitting)}
                className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
              >
                <CheckCircle2 className="h-4 w-4" />
                {submitting === 'attest' ? 'Recording...' : actionState.lateAttestation ? 'Record late execution evidence' : 'Record operator attestation'}
              </button>
            </div>
          ) : null}

          {actionState.canVerify ? (
            <button
              type="button"
              onClick={verify}
              disabled={!canExecute || Boolean(submitting)}
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
            >
              <RefreshCw className={`h-4 w-4 ${submitting === 'verify' ? 'animate-spin' : ''}`} />
              {submitting === 'verify' ? 'Verifying...' : 'Verify with Proxmox API'}
            </button>
          ) : null}
        </div>
      </div>
    </section>
  )
}
