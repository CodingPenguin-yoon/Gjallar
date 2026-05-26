import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, AlertTriangle, CheckCircle2, Eye, HardDrive, Lock, Network, RefreshCw, Route as RouteIcon, Server, ShieldCheck } from 'lucide-react'
import { apiV1Client } from '../services/apiV1'
import {
  checkDrsRecommendation,
  drsToneClass,
  formatDrsBlocker,
  loadDrsAdvisorModel,
  loadDrsRecommendationDetail,
} from '../utils/drsAdvisor'

function formatPercent(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '-'
  return `${Math.round(number)}%`
}

function boundedPercent(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return 0
  return Math.max(0, Math.min(100, number))
}

function pressureTone(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return 'slate'
  if (number >= 85) return 'red'
  if (number >= 70) return 'yellow'
  return 'green'
}

function pressureBarClass(value) {
  const tone = pressureTone(value)
  if (tone === 'red') return 'bg-red-500'
  if (tone === 'yellow') return 'bg-amber-500'
  if (tone === 'green') return 'bg-emerald-500'
  return 'bg-slate-400'
}

function evidenceBool(source, snakeKey, camelKey = snakeKey) {
  const evidence = source || {}
  if (Object.prototype.hasOwnProperty.call(evidence, snakeKey)) return evidence[snakeKey] === true
  if (Object.prototype.hasOwnProperty.call(evidence, camelKey)) return evidence[camelKey] === true
  return false
}

function evidenceValue(source, snakeKey, camelKey = snakeKey) {
  const evidence = source || {}
  if (Object.prototype.hasOwnProperty.call(evidence, snakeKey)) return evidence[snakeKey]
  return evidence[camelKey]
}

function routeStatus(recommendation) {
  const route = recommendation.evidence?.route || {}
  const networkOk = evidenceBool(route, 'network_evidence_sufficient', 'networkEvidenceSufficient')
  const storageOk = evidenceBool(route, 'storage_evidence_sufficient', 'storageEvidenceSufficient')
  const routeBlocked = recommendation.blockers.includes('route_unknown') || route.blocked === true || !networkOk || !storageOk
  if (routeBlocked) return { label: 'Unknown', tone: 'yellow', networkOk, storageOk }
  return { label: 'Verified', tone: 'green', networkOk, storageOk }
}

function blockerPresent(blockers, code) {
  return blockers.includes(code)
}

function PressureBar({ label, value, sub }) {
  const width = boundedPercent(value)
  return (
    <div className="min-w-0">
      <div className="flex items-center justify-between gap-3 text-xs">
        <span className="truncate font-semibold text-slate-600">{label}</span>
        <span className="shrink-0 font-semibold text-slate-950">{formatPercent(value)}</span>
      </div>
      <div className="mt-1 h-2 overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full rounded-full ${pressureBarClass(value)}`} style={{ width: `${width}%` }} />
      </div>
      {sub && <div className="mt-1 truncate text-xs text-slate-500">{sub}</div>}
    </div>
  )
}

function PressureEffect({ label, before, after }) {
  return (
    <div className="space-y-2">
      <PressureBar label={`${label} before`} value={before} />
      <PressureBar label={`${label} after`} value={after} />
    </div>
  )
}

function SummaryCard({ label, value, hint, tone = 'slate', icon: Icon = Activity }) {
  return (
    <div className="min-h-28 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
          <div className="mt-4 text-3xl font-bold text-slate-950">{value}</div>
        </div>
        <span className={`rounded-lg border p-2 ${drsToneClass(tone)}`}>
          <Icon className="h-4 w-4" />
        </span>
      </div>
      {hint && <div className="mt-1 truncate text-xs text-slate-500">{hint}</div>}
    </div>
  )
}

function CompactBlockerList({ blockers }) {
  if (!blockers.length) {
    return <span className="inline-flex rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-800">none</span>
  }
  const visibleBlockers = blockers.slice(0, 4)
  const hiddenCount = blockers.length - visibleBlockers.length
  return (
    <div className="flex flex-wrap gap-1.5">
      {visibleBlockers.map((blocker) => (
        <span key={blocker} className="inline-flex rounded-full border border-amber-200 bg-amber-50 px-2 py-1 text-xs font-semibold text-amber-800">
          {formatDrsBlocker(blocker)}
        </span>
      ))}
      {hiddenCount > 0 && (
        <span className="inline-flex rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-xs font-semibold text-slate-600">+{hiddenCount} more</span>
      )}
    </div>
  )
}

function EvidenceBadge({ label, value, ok }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${drsToneClass(ok ? 'green' : 'yellow')}`}>
      {label} {value}
    </span>
  )
}

function BalanceOverviewPanel({ summary, thresholds, execution }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <RouteIcon className="h-5 w-5 text-slate-500" />
            <h3 className="text-lg font-semibold text-slate-950">Balance Overview</h3>
            <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-600">executable false</span>
          </div>
          <div className="mt-4 grid gap-4 md:grid-cols-3">
            <div className="rounded-lg border border-slate-200 p-3">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Current Delta</div>
              <div className="mt-3 text-2xl font-bold text-slate-950">{formatPercent(summary.sourceTargetDelta)}</div>
              <PressureBar label="source-target delta" value={summary.sourceTargetDelta} sub={`minimum ${thresholds.source_target_delta ?? 25}%`} />
            </div>
            <div className="rounded-lg border border-slate-200 p-3">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Thresholds</div>
              <div className="mt-3 grid gap-2">
                <PressureBar label="hot" value={thresholds.hot ?? 70} />
                <PressureBar label="critical" value={thresholds.critical ?? 85} />
              </div>
            </div>
            <div className="rounded-lg border border-slate-200 p-3">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Candidate Scope</div>
              <div className="mt-3 text-2xl font-bold text-slate-950">{summary.recommendationCount}</div>
              <div className="mt-1 text-xs text-slate-500">{summary.runningCandidateVms} running non-template, {summary.excludedRedRiskVms} red-risk excluded</div>
            </div>
          </div>
        </div>
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800">
          <div className="flex items-start gap-2">
            <ShieldCheck className="mt-0.5 h-4 w-4" />
            <div>
              <div className="font-semibold">Read-only execution boundary</div>
              <div className="mt-1">{execution?.reason || 'DRS migration execution is unavailable.'}</div>
              <div className="mt-3 rounded-lg border border-blue-200 bg-white/60 px-3 py-2 text-xs font-semibold text-blue-900">allowed actions: none</div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

function RecommendationQueue({ recommendations, selectedId, loadingDetail, checkingId, onSelect, onCheck }) {
  return (
    <section className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-col gap-2 border-b border-slate-200 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="text-lg font-semibold text-slate-950">Recommendations</h3>
          <div className="mt-1 text-xs text-slate-500">Recommendation Queue for current read-only VM balance candidates</div>
        </div>
        <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-600">{recommendations.length} candidates</span>
      </div>
      <div className="space-y-4 p-4">
        {recommendations.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-300 bg-white p-5 text-sm text-slate-500">No DRS candidates are available.</div>
        ) : recommendations.map((recommendation) => {
          const route = routeStatus(recommendation)
          return (
            <article
              key={recommendation.id}
              className={`rounded-lg border p-4 shadow-sm ${selectedId === recommendation.id ? 'border-blue-300 bg-blue-50/40' : 'border-slate-200 bg-white'}`}
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h4 className="text-base font-semibold text-slate-950">{recommendation.vmName}</h4>
                    <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-semibold text-slate-600">VMID {recommendation.vmid}</span>
                  </div>
                  <div className="mt-1 flex min-w-0 flex-wrap items-center gap-2 text-sm text-slate-600">
                    <span className="truncate font-medium text-slate-900">{recommendation.sourceNodeName}</span>
                    <span className="text-slate-400">-&gt;</span>
                    <span className="truncate font-medium text-slate-900">{recommendation.targetNodeName}</span>
                  </div>
                </div>
                <div className="flex shrink-0 flex-wrap items-center gap-2">
                  <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${drsToneClass(route.tone)}`}>Route Status {route.label}</span>
                  <span className="inline-flex rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-600">{recommendation.blockers.length} blockers</span>
                </div>
              </div>

              <div className="mt-4 grid gap-3 lg:grid-cols-2">
                <div className="rounded-lg border border-slate-200 bg-slate-50/60 p-3">
                  <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Source Pressure</div>
                  <PressureEffect
                    label="Source"
                    before={recommendation.estimatedEffect.sourcePressureBefore}
                    after={recommendation.estimatedEffect.sourcePressureAfter}
                  />
                </div>
                <div className="rounded-lg border border-slate-200 bg-slate-50/60 p-3">
                  <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Target Pressure</div>
                  <PressureEffect
                    label="Target"
                    before={recommendation.estimatedEffect.targetPressureBefore}
                    after={recommendation.estimatedEffect.targetPressureAfter}
                  />
                  <div className="mt-2 text-xs font-semibold text-slate-500">Projected Target {formatPercent(recommendation.estimatedEffect.targetPressureAfter)}</div>
                </div>
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                <EvidenceBadge label="Network evidence" value={route.networkOk ? 'sufficient' : 'unknown'} ok={route.networkOk} />
                <EvidenceBadge label="Storage evidence" value={route.storageOk ? 'sufficient' : 'unknown'} ok={route.storageOk} />
                <EvidenceBadge label="Delta" value={formatPercent(recommendation.estimatedEffect.sourceTargetDelta)} ok={recommendation.estimatedEffect.sourceTargetDelta >= (recommendation.thresholds?.source_target_delta ?? 25)} />
              </div>

              <div className="mt-4 flex flex-col gap-3 border-t border-slate-100 pt-4 xl:flex-row xl:items-start xl:justify-between">
                <div className="min-w-0">
                  <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Blockers</div>
                  <CompactBlockerList blockers={recommendation.blockers} />
                </div>
                <div className="flex shrink-0 gap-2">
                  <button
                    type="button"
                    onClick={() => onSelect(recommendation.id)}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                  >
                    <Eye className="h-3.5 w-3.5" />
                    {loadingDetail === recommendation.id ? 'Loading' : 'Detail'}
                  </button>
                  <button
                    type="button"
                    onClick={() => onCheck(recommendation.id)}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                  >
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    {checkingId === recommendation.id ? 'Checking' : 'Check'}
                  </button>
                </div>
              </div>
            </article>
          )
        })}
      </div>
    </section>
  )
}

function DetailSection({ title, icon: Icon, children }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-3">
      <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
        {Icon && <Icon className="h-3.5 w-3.5 text-slate-500" />}
        {title}
      </div>
      <div className="mt-2 space-y-2">{children}</div>
    </div>
  )
}

function StatusPill({ children, tone = 'slate' }) {
  return (
    <span className={`inline-flex min-w-0 max-w-full items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${drsToneClass(tone)}`}>
      <span className="truncate">{children}</span>
    </span>
  )
}

function DetailStatusRow({ label, value, tone }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md bg-slate-50 px-2.5 py-1.5 text-xs">
      <span className="shrink-0 text-slate-500">{label}</span>
      {tone ? (
        <StatusPill tone={tone}>{value}</StatusPill>
      ) : (
        <span className="min-w-0 truncate text-right font-semibold text-slate-800">{value}</span>
      )}
    </div>
  )
}

function CompactPressurePair({ title, before, after }) {
  return (
    <div className="rounded-md bg-slate-50 px-2.5 py-2">
      <div className="mb-2 flex items-center justify-between gap-3 text-xs">
        <span className="font-semibold text-slate-700">{title}</span>
        <span className="shrink-0 font-semibold text-slate-950">{formatPercent(before)} -&gt; {formatPercent(after)}</span>
      </div>
      <div className="space-y-1.5">
        <PressureBar label="before" value={before} />
        <PressureBar label="after" value={after} />
      </div>
    </div>
  )
}

function DetailPanel({ detail, checkResult }) {
  if (!detail) {
    return (
      <section className="rounded-lg border border-dashed border-slate-300 bg-white p-5 text-sm text-slate-500">
        Select a recommendation for detail evidence.
      </section>
    )
  }
  const route = detail.evidence?.route || {}
  const storage = detail.evidence?.storage || {}
  const passthrough = detail.evidence?.passthrough || {}
  const targetThreshold = detail.evidence?.target_over_threshold || detail.evidence?.targetOverThreshold || {}
  const routeSummary = routeStatus(detail)
  const vmStorage = evidenceValue(route, 'vm_storage_ids', 'vmStorageIds') || evidenceValue(storage, 'storage_ids', 'storageIds')
  const targetStorage = evidenceValue(route, 'target_storage_ids', 'targetStorageIds')
  const bridgeMatches = evidenceValue(route, 'matching_target_bridge_ids', 'matchingTargetBridgeIds')
  const passthroughTags = evidenceValue(passthrough, 'matched_tags', 'matchedTags')
  const targetBlocked = targetThreshold.blocked === true || blockerPresent(detail.blockers, 'target_over_threshold')
  const identityRows = [
    ['Identity', blockerPresent(detail.blockers, 'identity_unknown') ? 'unknown' : 'available'],
    ['Metadata', blockerPresent(detail.blockers, 'metadata_missing') ? 'missing' : 'available'],
    ['Policy', blockerPresent(detail.blockers, 'policy_unknown') ? 'unknown' : 'available'],
    ['Final pre-check', blockerPresent(detail.blockers, 'final_precheck_not_run') ? 'not run' : 'available'],
  ]
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="space-y-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill tone={detail.status}>{detail.status}</StatusPill>
            <StatusPill>executable false</StatusPill>
          </div>
          <h3 className="mt-2 truncate text-base font-semibold text-slate-950">{detail.vmName}</h3>
          <div className="mt-1 text-xs leading-5 text-slate-600">{detail.reason}</div>
        </div>
        <div className="rounded-md border border-slate-200 bg-slate-50 px-2.5 py-2 text-xs text-slate-600">
          <div className="truncate font-semibold text-slate-950">{detail.id}</div>
          <div className="mt-0.5 truncate">{detail.execution.reason}</div>
        </div>
      </div>

      <div className="mt-4 space-y-3">
        <DetailSection title="Pressure">
          <CompactPressurePair title="Source Pressure" before={detail.estimatedEffect.sourcePressureBefore} after={detail.estimatedEffect.sourcePressureAfter} />
          <CompactPressurePair title="Target Pressure" before={detail.estimatedEffect.targetPressureBefore} after={detail.estimatedEffect.targetPressureAfter} />
          <DetailStatusRow label="Projected Target" value={formatPercent(detail.estimatedEffect.targetPressureAfter)} />
        </DetailSection>

        <DetailSection title="Route Evidence" icon={RouteIcon}>
          <div className="flex flex-wrap gap-1.5">
            <StatusPill tone={routeSummary.tone}>Route Status {routeSummary.label}</StatusPill>
            <StatusPill tone={routeSummary.networkOk ? 'green' : 'yellow'}>network {routeSummary.networkOk ? 'sufficient' : 'unknown'}</StatusPill>
            <StatusPill tone={routeSummary.storageOk ? 'green' : 'yellow'}>storage {routeSummary.storageOk ? 'sufficient' : 'unknown'}</StatusPill>
          </div>
          <DetailStatusRow label="Bridge match" value={asCompactDisplay(bridgeMatches, 2)} />
          <DetailStatusRow label="Reference check" value={checkResult?.check?.status || 'not run'} />
        </DetailSection>

        <DetailSection title="Storage Evidence" icon={HardDrive}>
          <DetailStatusRow label="VM storage" value={asCompactDisplay(vmStorage, 2)} />
          <DetailStatusRow label="Local dependency" value={storage.blocked ? 'blocked' : 'not detected'} tone={storage.blocked ? 'yellow' : 'green'} />
          <DetailStatusRow label="Target storage" value={asCompactDisplay(targetStorage, 3)} />
        </DetailSection>

        <DetailSection title="Passthrough Evidence" icon={Network}>
          <DetailStatusRow label="Status" value={passthrough.blocked ? 'blocked' : 'not detected'} tone={passthrough.blocked ? 'yellow' : 'green'} />
          <DetailStatusRow label="Tags" value={asCompactDisplay(passthroughTags, 2)} />
          <DetailStatusRow label="Method" value={passthrough.method || 'tags only'} />
        </DetailSection>

        <DetailSection title="Target Threshold" icon={AlertTriangle}>
          <DetailStatusRow label="Projected" value={formatPercent(targetThreshold.projected_target_pressure_percent ?? targetThreshold.projectedTargetPressurePercent ?? detail.estimatedEffect.targetPressureAfter)} />
          <DetailStatusRow label="Critical" value={formatPercent(targetThreshold.critical_threshold ?? targetThreshold.criticalThreshold ?? detail.thresholds.critical)} />
          <DetailStatusRow label="Status" value={targetBlocked ? 'target over threshold' : 'within threshold'} tone={targetBlocked ? 'red' : 'green'} />
        </DetailSection>

        <DetailSection title="Identity / Metadata / Policy" icon={ShieldCheck}>
          <div className="grid grid-cols-2 gap-1.5">
            {identityRows.map(([label, value]) => (
              <div key={label} className="min-w-0 rounded-md bg-slate-50 px-2 py-1.5 text-xs">
                <div className="truncate font-semibold text-slate-900">{label}</div>
                <div className="mt-0.5 truncate text-slate-600">{value}</div>
              </div>
            ))}
          </div>
        </DetailSection>
      </div>

      <div className="mt-4">
        <div className="mb-2 text-sm font-semibold text-slate-950">Blockers</div>
        <CompactBlockerList blockers={detail.blockers} />
      </div>

      <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 items-start gap-2">
            <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-500" />
            <div>
              <div className="text-sm font-semibold text-slate-950">Execution Boundary</div>
              <div className="mt-1 text-xs leading-5 text-slate-600">{detail.execution.reason}</div>
            </div>
          </div>
          <button type="button" disabled className="inline-flex w-fit shrink-0 cursor-not-allowed items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-400">
            Approve & Migrate
          </button>
        </div>
      </div>
    </section>
  )
}

function asList(value) {
  return Array.isArray(value) ? value : []
}

function asCompactDisplay(value, limit = 2) {
  const items = asList(value)
  if (!items.length) return '-'
  const visible = items.slice(0, limit).join(' / ')
  const hiddenCount = items.length - limit
  return hiddenCount > 0 ? `${visible} +${hiddenCount}` : visible
}

function DrsAdvisorScreen() {
  const [model, setModel] = useState(null)
  const [detail, setDetail] = useState(null)
  const [checkResult, setCheckResult] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadingDetail, setLoadingDetail] = useState(null)
  const [checkingId, setCheckingId] = useState(null)
  const [error, setError] = useState(null)

  const loadModel = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const nextModel = await loadDrsAdvisorModel(apiV1Client)
      setModel(nextModel)
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to load DRS Advisor')
    } finally {
      setLoading(false)
    }
  }, [])

  const loadDetail = useCallback(async (recommendationId) => {
    setLoadingDetail(recommendationId)
    setError(null)
    try {
      const nextDetail = await loadDrsRecommendationDetail(apiV1Client, recommendationId)
      setDetail(nextDetail)
      setCheckResult(null)
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to load DRS recommendation')
    } finally {
      setLoadingDetail(null)
    }
  }, [])

  const runCheck = useCallback(async (recommendationId) => {
    setCheckingId(recommendationId)
    setError(null)
    try {
      const result = await checkDrsRecommendation(apiV1Client, recommendationId, {})
      setCheckResult(result)
      setDetail(result.recommendation)
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to check DRS recommendation')
    } finally {
      setCheckingId(null)
    }
  }, [])

  useEffect(() => {
    loadModel()
  }, [loadModel])

  const summary = model?.summary || {
    clusterState: 'unknown',
    recommendationCount: 0,
    onlineNodes: 0,
    totalNodes: 0,
    runningCandidateVms: 0,
    excludedRedRiskVms: 0,
    sourceTargetDelta: 0,
    hotNodeCount: 0,
    criticalNodeCount: 0,
  }
  const thresholds = model?.thresholds || {}
  const thresholdText = useMemo(
    () => `hot ${thresholds.hot ?? 70}%, critical ${thresholds.critical ?? 85}%, delta ${thresholds.source_target_delta ?? 25}%`,
    [thresholds],
  )

  return (
    <section className="space-y-5">
      <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${drsToneClass(summary.clusterState)}`}>
              {summary.clusterState}
            </span>
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Live read-only</span>
          </div>
          <h2 className="mt-3 text-3xl font-semibold text-slate-950">DRS Advisor</h2>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">Read-only Proxmox balance candidates with stable blockers and reference checks.</p>
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
        <SummaryCard label="Advisor State" value={summary.clusterState} hint={thresholdText} tone={summary.clusterState} icon={Activity} />
        <SummaryCard label="Nodes" value={`${summary.onlineNodes}/${summary.totalNodes}`} hint={`${summary.hotNodeCount} hot, ${summary.criticalNodeCount} critical`} tone={summary.criticalNodeCount > 0 ? 'red' : summary.hotNodeCount > 0 ? 'yellow' : 'green'} icon={Server} />
        <SummaryCard label="Candidates" value={summary.recommendationCount} hint={`${summary.runningCandidateVms} running non-template`} tone={summary.recommendationCount > 0 ? 'yellow' : 'green'} icon={RouteIcon} />
        <SummaryCard label="Delta" value={formatPercent(summary.sourceTargetDelta)} hint="source-target pressure" tone={summary.sourceTargetDelta >= 25 ? 'yellow' : 'green'} icon={AlertTriangle} />
        <SummaryCard label="Excluded" value={summary.excludedRedRiskVms} hint="red-risk VMs" tone={summary.excludedRedRiskVms > 0 ? 'red' : 'green'} icon={ShieldCheck} />
      </div>

      <BalanceOverviewPanel summary={summary} thresholds={thresholds} execution={model?.execution} />

      {loading && !model ? (
        <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">Loading DRS Advisor...</div>
      ) : (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_440px]">
          <RecommendationQueue
            recommendations={model?.recommendations || []}
            selectedId={detail?.id}
            loadingDetail={loadingDetail}
            checkingId={checkingId}
            onSelect={loadDetail}
            onCheck={runCheck}
          />
          <DetailPanel detail={detail} checkResult={checkResult} />
        </div>
      )}
    </section>
  )
}

export default DrsAdvisorScreen
