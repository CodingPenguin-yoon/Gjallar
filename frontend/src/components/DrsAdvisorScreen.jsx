import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, AlertTriangle, CheckCircle2, ClipboardCheck, Eye, HardDrive, Lock, Network, RefreshCw, Route as RouteIcon, Server, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import PolicyReviewModal from './DrsPolicyReviewModal'
import { apiV1Client } from '../services/apiV1'
import {
  canOfferDrsApprovalPacket,
  canSubmitDrsApprovalPacket,
  checkDrsRecommendation,
  createDrsApprovalPacket,
  drsToneClass,
  formatDrsBlocker,
  loadDrsAdvisorModel,
  loadDrsPolicyCoverage,
  loadDrsRecommendationDetail,
  submitDrsPolicyUpdate,
} from '../utils/drsAdvisor'

const POLICY_FILTERS = ['unknown', 'allowed', 'restricted', 'blocked']
const CONFIDENCE_FILTERS = ['all', 'high', 'uncertain']

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
  const routeUnknown = route.blocked === true || !networkOk || !storageOk
  if (routeUnknown) return { label: 'Unknown', tone: 'yellow', networkOk, storageOk }
  return { label: 'Verified', tone: 'green', networkOk, storageOk }
}

function blockerPresent(blockers, code) {
  return blockers.includes(code)
}

function identityTone(confidence) {
  if (confidence === 'high') return 'green'
  if (confidence === 'unknown') return 'yellow'
  return 'yellow'
}

function policyTone(policy) {
  if (policy === 'allowed') return 'green'
  if (policy === 'blocked') return 'red'
  return 'yellow'
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
              <div className="mt-1">{execution?.reason || 'DRS read/check UI has no execution controls; backend execution is a separate approval/job route.'}</div>
              <div className="mt-3 rounded-lg border border-blue-200 bg-white/60 px-3 py-2 text-xs font-semibold text-blue-900">allowed actions: none</div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

function PolicyFilterButton({ active, children, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center rounded-lg border px-2.5 py-1.5 text-xs font-semibold ${
        active
          ? 'border-blue-300 bg-blue-50 text-blue-800'
          : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
      }`}
    >
      {children}
    </button>
  )
}

function policyValueTone(value) {
  if (value === 'allowed') return 'green'
  if (value === 'blocked') return 'red'
  if (value === 'restricted') return 'yellow'
  return 'yellow'
}

function confidenceFilterMatch(item, filter) {
  if (filter === 'high') return item.identityConfidence === 'high'
  if (filter === 'uncertain') return item.identityConfidence !== 'high'
  return true
}

function policyLocation(item) {
  const locator = item.currentLocator || {}
  return `${locator.nodeId || '-'} / VMID ${locator.vmid ?? '-'}`
}

function PolicyCoveragePanel({
  policyCoverage,
  filters,
  onPolicyFilterToggle,
  onConfidenceFilter,
  canOperate,
  savingPolicyId,
  onReviewPolicy,
}) {
  const items = asList(policyCoverage?.items)
  const visibleItems = items.filter((item) => filters.policies[item.policy.value] && confidenceFilterMatch(item, filters.confidence))
  const coverage = policyCoverage?.coverage || {}
  return (
    <section className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-col gap-3 border-b border-slate-200 px-5 py-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <h3 className="text-lg font-semibold text-slate-950">VM Policy Configuration</h3>
          <div className="mt-1 text-xs text-slate-500">
            {coverage.totalNonTemplateVms ?? items.length} current non-template VMs · {coverage.writeAllowedCount ?? 0} writable identities
          </div>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:justify-end">
          <div className="flex flex-wrap gap-1.5">
            {POLICY_FILTERS.map((policy) => (
              <PolicyFilterButton
                key={policy}
                active={filters.policies[policy]}
                onClick={() => onPolicyFilterToggle(policy)}
              >
                {policy}
              </PolicyFilterButton>
            ))}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {CONFIDENCE_FILTERS.map((filter) => (
              <PolicyFilterButton
                key={filter}
                active={filters.confidence === filter}
                onClick={() => onConfidenceFilter(filter)}
              >
                {filter === 'uncertain' ? 'identity uncertain' : filter}
              </PolicyFilterButton>
            ))}
          </div>
        </div>
      </div>
      <div className="grid gap-3 p-4 xl:grid-cols-2">
        {visibleItems.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-300 bg-white p-5 text-sm text-slate-500">No policy items match the selected filters.</div>
        ) : visibleItems.map((item) => {
          const blockers = item.policyWriteBlockers.length ? item.policyWriteBlockers : item.drsBlockerImpact.policyBlockers
          return (
            <article key={`${item.vmIdentityId || item.currentLocator.vmid}`} className="rounded-lg border border-slate-200 bg-white p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h4 className="truncate text-base font-semibold text-slate-950">{item.currentLocator.name}</h4>
                    <StatusPill tone={policyValueTone(item.policy.value)}>{item.policy.value}</StatusPill>
                    {item.currentDrsCandidate && <StatusPill tone="yellow">DRS candidate</StatusPill>}
                  </div>
                  <div className="mt-1 text-xs text-slate-500">{policyLocation(item)}</div>
                </div>
                <button
                  type="button"
                  onClick={() => onReviewPolicy(item)}
                  disabled={!canOperate || !item.policyWriteAllowed || savingPolicyId === item.vmIdentityId}
                  className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <ClipboardCheck className="h-3.5 w-3.5" />
                  {savingPolicyId === item.vmIdentityId ? 'Saving' : 'Review'}
                </button>
              </div>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                <DetailStatusRow label="Identity" value={item.identityConfidence} tone={item.identityConfidence === 'high' ? 'green' : 'yellow'} />
                <DetailStatusRow label="Status" value={item.identityStatus} tone={item.identityStatus === 'active' ? 'green' : 'yellow'} />
                <DetailStatusRow label="Observed" value={item.latestObservation.observedAt || '-'} />
                <DetailStatusRow label="Source" value={item.policy.source || 'default'} />
              </div>
              <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 px-2.5 py-2 text-xs text-slate-600">
                <div className="truncate">fingerprint {item.fingerprint.fingerprintHash || '-'}</div>
                <div className="mt-1 truncate">reason {item.policy.reason || '-'}</div>
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                <StatusPill tone={item.policyWriteAllowed ? 'green' : 'yellow'}>policy write {item.policyWriteAllowed ? 'allowed' : 'blocked'}</StatusPill>
                <StatusPill tone="slate">migration approval unchanged</StatusPill>
              </div>
              {blockers.length > 0 && (
                <div className="mt-3">
                  <CompactBlockerList blockers={blockers} />
                </div>
              )}
              {!canOperate && (
                <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 px-2.5 py-2 text-xs text-slate-600">
                  DRS policy updates require operator or admin role.
                </div>
              )}
            </article>
          )
        })}
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
          const identityConfidence = recommendation.identityEvidence?.match_confidence || recommendation.identityEvidence?.matchConfidence || 'unknown'
          const migrationPolicy = recommendation.policyEvidence?.policy || 'unknown'
          const activeAdvisorSignals = asList(recommendation.advisorySignals).filter((signal) => signal.status !== 'pass')
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
                  <StatusPill tone={activeAdvisorSignals.length ? 'yellow' : 'green'}>advisory {activeAdvisorSignals.length}</StatusPill>
                  <StatusPill tone={technicalGateTone(recommendation.technicalGateStatus?.status)}>Proxmox {recommendation.technicalGateStatus?.status || 'unknown'}</StatusPill>
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
                <EvidenceBadge label="Identity" value={identityConfidence} ok={identityConfidence === 'high'} />
                <EvidenceBadge label="Policy" value={migrationPolicy} ok={migrationPolicy === 'allowed'} />
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

function checkTone(status) {
  const normalized = String(status ?? '').toLowerCase()
  if (normalized === 'pass' || normalized === 'would_pass' || normalized === 'completed') return 'green'
  if (normalized === 'failed' || normalized === 'blocked') return 'red'
  if (normalized === 'not_collected' || normalized === 'not_implemented' || normalized === 'not run') return 'yellow'
  return 'slate'
}

function boolLabel(value) {
  return value === true ? 'true' : 'false'
}

function criteriaTone(detail) {
  if (detail?.blocking) return 'red'
  if (detail?.status === 'warning' || detail?.severity === 'warning' || detail?.evidenceState === 'not_collected') return 'yellow'
  if (detail?.status === 'pass' || detail?.severity === 'info') return 'green'
  return 'slate'
}

function technicalGateTone(status) {
  if (status === 'blocked') return 'red'
  if (status === 'pass') return 'green'
  if (status === 'not_collected' || status === 'unknown') return 'yellow'
  return 'slate'
}

function authorityLabel(authority) {
  if (authority === 'gjallar_operational_gate') return 'Gjallar gate'
  if (authority === 'proxmox_final_technical_gate') return 'Proxmox technical'
  if (authority === 'advisor_prefilter_signal') return 'Advisor signal'
  return authority || '-'
}

function lockLabel(lock) {
  const source = lock || {}
  return [
    source.operation_lock_id || source.operationLockId,
    source.status,
    source.scope_type || source.scopeType,
    source.reason,
  ].filter(Boolean).join(' · ') || '-'
}

function scopeLabel(scope) {
  const source = scope || {}
  return [source.scope_type || source.scopeType, source.scope_key || source.scopeKey].filter(Boolean).join(':') || '-'
}

function CheckRows({ checks }) {
  const rows = asList(checks)
  if (!rows.length) {
    return <div className="rounded-md border border-dashed border-slate-200 p-3 text-xs text-slate-500">Run Check to load final pre-check rows.</div>
  }
  return (
    <div className="space-y-1.5">
      {rows.map((check) => (
        <div key={check.id} className="grid gap-2 rounded-md border border-slate-200 bg-white px-2.5 py-2 text-xs sm:grid-cols-[minmax(0,1fr)_auto]">
          <div className="min-w-0">
            <div className="truncate font-semibold text-slate-900">{check.label}</div>
            {check.blocker && <div className="mt-0.5 truncate text-slate-500">{formatDrsBlocker(check.blocker)}</div>}
            {check.criterion?.authority && (
              <div className="mt-0.5 truncate text-slate-500">
                {authorityLabel(check.criterion.authority)} · {check.criterion.evidenceState || check.criterion.status || '-'}
              </div>
            )}
          </div>
          <StatusPill tone={checkTone(check.status)}>{check.status}</StatusPill>
        </div>
      ))}
    </div>
  )
}

function CriteriaTaxonomyPanel({ criteriaDetails, advisorySignals, technicalGateStatus }) {
  const details = asList(criteriaDetails)
  const hardGates = details.filter((detail) => detail.blocking === true)
  const advisorSignals = asList(advisorySignals).length
    ? asList(advisorySignals)
    : details.filter((detail) => detail.authority === 'advisor_prefilter_signal')
  const proxmoxCriteria = details.filter((detail) => detail.authority === 'proxmox_final_technical_gate')
  const activeAdvisorSignals = advisorSignals.filter((detail) => detail.status !== 'pass')
  return (
    <DetailSection title="DRS Criteria" icon={ShieldCheck}>
      <div className="flex flex-wrap gap-1.5">
        <StatusPill tone={hardGates.length ? 'red' : 'green'}>hard gates {hardGates.length}</StatusPill>
        <StatusPill tone={activeAdvisorSignals.length ? 'yellow' : 'green'}>advisory signals {activeAdvisorSignals.length}</StatusPill>
        <StatusPill tone={technicalGateTone(technicalGateStatus?.status)}>Proxmox technical {technicalGateStatus?.status || 'unknown'}</StatusPill>
      </div>
      <DetailStatusRow label="Hard gate blockers" value={asCompactDisplay(hardGates.map((detail) => formatDrsBlocker(detail.code)), 3)} tone={hardGates.length ? 'red' : 'green'} />
      <DetailStatusRow label="Technical criteria" value={asCompactDisplay(technicalGateStatus?.criteria || proxmoxCriteria.map((detail) => detail.code), 3)} tone={technicalGateTone(technicalGateStatus?.status)} />
      {advisorSignals.length > 0 && (
        <div className="space-y-1">
          {advisorSignals.slice(0, 4).map((detail) => (
            <div key={detail.code} className="flex items-center justify-between gap-2 rounded-md bg-slate-50 px-2.5 py-1.5 text-xs">
              <span className="min-w-0 truncate font-semibold text-slate-800">{formatDrsBlocker(detail.code)}</span>
              <StatusPill tone={criteriaTone(detail)}>{detail.status || detail.severity}</StatusPill>
            </div>
          ))}
        </div>
      )}
    </DetailSection>
  )
}

function OperationLockEvidence({ operationLock, approvalReadiness }) {
  const lock = operationLock || {}
  const matchingLocks = asList(lock.matchingLocks)
  const reconciliation = approvalReadiness?.reconciliation || {}
  const reconciliationLockIds = asList(reconciliation.matchingLockIds).length
    ? reconciliation.matchingLockIds
    : lock.reconciliationLockIds
  return (
    <DetailSection title="Operation Lock Evidence" icon={Lock}>
      <div className="flex flex-wrap gap-1.5">
        <StatusPill tone={checkTone(lock.status)}>status {lock.status || 'not run'}</StatusPill>
        <StatusPill tone={lock.blocking ? 'yellow' : 'green'}>blocking {boolLabel(lock.blocking === true)}</StatusPill>
        <StatusPill tone={reconciliation.required ? 'yellow' : 'green'}>reconciliation {reconciliation.required ? 'required' : 'not required'}</StatusPill>
      </div>
      <DetailStatusRow label="Operation" value={lock.operationType || '-'} />
      <DetailStatusRow label="Cluster" value={lock.clusterId || '-'} />
      <DetailStatusRow label="Matching locks" value={asCompactDisplay(lock.matchingLockIds, 3)} tone={matchingLocks.length ? 'yellow' : 'green'} />
      <DetailStatusRow label="Reconciliation locks" value={asCompactDisplay(reconciliationLockIds, 3)} tone={reconciliation.required ? 'yellow' : 'green'} />
      {matchingLocks.length > 0 && (
        <div className="space-y-1">
          {matchingLocks.slice(0, 3).map((item, index) => (
            <div key={`${item.operation_lock_id || item.operationLockId || index}`} className="rounded-md bg-slate-50 px-2.5 py-1.5 text-xs text-slate-700">
              {lockLabel(item)}
            </div>
          ))}
        </div>
      )}
      {asList(lock.checkedScopes).length > 0 && (
        <DetailStatusRow label="Checked scopes" value={asCompactDisplay(lock.checkedScopes.map(scopeLabel), 3)} />
      )}
    </DetailSection>
  )
}

function ProxmoxConflictEvidence({ conflicts }) {
  const source = conflicts || {}
  return (
    <DetailSection title="Proxmox Conflict Evidence" icon={AlertTriangle}>
      <div className="flex flex-wrap gap-1.5">
        <StatusPill tone={checkTone(source.status)}>conflicts {source.status || 'not run'}</StatusPill>
        <StatusPill tone={asList(source.notCollected).length ? 'yellow' : 'green'}>not collected {asList(source.notCollected).length}</StatusPill>
      </div>
      <DetailStatusRow label="Config lock" value={source.configLock?.status || '-'} tone={source.configLock?.blocking ? 'red' : 'green'} />
      <DetailStatusRow label="Active task" value={source.activeTask?.status || '-'} tone={source.activeTask?.status === 'not_collected' ? 'yellow' : undefined} />
      <DetailStatusRow label="HA state" value={source.haState?.status || '-'} tone={source.haState?.status === 'not_collected' ? 'yellow' : undefined} />
      <DetailStatusRow label="Cluster quorum" value={source.clusterQuorum?.status || '-'} tone={source.clusterQuorum?.status === 'not_collected' ? 'yellow' : undefined} />
    </DetailSection>
  )
}

function ApprovalReadinessPanel({
  approvalReadiness,
  currentUser,
  canOperate,
  creatingApproval,
  approvalResult,
  warningAcknowledged,
  onWarningAcknowledgedChange,
  onCreateApprovalPacket,
}) {
  if (!approvalReadiness) return null
  const approvalReady = approvalReadiness.approvalPacketCreatable === true
  const approvalOffered = canOfferDrsApprovalPacket(approvalReadiness)
  const approvalSubmittable = canSubmitDrsApprovalPacket(approvalReadiness, { warningAcknowledged })
  const viewerLocked = canOperate !== true
  return (
    <DetailSection title="Approval Readiness" icon={ClipboardCheck}>
      <div className="flex flex-wrap gap-1.5">
        <StatusPill tone={approvalReadiness.finalPrecheckPassed ? 'green' : 'yellow'}>final pre-check {approvalReadiness.finalPrecheckPassed ? 'passed' : 'blocked'}</StatusPill>
        <StatusPill tone={approvalReady ? 'green' : 'yellow'}>approval packet creatable {boolLabel(approvalReady)}</StatusPill>
        <StatusPill tone="slate">runnable {boolLabel(approvalReadiness.runnable)}</StatusPill>
        <StatusPill tone="slate">proxmox mutation {boolLabel(approvalReadiness.proxmoxMutationEnabled)}</StatusPill>
      </div>
      <DetailStatusRow label="Session role" value={currentUser?.role || 'unknown'} tone={canOperate ? 'green' : 'yellow'} />
      <DetailStatusRow label="Allowed actions" value={asCompactDisplay(approvalReadiness.allowedActions, 3)} />
      <DetailStatusRow label="Side effects" value={asCompactDisplay(approvalReadiness.sideEffects, 3)} />
      {approvalReadiness.blockers.length > 0 && <CompactBlockerList blockers={approvalReadiness.blockers} />}
      {approvalReadiness.runnableBlockers.length > 0 && (
        <DetailStatusRow label="Runnable blockers" value={asCompactDisplay(approvalReadiness.runnableBlockers, 3)} tone="yellow" />
      )}
      {approvalReadiness.warningsAckRequired && (
        <label className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-2 text-xs text-amber-800">
          <input
            type="checkbox"
            checked={warningAcknowledged}
            onChange={(event) => onWarningAcknowledgedChange(event.target.checked)}
            disabled={viewerLocked || creatingApproval}
            className="mt-0.5"
          />
          <span>Warning acknowledgement required for local approval packet creation.</span>
        </label>
      )}
      {canOperate ? (
        approvalOffered && (
          <button
            type="button"
            onClick={onCreateApprovalPacket}
            disabled={creatingApproval || !approvalSubmittable}
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-blue-300 bg-blue-600 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
          >
            <ClipboardCheck className="h-4 w-4" />
            {creatingApproval ? 'Creating approval packet' : 'Create approval packet'}
          </button>
        )
      ) : (
        <div className="rounded-md border border-slate-200 bg-slate-50 px-2.5 py-2 text-xs text-slate-600">
          DRS approval packet creation requires operator or admin role.
        </div>
      )}
      {approvalResult && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-2.5 py-2 text-xs text-emerald-800">
          <div className="font-semibold">Local approval packet/job intent recorded</div>
          <div className="mt-1">Approval packet {approvalResult.approvalPacketId || '-'}</div>
          <div className="mt-1">Job intent {approvalResult.jobId || '-'}</div>
          {approvalResult.jobId && (
            <Link className="mt-2 inline-flex font-semibold text-emerald-900 underline" to={`/jobs?job=${encodeURIComponent(approvalResult.jobId)}`}>
              Jobs/Runs
            </Link>
          )}
        </div>
      )}
    </DetailSection>
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

function DetailPanel({
  detail,
  checkResult,
  currentUser,
  canOperate,
  creatingApproval,
  approvalResult,
  warningAcknowledged,
  onWarningAcknowledgedChange,
  onCreateApprovalPacket,
}) {
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
  const identityEvidence = detail.identityEvidence || detail.evidence?.identity || {}
  const policyEvidence = detail.policyEvidence || detail.evidence?.policy || {}
  const identityConfidence = identityEvidence.match_confidence || identityEvidence.matchConfidence || 'unknown'
  const identityStatus = identityEvidence.identity_status || identityEvidence.identityStatus || 'unknown'
  const migrationPolicy = policyEvidence.policy || 'unknown'
  const fingerprint = identityEvidence.stable_fingerprint || identityEvidence.stableFingerprint || '-'
  const fingerprintLabel = fingerprint === '-' ? '-' : `${fingerprint.slice(0, 18)}...`
  const finalPrecheck = checkResult?.finalPrecheck
  const approvalReadiness = checkResult?.approvalReadiness
  const criteriaDetails = checkResult?.criteriaDetails?.length ? checkResult.criteriaDetails : detail.criteriaDetails
  const advisorySignals = checkResult?.advisorySignals?.length ? checkResult.advisorySignals : detail.advisorySignals
  const technicalGateStatus = checkResult?.technicalGateStatus || detail.technicalGateStatus
  const identityRows = [
    ['Identity', identityConfidence, identityTone(identityConfidence)],
    ['Status', identityStatus, identityTone(identityConfidence)],
    ['Fingerprint', fingerprintLabel, identityConfidence === 'high' ? 'green' : 'yellow'],
    ['Policy', migrationPolicy, policyTone(migrationPolicy)],
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

        <CriteriaTaxonomyPanel
          criteriaDetails={criteriaDetails}
          advisorySignals={advisorySignals}
          technicalGateStatus={technicalGateStatus}
        />

        <DetailSection title="Identity / Metadata / Policy" icon={ShieldCheck}>
          <div className="grid grid-cols-2 gap-1.5">
            {identityRows.map(([label, value, tone]) => (
              <div key={label} className="min-w-0 rounded-md bg-slate-50 px-2 py-1.5 text-xs">
                <div className="truncate font-semibold text-slate-900">{label}</div>
                <div className={`mt-0.5 truncate font-semibold ${tone === 'green' ? 'text-emerald-700' : tone === 'red' ? 'text-red-700' : 'text-amber-700'}`}>{value}</div>
              </div>
            ))}
          </div>
          <DetailStatusRow label="Policy source" value={policyEvidence.source || 'default'} />
          <DetailStatusRow label="Policy reason" value={policyEvidence.reason || 'not recorded'} />
        </DetailSection>

        {finalPrecheck && (
          <DetailSection title="Final Pre-check" icon={CheckCircle2}>
            <div className="flex flex-wrap gap-1.5">
              <StatusPill tone={checkTone(finalPrecheck.status)}>status {finalPrecheck.status}</StatusPill>
              <StatusPill tone="slate">read only {boolLabel(checkResult.readOnly)}</StatusPill>
              <StatusPill tone="slate">executable {boolLabel(checkResult.executable)}</StatusPill>
              <StatusPill tone="slate">allowed actions {checkResult.allowedActions.length}</StatusPill>
            </div>
            <DetailStatusRow label="Checked" value={finalPrecheck.checkedAt || checkResult.checkedAt || '-'} />
            <DetailStatusRow label="Observed" value={finalPrecheck.observedAt || '-'} />
            <DetailStatusRow label="Would be executable" value={boolLabel(checkResult.wouldBeExecutable)} tone={checkResult.wouldBeExecutable ? 'green' : 'yellow'} />
            {checkResult.blockerDetails.length > 0 && (
              <div className="space-y-1">
                {checkResult.blockerDetails.slice(0, 4).map((blocker) => (
                  <div key={blocker.code} className="rounded-md bg-amber-50 px-2.5 py-1.5 text-xs text-amber-800">
                    <span className="font-semibold">{formatDrsBlocker(blocker.code)}</span>
                    <span className="ml-1">{blocker.message}</span>
                  </div>
                ))}
              </div>
            )}
            <CheckRows checks={finalPrecheck.checks} />
          </DetailSection>
        )}

        {finalPrecheck && (
          <>
            <OperationLockEvidence operationLock={checkResult.operationLock} approvalReadiness={approvalReadiness} />
            <ProxmoxConflictEvidence conflicts={checkResult.proxmoxConflicts} />
          </>
        )}

        <ApprovalReadinessPanel
          approvalReadiness={approvalReadiness}
          currentUser={currentUser}
          canOperate={canOperate}
          creatingApproval={creatingApproval}
          approvalResult={approvalResult}
          warningAcknowledged={warningAcknowledged}
          onWarningAcknowledgedChange={onWarningAcknowledgedChange}
          onCreateApprovalPacket={onCreateApprovalPacket}
        />
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
          <StatusPill>allowed actions none</StatusPill>
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

function DrsAdvisorScreen({ currentUser = null, canOperate = false }) {
  const [model, setModel] = useState(null)
  const [policyCoverage, setPolicyCoverage] = useState(null)
  const [detail, setDetail] = useState(null)
  const [checkResult, setCheckResult] = useState(null)
  const [approvalResult, setApprovalResult] = useState(null)
  const [policyReviewItem, setPolicyReviewItem] = useState(null)
  const [policyUpdateResult, setPolicyUpdateResult] = useState(null)
  const [policyFilters, setPolicyFilters] = useState({
    policies: { unknown: true, allowed: true, restricted: true, blocked: true },
    confidence: 'all',
  })
  const [warningAcknowledged, setWarningAcknowledged] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadingDetail, setLoadingDetail] = useState(null)
  const [checkingId, setCheckingId] = useState(null)
  const [creatingApproval, setCreatingApproval] = useState(false)
  const [savingPolicyId, setSavingPolicyId] = useState(null)
  const [policyError, setPolicyError] = useState(null)
  const [error, setError] = useState(null)

  const loadModel = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [nextModel, nextPolicyCoverage] = await Promise.all([
        loadDrsAdvisorModel(apiV1Client),
        loadDrsPolicyCoverage(apiV1Client),
      ])
      setModel(nextModel)
      setPolicyCoverage(nextPolicyCoverage)
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
      setApprovalResult(null)
      setWarningAcknowledged(false)
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
      setApprovalResult(null)
      setWarningAcknowledged(false)
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to check DRS recommendation')
    } finally {
      setCheckingId(null)
    }
  }, [])

  const createApprovalPacket = useCallback(async () => {
    if (!canOperate || !canSubmitDrsApprovalPacket(checkResult?.approvalReadiness, { warningAcknowledged })) return
    setCreatingApproval(true)
    setError(null)
    try {
      const result = await createDrsApprovalPacket(apiV1Client, checkResult.recommendationId, {
        warningAcknowledged,
      })
      setApprovalResult(result)
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to create DRS approval packet')
    } finally {
      setCreatingApproval(false)
    }
  }, [canOperate, checkResult?.approvalReadiness, checkResult?.recommendationId, warningAcknowledged])

  const togglePolicyFilter = useCallback((policy) => {
    setPolicyFilters((current) => ({
      ...current,
      policies: {
        ...current.policies,
        [policy]: !current.policies[policy],
      },
    }))
  }, [])

  const submitPolicyReview = useCallback(async (item, { policy, reason, acknowledged }) => {
    if (!canOperate || !item?.policyWriteAllowed) return
    setSavingPolicyId(item.vmIdentityId)
    setPolicyError(null)
    try {
      const result = await submitDrsPolicyUpdate(apiV1Client, item.vmIdentityId, {
        policy,
        reason,
        policyChangeAcknowledged: acknowledged,
        expectedObservation: item.expectedObservationPayload,
      })
      setPolicyUpdateResult(result)
      setPolicyReviewItem(null)
      const [nextModel, nextPolicyCoverage] = await Promise.all([
        loadDrsAdvisorModel(apiV1Client),
        loadDrsPolicyCoverage(apiV1Client),
      ])
      setModel(nextModel)
      setPolicyCoverage(nextPolicyCoverage)
      if (result.recommendationImpact) {
        setDetail(result.recommendationImpact)
        setCheckResult(null)
      }
    } catch (nextError) {
      setPolicyError(nextError instanceof Error ? nextError.message : 'Unable to update DRS policy')
    } finally {
      setSavingPolicyId(null)
    }
  }, [canOperate])

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

      <PolicyCoveragePanel
        policyCoverage={policyCoverage}
        filters={policyFilters}
        onPolicyFilterToggle={togglePolicyFilter}
        onConfidenceFilter={(confidence) => setPolicyFilters((current) => ({ ...current, confidence }))}
        canOperate={canOperate}
        savingPolicyId={savingPolicyId}
        onReviewPolicy={(item) => {
          setPolicyReviewItem(item)
          setPolicyError(null)
          setPolicyUpdateResult(null)
        }}
      />

      {policyUpdateResult && !policyReviewItem && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
          DRS policy saved for {policyUpdateResult.vmIdentityId}; migration approval remains separate.
        </div>
      )}

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
          <DetailPanel
            detail={detail}
            checkResult={checkResult}
            currentUser={currentUser}
            canOperate={canOperate}
            creatingApproval={creatingApproval}
            approvalResult={approvalResult}
            warningAcknowledged={warningAcknowledged}
            onWarningAcknowledgedChange={setWarningAcknowledged}
            onCreateApprovalPacket={createApprovalPacket}
          />
        </div>
      )}

      {policyReviewItem && (
        <PolicyReviewModal
          key={policyReviewItem.vmIdentityId}
          item={policyReviewItem}
          saving={savingPolicyId === policyReviewItem.vmIdentityId}
          error={policyError}
          result={policyUpdateResult}
          onCancel={() => setPolicyReviewItem(null)}
          onSubmit={submitPolicyReview}
        />
      )}
    </section>
  )
}

export default DrsAdvisorScreen
