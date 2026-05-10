import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, AlertTriangle, CheckCircle2, Clock3, HardDrive, Network, RefreshCw, Server, ShieldCheck } from 'lucide-react'
import { apiV1Client } from '../services/apiV1'
import { loadPlacementModel, placementToneClass } from '../utils/placement'

function formatPercent(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '-'
  return `${Math.round(number)}%`
}

function formatGb(value) {
  const number = Number(value)
  if (!Number.isFinite(number) || number <= 0) return '-'
  return `${Math.round(number).toLocaleString()} GB`
}

function metricTextClass(tone) {
  const normalized = String(tone ?? '').toLowerCase()
  if (normalized === 'green') return 'text-emerald-600'
  if (normalized === 'yellow') return 'text-amber-600'
  if (normalized === 'red') return 'text-red-600'
  return 'text-slate-950'
}

function barColor(tone) {
  const normalized = String(tone ?? '').toLowerCase()
  if (normalized === 'red') return 'bg-red-500'
  if (normalized === 'yellow') return 'bg-amber-500'
  if (normalized === 'green') return 'bg-emerald-500'
  return 'bg-blue-500'
}

function usageTone(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return 'slate'
  if (number >= 85) return 'red'
  if (number >= 70) return 'yellow'
  return 'green'
}

function SummaryCard({ label, value, hint, tone = 'slate', icon: Icon = Activity }) {
  return (
    <div className="min-h-28 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
          <div className={`mt-4 text-3xl font-bold ${metricTextClass(tone)}`}>{value}</div>
        </div>
        <span className={`rounded-lg border p-2 ${placementToneClass(tone)}`}>
          <Icon className="h-4 w-4" />
        </span>
      </div>
      {hint && <div className="mt-1 truncate text-xs text-slate-500">{hint}</div>}
    </div>
  )
}

function StatusBadge({ value }) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${placementToneClass(value)}`}>
      {value}
    </span>
  )
}

function RiskBadge({ level }) {
  const label = String(level || 'unknown')
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${placementToneClass(label)}`}>
      {label}
    </span>
  )
}

function UsageBar({ value }) {
  const number = Number(value)
  const width = Number.isFinite(number) ? Math.max(0, Math.min(100, number)) : 0
  return (
    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
      <div className={`h-full rounded-full ${barColor(usageTone(number))}`} style={{ width: `${width}%` }} />
    </div>
  )
}

function ReadOnlyNotice() {
  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800">
      <div className="flex items-start gap-2">
        <ShieldCheck className="mt-0.5 h-4 w-4" />
        <div>
          <div className="font-semibold">Read-only safety boundary</div>
          <div>Recommendations are review models only. Migration execution is not available in this slice.</div>
        </div>
      </div>
    </div>
  )
}

function NodeLoadTable({ nodes }) {
  return (
    <section className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-5 py-4">
        <h3 className="text-lg font-semibold text-slate-950">Node Load</h3>
        <div className="mt-1 text-xs text-slate-500">CPU, memory, VM count, storage, and bridge evidence by node</div>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-[58rem] w-full table-fixed divide-y divide-slate-200 text-sm">
          <colgroup>
            <col className="w-[16rem]" />
            <col className="w-[8rem]" />
            <col className="w-[8rem]" />
            <col className="w-[10rem]" />
            <col className="w-[10rem]" />
            <col className="w-[10rem]" />
            <col className="w-[12rem]" />
          </colgroup>
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-5 py-3 text-left font-semibold">Node</th>
              <th className="px-5 py-3 text-left font-semibold">State</th>
              <th className="px-5 py-3 text-left font-semibold">VMs</th>
              <th className="px-5 py-3 text-left font-semibold">CPU</th>
              <th className="px-5 py-3 text-left font-semibold">Memory</th>
              <th className="px-5 py-3 text-left font-semibold">Storage</th>
              <th className="px-5 py-3 text-left font-semibold">Bridges</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {nodes.length === 0 ? (
              <tr>
                <td className="px-5 py-6 text-sm text-slate-500" colSpan={7}>No node inventory is available.</td>
              </tr>
            ) : nodes.map((node) => (
              <tr key={node.id} className="hover:bg-slate-50">
                <td className="px-5 py-4">
                  <div className="truncate font-semibold text-slate-950">{node.name}</div>
                  <div className="mt-0.5 truncate text-xs text-slate-500">{node.status}</div>
                </td>
                <td className="px-5 py-4"><StatusBadge value={node.state} /></td>
                <td className="px-5 py-4">
                  <div className="font-medium text-slate-900">{node.runningVmCount}/{node.totalVmCount}</div>
                  <div className="text-xs text-slate-500">running / total</div>
                </td>
                <td className="px-5 py-4">
                  <div className="font-medium text-slate-900">{formatPercent(node.cpuUsagePercent)}</div>
                  <UsageBar value={node.cpuUsagePercent} />
                </td>
                <td className="px-5 py-4">
                  <div className="font-medium text-slate-900">{formatPercent(node.memoryUsagePercent)}</div>
                  <UsageBar value={node.memoryUsagePercent} />
                </td>
                <td className="px-5 py-4 text-slate-700">{formatGb(node.storageFreeGb)} free</td>
                <td className="px-5 py-4">
                  <div className="truncate text-slate-700">{node.bridgeIds.length ? node.bridgeIds.join(' / ') : '-'}</div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function DistributionPanel({ items }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center gap-2">
        <Server className="h-5 w-5 text-slate-500" />
        <h3 className="text-lg font-semibold text-slate-950">VM Distribution</h3>
      </div>
      <div className="mt-4 space-y-3">
        {items.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-500">No VM distribution data is available.</div>
        ) : items.map((item) => (
          <div key={item.nodeId} className="rounded-lg border border-slate-200 p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-slate-950">{item.nodeName}</div>
                <div className="mt-1 text-xs text-slate-500">{item.running} running, {item.stopped} stopped, {item.templates} templates</div>
              </div>
              <StatusBadge value={item.state} />
            </div>
            <div className="mt-3 grid grid-cols-3 gap-2 text-xs text-slate-600">
              <div className="rounded-lg bg-slate-50 px-3 py-2">
                <div className="font-semibold text-slate-950">{item.total}</div>
                <div>Total VMs</div>
              </div>
              <div className="rounded-lg bg-slate-50 px-3 py-2">
                <div className="font-semibold text-slate-950">{item.guestAgentVisible}</div>
                <div>Guest agent</div>
              </div>
              <div className="rounded-lg bg-slate-50 px-3 py-2">
                <div className="font-semibold text-slate-950">{item.risks}</div>
                <div>Risk VMs</div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

function RecommendationCard({ recommendation }) {
  return (
    <article className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <RiskBadge level={recommendation.riskLevel} />
            <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-600">Review only</span>
          </div>
          <h4 className="mt-3 truncate text-base font-semibold text-slate-950">{recommendation.vmName}</h4>
          <div className="mt-1 text-sm text-slate-600">{recommendation.sourceNodeName} to {recommendation.targetNodeName}</div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-right text-xs text-slate-600">
          <div className="font-semibold text-slate-950">{recommendation.estimatedEffect.imbalanceDelta}%</div>
          <div>pressure delta</div>
        </div>
      </div>

      <div className="mt-4 text-sm text-slate-700">{recommendation.reason}</div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-slate-200 p-3">
          <div className="text-xs text-slate-500">Estimated source pressure</div>
          <div className="mt-1 text-sm font-semibold text-slate-950">
            {recommendation.estimatedEffect.sourcePressureBefore}% to {recommendation.estimatedEffect.sourcePressureAfter}%
          </div>
        </div>
        <div className="rounded-lg border border-slate-200 p-3">
          <div className="text-xs text-slate-500">Estimated target pressure</div>
          <div className="mt-1 text-sm font-semibold text-slate-950">
            {recommendation.estimatedEffect.targetPressureBefore}% to {recommendation.estimatedEffect.targetPressureAfter}%
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-2 text-xs text-slate-600 sm:grid-cols-2">
        <div className="flex items-center gap-2">
          <Network className="h-4 w-4 text-slate-400" />
          <span>{recommendation.evidence.networkMessage}</span>
        </div>
        <div className="flex items-center gap-2">
          <HardDrive className="h-4 w-4 text-slate-400" />
          <span>{recommendation.evidence.storageMessage}</span>
        </div>
      </div>

      {recommendation.blockers.length > 0 && (
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
          {recommendation.blockers.join(', ')}
        </div>
      )}
    </article>
  )
}

function RecommendationsPanel({ recommendations }) {
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-slate-950">Placement Recommendations</h3>
          <div className="mt-1 text-xs text-slate-500">Generated from current read-only inventory</div>
        </div>
        <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-600">{recommendations.length} candidates</span>
      </div>
      {recommendations.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">No placement recommendations are available from the current inventory.</div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {recommendations.map((recommendation) => (
            <RecommendationCard key={recommendation.id} recommendation={recommendation} />
          ))}
        </div>
      )}
    </section>
  )
}

function RulesAndHistory({ rules, history }) {
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="h-5 w-5 text-slate-500" />
          <h3 className="text-lg font-semibold text-slate-950">Placement Rules</h3>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-600">{rules.status}</span>
          <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-600">editing {rules.editing}</span>
        </div>
        <div className="mt-4 grid gap-2">
          {rules.candidates.map((candidate) => (
            <div key={candidate} className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700">{candidate}</div>
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2">
          <Clock3 className="h-5 w-5 text-slate-500" />
          <h3 className="text-lg font-semibold text-slate-950">Placement History</h3>
        </div>
        <div className="mt-4 space-y-2">
          {history.length === 0 ? (
            <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-500">No placement history has been recorded.</div>
          ) : history.map((item) => (
            <div key={item.id} className="rounded-lg border border-slate-200 px-3 py-2 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="font-semibold text-slate-950">{item.type}</span>
                <RiskBadge level={item.riskLevel} />
              </div>
              <div className="mt-1 text-xs text-slate-500">{item.id} - {item.status}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}

function PlacementScreen() {
  const [model, setModel] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const loadModel = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const nextModel = await loadPlacementModel(apiV1Client)
      setModel(nextModel)
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to load Placement')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadModel()
  }, [loadModel])

  const summary = model?.summary || {
    totalNodes: 0,
    onlineNodes: 0,
    totalVms: 0,
    runningVms: 0,
    busiestNode: '-',
    roomiestNode: '-',
    cpuImbalance: 0,
    memoryImbalance: 0,
    recommendations: 0,
  }
  const status = model?.status || 'Unknown'
  const tone = model?.tone || 'slate'
  const pressureHint = useMemo(() => `${summary.busiestNode} busiest, ${summary.roomiestNode} roomiest`, [summary.busiestNode, summary.roomiestNode])

  return (
    <section className="space-y-5">
      <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${placementToneClass(status)}`}>
              Cluster {status}
            </span>
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Live read-only</span>
          </div>
          <h2 className="mt-3 text-3xl font-semibold text-slate-950">Placement</h2>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">VM placement balance, node load, and review-only movement candidates.</p>
        </div>
        <button
          type="button"
          onClick={loadModel}
          className="inline-flex w-fit items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </header>

      {error && <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <SummaryCard label="Cluster Balance" value={status} hint={pressureHint} tone={tone} icon={Activity} />
        <SummaryCard label="Nodes" value={`${summary.onlineNodes}/${summary.totalNodes}`} hint="online / total" tone={summary.onlineNodes === summary.totalNodes ? 'green' : 'yellow'} icon={Server} />
        <SummaryCard label="VMs" value={summary.totalVms} hint={`${summary.runningVms} running`} icon={Server} />
        <SummaryCard label="Imbalance" value={`${summary.cpuImbalance}%`} hint={`${summary.memoryImbalance}% memory delta`} tone={summary.cpuImbalance >= 25 || summary.memoryImbalance >= 25 ? 'yellow' : 'green'} icon={AlertTriangle} />
        <SummaryCard label="Recommendations" value={summary.recommendations} hint="review candidates" tone={summary.recommendations > 0 ? 'yellow' : 'green'} icon={CheckCircle2} />
      </div>

      <ReadOnlyNotice />

      {loading && !model ? (
        <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">Loading placement inventory...</div>
      ) : (
        <>
          <NodeLoadTable nodes={model?.nodes || []} />

          <div className="grid gap-5 xl:grid-cols-[380px_minmax(0,1fr)]">
            <DistributionPanel items={model?.vmDistribution || []} />
            <RecommendationsPanel recommendations={model?.recommendations || []} />
          </div>

          <RulesAndHistory rules={model?.rules || { status: 'display_only', editing: 'deferred', candidates: [] }} history={model?.history || []} />
        </>
      )}
    </section>
  )
}

export default PlacementScreen
