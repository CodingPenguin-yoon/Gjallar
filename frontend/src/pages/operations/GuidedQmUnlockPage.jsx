import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { AlertTriangle, Terminal } from 'lucide-react'
import { apiV1Client } from '../../shared/api/apiV1'
import { authFailureMessage } from '../../shared/auth/permissions'
import { buildGuidedQmUnlockPayload, newGuidedQmIdempotencyKey } from '../../features/guided-qm-unlock/model'

export default function GuidedQmUnlockPage({ canExecute = false }) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const initialNodeId = searchParams.get('node_id') || ''
  const initialVmid = searchParams.get('vmid') || ''
  const [form, setForm] = useState({ nodeId: initialNodeId, vmid: initialVmid, acknowledged: false })
  const [idempotencyKey, setIdempotencyKey] = useState(() => newGuidedQmIdempotencyKey(initialNodeId, initialVmid))
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const update = (field, value) => setForm((current) => ({ ...current, [field]: value }))

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      const payload = buildGuidedQmUnlockPayload({ ...form, idempotencyKey })
      const result = await apiV1Client.planGuidedQmVmUnlock(payload)
      navigate(`/operations/${encodeURIComponent(result.operation.operation_id)}`)
    } catch (err) {
      setError(authFailureMessage(err, 'Guided qm unlock 계획을 만들지 못했습니다.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="mx-auto max-w-3xl space-y-5">
      <div>
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500"><Terminal className="h-4 w-4" /> Guided manual</div>
        <h2 className="mt-2 text-3xl font-semibold text-slate-950">Plan qm unlock</h2>
        <p className="mt-2 text-sm text-slate-600">Gjallar가 사전 점검과 allowlisted instruction을 만들고, 실제 실행은 Proxmox node shell에서 운영자가 수행합니다.</p>
      </div>

      <form onSubmit={submit} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-1">
            <span className="text-sm font-semibold text-slate-700">Node ID</span>
            <input
              value={form.nodeId}
              onChange={(event) => update('nodeId', event.target.value)}
              placeholder="node-a"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="space-y-1">
            <span className="text-sm font-semibold text-slate-700">VMID</span>
            <input
              type="number"
              min="1"
              value={form.vmid}
              onChange={(event) => update('vmid', event.target.value)}
              placeholder="306"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
        </div>

        <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800">
          최종 명령과 plan digest는 사전 점검 후 backend가 생성합니다. Browser는 command 문자열을 요청에 포함하지 않습니다.
        </div>

        <label className="mt-4 flex items-start gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={form.acknowledged}
            onChange={(event) => update('acknowledged', event.target.checked)}
            disabled={!canExecute || submitting}
            className="mt-0.5 h-4 w-4 rounded border-slate-300"
          />
          <span>활성 task와 VM config lock을 점검한 뒤 `qm unlock` instruction이 발급되며, 실행 책임은 운영자에게 있음을 확인합니다.</span>
        </label>

        <details className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
          <summary className="cursor-pointer font-semibold">Request identity</summary>
          <div className="mt-2 break-all font-mono">{idempotencyKey}</div>
          <button type="button" onClick={() => setIdempotencyKey(newGuidedQmIdempotencyKey(form.nodeId, form.vmid))} className="mt-2 font-semibold text-blue-700">Generate new key</button>
        </details>

        {!canExecute ? (
          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">operator/admin 권한과 live Proxmox 연결이 필요합니다.</div>
        ) : null}
        {error ? (
          <div className="mt-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /><span>{error}</span></div>
        ) : null}

        <button
          type="submit"
          disabled={!canExecute || !form.acknowledged || submitting}
          className="mt-5 inline-flex items-center gap-2 rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
        >
          <Terminal className="h-4 w-4" />
          {submitting ? 'Planning...' : 'Create instruction bundle'}
        </button>
      </form>
    </section>
  )
}
