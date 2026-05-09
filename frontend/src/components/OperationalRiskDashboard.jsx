import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, FileText, RefreshCw, Search, ShieldCheck } from 'lucide-react'
import { apiV1Client } from '../services/apiV1'
import { loadRisksScreenModel, riskLevelLabel, riskToneClass } from '../utils/risksScreen'

function SummaryCard({ label, value, level = 'unknown' }) {
  return (
    <div className={`rounded-xl border p-4 ${riskToneClass(level)}`}>
      <div className="text-xs font-semibold uppercase tracking-wide opacity-75">{label}</div>
      <div className="mt-2 text-2xl font-bold">{value}</div>
    </div>
  )
}

function RiskBadge({ level }) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${riskToneClass(level)}`}>
      {riskLevelLabel(level)}
    </span>
  )
}

function RiskCard({ risk }) {
  return (
    <article className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <RiskBadge level={risk.level} />
            <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-600">
              {risk.code}
            </span>
          </div>
          <h3 className="mt-3 text-base font-semibold text-slate-900">{risk.message || 'Risk requires operator review'}</h3>
          <div className="mt-2 text-sm text-slate-600">Risk ID: {risk.id}</div>
          {risk.jobId && <div className="mt-1 text-sm text-slate-600">Job: {risk.jobId}</div>}
        </div>
        {risk.artifactsUrl && (
          <a
            href={risk.artifactsUrl}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            <FileText className="h-4 w-4" />
            Artifacts
          </a>
        )}
      </div>
    </article>
  )
}

function filterRisks(items, query) {
  const normalized = query.trim().toLowerCase()
  if (!normalized) return items
  return items.filter((risk) => [risk.id, risk.jobId, risk.level, risk.code, risk.message].some((value) => String(value ?? '').toLowerCase().includes(normalized)))
}

function OperationalRiskDashboard() {
  const [model, setModel] = useState(null)
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const loadModel = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setModel(await loadRisksScreenModel(apiV1Client))
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to load Risks')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadModel()
  }, [loadModel])

  const summary = model?.summary || { total: 0, red: 0, yellow: 0, green: 0, unknown: 0 }
  const risks = useMemo(() => filterRisks(model?.items || [], query), [model, query])

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-red-600">
            <AlertTriangle className="h-4 w-4" />
            PRD /api/v1
          </div>
          <h1 className="mt-1 text-2xl font-bold text-slate-900">Risks / Alerts</h1>
          <p className="mt-2 max-w-2xl text-sm text-slate-600">
            Read-only view of risks emitted by VM create preflight, plan, and approval boundaries. Risk policy changes are outside this MVP screen.
          </p>
        </div>
        <button
          type="button"
          onClick={loadModel}
          className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <SummaryCard label="Total" value={summary.total} />
        <SummaryCard label="Red" value={summary.red} level="red" />
        <SummaryCard label="Yellow" value={summary.yellow} level="yellow" />
        <SummaryCard label="Green" value={summary.green} level="green" />
        <SummaryCard label="Unknown" value={summary.unknown} />
      </div>

      <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800">
        <div className="flex items-start gap-2">
          <ShieldCheck className="mt-0.5 h-4 w-4" />
          <div>
            <div className="font-semibold">Read-only safety boundary</div>
            <div>This screen can inspect risk evidence only. It has no policy edit, local exception, or live action controls.</div>
          </div>
        </div>
      </div>

      {error && <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>}

      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Filter risks by id, job, level, code, message"
          className="w-full rounded-lg border border-slate-300 bg-white py-2 pl-9 pr-3 text-sm outline-none focus:border-red-500 focus:ring-2 focus:ring-red-100"
        />
      </div>

      {loading && !model ? (
        <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500">Loading risks…</div>
      ) : risks.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">No risks match the current filter.</div>
      ) : (
        <div className="space-y-3">
          {risks.map((risk) => <RiskCard key={risk.id} risk={risk} />)}
        </div>
      )}
    </div>
  )
}

export default OperationalRiskDashboard
