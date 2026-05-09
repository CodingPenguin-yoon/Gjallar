import { useMemo, useState } from 'react'
import { CheckCircle2, Loader2, ShieldCheck, AlertTriangle, FileText, Server } from 'lucide-react'
import { apiV1Client } from '../services/apiV1'
import { buildCreateVmDefaults } from '../utils/createVmDefaults'
import {
  approveCreateVmReview,
  buildCreateVmInputFromConfig,
  loadCreateVmReviewModel,
} from '../utils/createVmFlow'

function StatusPill({ tone = 'slate', children }) {
  const tones = {
    green: 'bg-green-50 text-green-700 border-green-200',
    yellow: 'bg-yellow-50 text-yellow-700 border-yellow-200',
    red: 'bg-red-50 text-red-700 border-red-200',
    blue: 'bg-blue-50 text-blue-700 border-blue-200',
    slate: 'bg-slate-50 text-slate-700 border-slate-200',
  }
  return <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium ${tones[tone] || tones.slate}`}>{children}</span>
}

function approvalToneClass(approval) {
  if (approval?.tone === 'green') return 'border-green-200 bg-green-50 text-green-700'
  if (approval?.tone === 'yellow') return 'border-yellow-200 bg-yellow-50 text-yellow-800'
  return 'border-red-200 bg-red-50 text-red-700'
}

function DetailRow({ label, value }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-slate-100 py-2 last:border-b-0">
      <span className="text-sm text-slate-500">{label}</span>
      <span className="text-sm font-medium text-slate-900 text-right break-all">{value || '—'}</span>
    </div>
  )
}

function buildInitialForm(config) {
  const defaults = buildCreateVmDefaults()
  const input = buildCreateVmInputFromConfig(config, {
    operatorId: 'ui-operator',
    jobId: `ui-${new Date().toISOString().slice(0, 10).replaceAll('-', '')}`,
    targetNodeId: 'yoonmanserver2',
    staticIp: '',
    ipMode: defaults.network.ipMode,
  })
  return {
    ...input,
    profileId: defaults.profileId,
    hardware: defaults.hardware,
    networkId: defaults.network.networkId,
  }
}

function CreateInstanceWizard({ config = {}, onConfigChange = () => {} }) {
  const [form, setForm] = useState(() => buildInitialForm(config))
  const [model, setModel] = useState(null)
  const [approval, setApproval] = useState(null)
  const [yellowRiskAcknowledged, setYellowRiskAcknowledged] = useState(false)
  const [loading, setLoading] = useState(false)
  const [approving, setApproving] = useState(false)
  const [error, setError] = useState(null)

  const riskTone = useMemo(() => {
    const level = model?.review?.riskLevel || model?.preflight?.level
    if (level === 'red') return 'red'
    if (level === 'yellow') return 'yellow'
    if (level === 'green') return 'green'
    return 'slate'
  }, [model])

  const updateForm = (field, value) => {
    const next = { ...form, [field]: value }
    setForm(next)
    onConfigChange(next)
  }

  const runReview = async () => {
    setLoading(true)
    setError(null)
    setApproval(null)
    try {
      const reviewModel = await loadCreateVmReviewModel(apiV1Client, form)
      setModel(reviewModel)
    } catch (err) {
      setError(err?.message || 'Create VM review failed')
      setModel(null)
    } finally {
      setLoading(false)
    }
  }

  const approveReview = async () => {
    if (!model?.review?.canApprove) return
    setApproving(true)
    setError(null)
    try {
      const result = await approveCreateVmReview(apiV1Client, model, { yellowRiskAcknowledged })
      setApproval(result)
    } catch (err) {
      setError(err?.message || 'Approval validation failed')
      setApproval(null)
    } finally {
      setApproving(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-blue-100 bg-blue-50 p-4">
        <div className="flex items-start gap-3">
          <ShieldCheck className="mt-0.5 h-5 w-5 text-blue-600" />
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Create VM review flow</h2>
            <p className="mt-1 text-sm text-slate-600">
              PRD v1 path: draft, preflight, dry-run plan, then approval metadata validation. Live run remains gated outside this screen.
            </p>
          </div>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <label className="space-y-1">
          <span className="text-sm font-medium text-slate-700">Operator</span>
          <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.operatorId} onChange={(event) => updateForm('operatorId', event.target.value)} />
        </label>
        <label className="space-y-1">
          <span className="text-sm font-medium text-slate-700">Job ID</span>
          <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.jobId} onChange={(event) => updateForm('jobId', event.target.value)} />
        </label>
        <label className="space-y-1">
          <span className="text-sm font-medium text-slate-700">Target node</span>
          <select className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.targetNodeId} onChange={(event) => updateForm('targetNodeId', event.target.value)}>
            <option value="yoonmanserver2">yoonmanserver2</option>
            <option value="yoonmanserver3">yoonmanserver3</option>
          </select>
        </label>
        <label className="space-y-1">
          <span className="text-sm font-medium text-slate-700">IP mode</span>
          <select className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.ipMode} onChange={(event) => updateForm('ipMode', event.target.value)}>
            <option value="static">static</option>
            <option value="dhcp">dhcp</option>
          </select>
        </label>
        <label className="space-y-1 md:col-span-2">
          <span className="text-sm font-medium text-slate-700">Static IP</span>
          <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.staticIp} onChange={(event) => updateForm('staticIp', event.target.value)} placeholder="192.168.2.149" disabled={form.ipMode === 'dhcp'} />
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={runReview} disabled={loading} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60">
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
          Build review packet
        </button>
        <StatusPill tone="blue">Validation only</StatusPill>
        <StatusPill tone="slate">No live mutation</StatusPill>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {model && (
        <div className="grid gap-4 lg:grid-cols-3">
          <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm lg:col-span-2">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Server className="h-5 w-5 text-slate-600" />
                <h3 className="font-semibold text-slate-900">Review & confirm</h3>
              </div>
              <StatusPill tone={riskTone}>{model.review.riskLevel}</StatusPill>
            </div>
            <DetailRow label="VM name" value={model.review.vmName} />
            <DetailRow label="VMID" value={model.review.vmid} />
            <DetailRow label="Target node" value={model.review.targetNode} />
            <DetailRow label="Storage" value={model.review.storage} />
            <DetailRow label="Template" value={model.review.template} />
            <DetailRow label="Hardware" value={`${model.review.hardware.cpu} CPU / ${model.review.hardware.memoryMb} MB / ${model.review.hardware.diskGb} GB`} />
            <DetailRow label="Network" value={`${model.review.network.ip_mode || model.review.network.ipMode || form.ipMode} / ${model.review.network.bridge_id || model.review.network.bridgeId || 'vmbr0'}`} />
            <DetailRow label="State path" value={model.review.terraformStatePath} />
            <DetailRow label="Plan artifact" value={model.review.planArtifactId} />
            <DetailRow label="Review checksum" value={model.review.reviewSummaryChecksum} />
          </section>

          <aside className="space-y-4">
            <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <h3 className="mb-3 font-semibold text-slate-900">Preflight checks</h3>
              <div className="space-y-2">
                {model.preflight.checks.map((check) => (
                  <div key={check.code} className="rounded-lg border border-slate-100 p-2 text-sm">
                    <div className="font-medium text-slate-800">{check.code}</div>
                    <div className="text-slate-500">{check.status} · {check.level}</div>
                  </div>
                ))}
              </div>
            </section>

            <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <h3 className="mb-3 font-semibold text-slate-900">Approval</h3>
              {model.review.riskLevel === 'yellow' && (
                <label className="mb-3 flex items-start gap-2 rounded-lg border border-yellow-200 bg-yellow-50 p-2 text-sm text-yellow-800">
                  <input type="checkbox" className="mt-1" checked={yellowRiskAcknowledged} onChange={(event) => setYellowRiskAcknowledged(event.target.checked)} />
                  I reviewed the yellow risk items.
                </label>
              )}
              <button type="button" onClick={approveReview} disabled={!model.review.canApprove || approving} className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60">
                {approving ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                Approve metadata
              </button>
              <p className="mt-2 text-xs text-slate-500">{model.review.executeDisabledReason}</p>
              {approval && (
                <div className={`mt-3 rounded-lg border p-3 text-sm ${approvalToneClass(approval)}`}>
                  {approval.operatorMessage}
                </div>
              )}
            </section>
          </aside>
        </div>
      )}

      {model?.review?.riskLevel === 'red' && (
        <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          <AlertTriangle className="mt-0.5 h-4 w-4" />
          Red risk blocks approval in this MVP flow.
        </div>
      )}
    </div>
  )
}

export default CreateInstanceWizard
