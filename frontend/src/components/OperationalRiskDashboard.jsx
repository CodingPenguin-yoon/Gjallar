import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Database, Info, Loader2, RefreshCw, Save, Server, ShieldCheck, SlidersHorizontal } from 'lucide-react'
import { getOperationalRisks, updateOperationalRiskThresholds } from '../services/api'
import {
  formatGeneratedAt,
  formatRiskScope,
  getRiskCategoryLabel,
  getRiskSeverityTone,
  groupRisksByCategory,
  normalizeRiskDashboard,
  normalizeRiskThresholds,
  serializeRiskThresholds,
  sortRiskItems,
  validateRiskThresholdDraft,
} from '../utils/operationalRisk'

function RiskSummaryCard({ label, value, severity, description }) {
  const tone = getRiskSeverityTone(severity)
  return (
    <div className={`rounded-lg border p-4 ${tone.cardClass}`}>
      <div className="text-xs uppercase tracking-wide opacity-80">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
      {description && <div className="mt-1 text-xs opacity-80">{description}</div>}
    </div>
  )
}

function ThresholdInput({ label, name, unit, value, onChange }) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-slate-600">{label}</span>
      <div className="mt-1 flex overflow-hidden rounded-md border border-slate-300 bg-white focus-within:border-red-400 focus-within:ring-1 focus-within:ring-red-400">
        <input
          type="number"
          min="1"
          step="1"
          value={value ?? ''}
          onChange={(event) => onChange(name, event.target.value)}
          className="w-full border-0 px-3 py-2 text-sm text-slate-900 outline-none"
        />
        <span className="flex items-center border-l border-slate-200 bg-slate-50 px-2 text-xs text-slate-500">{unit}</span>
      </div>
    </label>
  )
}

function ThresholdEditor({ draft, onChange, onSave, saving, status }) {
  const validation = validateRiskThresholdDraft(draft)
  const fields = [
    { label: 'Storage warning', name: 'storageWarningPercent', unit: '%' },
    { label: 'Storage critical', name: 'storageCriticalPercent', unit: '%' },
    { label: 'Snapshot warning', name: 'snapshotWarningDays', unit: 'days' },
    { label: 'Snapshot critical', name: 'snapshotCriticalDays', unit: 'days' },
    { label: 'Backup recency', name: 'backupWarningDays', unit: 'days' },
    { label: 'Stopped warning', name: 'stoppedWarningDays', unit: 'days' },
    { label: 'Stopped critical', name: 'stoppedCriticalDays', unit: 'days' },
  ]

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
            <SlidersHorizontal className="h-4 w-4 text-slate-500" />
            Risk thresholds
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Local Gjallar policy. Saving changes only updates Gjallar&apos;s DB; it does not mutate Proxmox resources.
          </p>
        </div>
        <button
          onClick={onSave}
          disabled={saving || !validation.valid}
          className="inline-flex items-center gap-2 rounded-md border border-red-200 bg-red-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          Save thresholds
        </button>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {fields.map((field) => (
          <ThresholdInput
            key={field.name}
            label={field.label}
            name={field.name}
            unit={field.unit}
            value={draft[field.name]}
            onChange={onChange}
          />
        ))}
      </div>
      {!validation.valid && <div className="mt-3 text-xs font-medium text-red-700">{validation.message}</div>}
      {status && (
        <div className={`mt-3 text-xs font-medium ${status.kind === 'error' ? 'text-red-700' : 'text-green-700'}`}>
          {status.message}
        </div>
      )}
    </div>
  )
}

function RiskItemCard({ item }) {
  const tone = getRiskSeverityTone(item.severity)
  const category = getRiskCategoryLabel(item.category)
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`inline-flex items-center rounded-full border px-2 py-1 text-xs font-semibold ${tone.badgeClass}`}>
              <span className={`mr-1.5 h-2 w-2 rounded-full ${tone.dotClass}`} />
              {tone.label}
            </span>
            <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-xs font-medium text-slate-600">
              {category}
            </span>
            <span className="text-xs text-slate-500">{formatRiskScope(item)}</span>
          </div>
          <h3 className="mt-3 text-sm font-semibold text-slate-900">{item.title}</h3>
          <p className="mt-1 text-sm text-slate-600">{item.detail}</p>
          <p className="mt-2 text-sm text-slate-700">
            <span className="font-medium">Recommendation:</span> {item.recommendation}
          </p>
        </div>
        {item.evidence && Object.keys(item.evidence).length > 0 && (
          <div className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-600 lg:max-w-xs">
            <div className="mb-1 font-semibold text-slate-700">Evidence</div>
            {Object.entries(item.evidence).slice(0, 4).map(([key, value]) => (
              <div key={key} className="flex gap-2">
                <span className="shrink-0 text-slate-400">{key}:</span>
                <span className="truncate">{Array.isArray(value) ? value.join(', ') || 'none' : String(value)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function OperationalRiskDashboard() {
  const [dashboard, setDashboard] = useState(null)
  const [thresholdDraft, setThresholdDraft] = useState(normalizeRiskThresholds({}))
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [savingThresholds, setSavingThresholds] = useState(false)
  const [thresholdStatus, setThresholdStatus] = useState(null)
  const [error, setError] = useState(null)

  const fetchRisks = async () => {
    try {
      setRefreshing(true)
      setError(null)
      const response = await getOperationalRisks()
      const payload = response.data || {}
      setDashboard(normalizeRiskDashboard(payload))
      setThresholdDraft(normalizeRiskThresholds(payload.thresholds || payload.threshold_config?.thresholds || {}))
    } catch (err) {
      console.error('Failed to fetch operational risks:', err)
      setError(err.response?.data?.detail || err.message || 'Failed to fetch operational risks')
      setDashboard(normalizeRiskDashboard({}))
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    fetchRisks()
    const interval = setInterval(fetchRisks, 60000)
    return () => clearInterval(interval)
  }, [])

  const handleThresholdChange = (name, value) => {
    setThresholdStatus(null)
    setThresholdDraft((current) => ({ ...current, [name]: value }))
  }

  const saveThresholds = async () => {
    const validation = validateRiskThresholdDraft(thresholdDraft)
    if (!validation.valid) {
      setThresholdStatus({ kind: 'error', message: validation.message })
      return
    }
    try {
      setSavingThresholds(true)
      setThresholdStatus(null)
      const response = await updateOperationalRiskThresholds(serializeRiskThresholds(thresholdDraft))
      setThresholdDraft(normalizeRiskThresholds(response.data?.thresholds || {}))
      setThresholdStatus({ kind: 'success', message: 'Thresholds saved to Gjallar DB.' })
      await fetchRisks()
    } catch (err) {
      console.error('Failed to update risk thresholds:', err)
      setThresholdStatus({ kind: 'error', message: err.response?.data?.detail || err.message || 'Failed to save thresholds' })
    } finally {
      setSavingThresholds(false)
    }
  }

  const normalized = dashboard || normalizeRiskDashboard({})
  const sortedRisks = useMemo(() => sortRiskItems(normalized.riskItems), [normalized.riskItems])
  const categoryGroups = useMemo(() => groupRisksByCategory(sortedRisks), [sortedRisks])
  const statusTone = getRiskSeverityTone(normalized.status)

  return (
    <div className="p-6">
      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
            <AlertTriangle className="h-5 w-5 text-red-600" />
            Operational Risk Dashboard
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            Read-only risk signals for VM operations, storage capacity, snapshots, backups, and governance.
          </p>
        </div>
        <button
          onClick={fetchRisks}
          disabled={refreshing}
          className="flex items-center gap-2 rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-red-600" />
          <span className="ml-3 text-slate-600">Loading operational risks...</span>
        </div>
      ) : (
        <div className="space-y-6">
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex items-center gap-3">
                <div className={`rounded-full border px-3 py-1 text-sm font-semibold ${statusTone.badgeClass}`}>
                  Overall: {statusTone.label}
                </div>
                <div className="text-sm text-slate-500">Generated: {formatGeneratedAt(normalized.generatedAt)}</div>
              </div>
              <div className="text-sm text-slate-500">
                {normalized.summary.totalVms} VMs / {normalized.summary.totalNodes} nodes assessed · auto-refresh every 60s
              </div>
            </div>
          </div>

          <ThresholdEditor
            draft={thresholdDraft}
            onChange={handleThresholdChange}
            onSave={saveThresholds}
            saving={savingThresholds}
            status={thresholdStatus}
          />

          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <RiskSummaryCard label="Critical" value={normalized.summary.critical} severity="critical" description="Immediate attention" />
            <RiskSummaryCard label="Warnings" value={normalized.summary.warning} severity="warning" description="Needs review" />
            <RiskSummaryCard label="Info" value={normalized.summary.info} severity="info" description="Governance hints" />
            <RiskSummaryCard label="Affected VMs" value={normalized.summary.affectedVms} severity={normalized.summary.affectedVms ? 'warning' : 'healthy'} description={`${normalized.summary.affectedNodes} affected nodes`} />
          </div>

          {Object.keys(categoryGroups).length > 0 && (
            <div className="rounded-lg border border-slate-200 bg-white p-4">
              <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-800">
                <Database className="h-4 w-4 text-slate-500" />
                Risk categories
              </div>
              <div className="flex flex-wrap gap-2">
                {Object.entries(categoryGroups).map(([category, items]) => (
                  <span key={category} className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-700">
                    {getRiskCategoryLabel(category)}: {items.length}
                  </span>
                ))}
              </div>
            </div>
          )}

          {sortedRisks.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-lg border border-green-200 bg-green-50 py-12 text-center">
              <ShieldCheck className="mb-4 h-12 w-12 text-green-600" />
              <p className="font-medium text-green-800">No operational risks detected</p>
              <p className="mt-1 text-sm text-green-700">Current read-only checks did not find critical, warning, or info signals.</p>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                <Server className="h-4 w-4 text-slate-500" />
                Risk items
              </div>
              {sortedRisks.map((item) => (
                <RiskItemCard key={item.id} item={item} />
              ))}
            </div>
          )}

          <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800">
            <div className="mb-1 flex items-center gap-2 font-semibold">
              <Info className="h-4 w-4" />
              Safety note
            </div>
            This dashboard only reads Proxmox/PBS evidence and stores Gjallar&apos;s local observations and policy. It does not delete, stop, start, reboot, or modify VMs.
          </div>
        </div>
      )}
    </div>
  )
}

export default OperationalRiskDashboard
