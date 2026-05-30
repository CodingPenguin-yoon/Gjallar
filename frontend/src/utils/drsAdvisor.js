import { apiV1Client } from '../services/apiV1.js'

const READ_ONLY_ACTIONS = Object.freeze([])

function asArray(value) {
  return Array.isArray(value) ? value : []
}

function asObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function asText(value, fallback = '-') {
  const text = String(value ?? '').trim()
  return text || fallback
}

function asNumber(value, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function pickModel(payload) {
  const model = asObject(payload)
  return {
    summary: asObject(model.summary),
    recommendations: asArray(model.recommendations),
    thresholds: asObject(model.thresholds),
    execution: asObject(model.execution),
    evidence: asObject(model.evidence),
    readOnly: model.read_only !== false,
    executable: model.executable === true,
  }
}

function pickRecommendations(payload) {
  if (Array.isArray(payload)) return payload
  return asArray(asObject(payload).recommendations)
}

function normalizeExecution(source = {}) {
  return {
    available: source.available === true,
    allowedActions: asArray(source.allowed_actions ?? source.allowedActions),
    reason: asText(source.reason, 'Frontend DRS recommendation/check output is read-only; backend execution is a separate approval/job route.'),
  }
}

function normalizeBlockers(source = {}) {
  return asArray(source.blockers).map((blocker) => asText(blocker)).filter((blocker) => blocker !== '-')
}

function normalizeRecommendation(source = {}) {
  const effect = asObject(source.estimated_effect ?? source.estimatedEffect)
  const evidence = asObject(source.evidence)
  const identityEvidence = asObject(source.identity_evidence ?? source.identityEvidence ?? evidence.identity)
  const policyEvidence = asObject(source.policy_evidence ?? source.policyEvidence ?? evidence.policy)
  return {
    id: asText(source.id, 'unknown'),
    status: asText(source.status, 'blocked'),
    riskLevel: asText(source.risk_level ?? source.riskLevel, 'yellow'),
    vmid: source.vmid ?? null,
    vmName: asText(source.vm_name ?? source.vmName, 'unknown VM'),
    sourceNodeId: asText(source.source_node_id ?? source.sourceNodeId, 'unknown'),
    sourceNodeName: asText(source.source_node_name ?? source.sourceNodeName, source.source_node_id ?? source.sourceNodeId ?? 'unknown'),
    targetNodeId: asText(source.target_node_id ?? source.targetNodeId, 'unknown'),
    targetNodeName: asText(source.target_node_name ?? source.targetNodeName, source.target_node_id ?? source.targetNodeId ?? 'unknown'),
    reason: asText(source.reason, 'Review current DRS evidence'),
    blockers: normalizeBlockers(source),
    blockerDetails: asArray(source.blocker_details ?? source.blockerDetails),
    thresholds: asObject(source.thresholds),
    estimatedEffect: {
      sourcePressureBefore: asNumber(effect.source_pressure_before ?? effect.sourcePressureBefore),
      sourcePressureAfter: asNumber(effect.source_pressure_after ?? effect.sourcePressureAfter),
      targetPressureBefore: asNumber(effect.target_pressure_before ?? effect.targetPressureBefore),
      targetPressureAfter: asNumber(effect.target_pressure_after ?? effect.targetPressureAfter),
      sourceTargetDelta: asNumber(effect.source_target_delta ?? effect.sourceTargetDelta),
    },
    evidence,
    identityEvidence,
    policyEvidence,
    readOnly: source.read_only !== false,
    executable: source.executable === true,
    allowedActions: asArray(source.allowed_actions ?? source.allowedActions),
    execution: normalizeExecution(source.execution),
    raw: source,
  }
}

function normalizeSummary(source = {}) {
  const execution = normalizeExecution(source.execution)
  return {
    clusterState: asText(source.cluster_state ?? source.clusterState, 'unknown'),
    totalNodes: asNumber(source.total_nodes ?? source.totalNodes),
    onlineNodes: asNumber(source.online_nodes ?? source.onlineNodes),
    totalVms: asNumber(source.total_vms ?? source.totalVms),
    runningCandidateVms: asNumber(source.running_candidate_vms ?? source.runningCandidateVms),
    excludedRedRiskVms: asNumber(source.excluded_red_risk_vms ?? source.excludedRedRiskVms),
    recommendationCount: asNumber(source.recommendation_count ?? source.recommendationCount),
    hotNodeCount: asNumber(source.hot_node_count ?? source.hotNodeCount),
    criticalNodeCount: asNumber(source.critical_node_count ?? source.criticalNodeCount),
    sourceTargetDelta: asNumber(source.source_target_delta ?? source.sourceTargetDelta),
    thresholds: asObject(source.thresholds),
    readOnly: source.read_only !== false,
    executable: source.executable === true,
    execution,
  }
}

function statusTone(status) {
  const normalized = String(status ?? '').toLowerCase()
  if (normalized === 'critical') return 'red'
  if (normalized === 'hot' || normalized === 'blocked' || normalized === 'yellow') return 'yellow'
  if (normalized === 'balanced' || normalized === 'green') return 'green'
  return 'slate'
}

export function buildDrsAdvisorViewModel({ summaryPayload = {}, recommendationsPayload = {} } = {}) {
  const summaryModel = pickModel(summaryPayload)
  const recommendationModel = pickModel(recommendationsPayload)
  const rawRecommendations = pickRecommendations(recommendationsPayload).length
    ? pickRecommendations(recommendationsPayload)
    : summaryModel.recommendations
  const recommendations = rawRecommendations.map(normalizeRecommendation)
  const summary = normalizeSummary(
    Object.keys(recommendationModel.summary).length ? recommendationModel.summary : summaryModel.summary,
  )
  const thresholds = Object.keys(recommendationModel.thresholds).length
    ? recommendationModel.thresholds
    : summaryModel.thresholds
  const execution = normalizeExecution(
    Object.keys(recommendationModel.execution).length ? recommendationModel.execution : summaryModel.execution,
  )
  return {
    summary,
    recommendations,
    thresholds,
    execution,
    evidence: Object.keys(recommendationModel.evidence).length ? recommendationModel.evidence : summaryModel.evidence,
    status: summary.clusterState,
    tone: statusTone(summary.clusterState),
    readOnly: true,
    executable: false,
    allowedActions: READ_ONLY_ACTIONS,
  }
}

export async function loadDrsAdvisorModel(client = apiV1Client) {
  for (const method of ['getDrsSummary', 'listDrsRecommendations']) {
    if (!client || typeof client[method] !== 'function') {
      throw new Error(`DRS Advisor requires an /api/v1 client with ${method}()`)
    }
  }
  const [summaryPayload, recommendationsPayload] = await Promise.all([
    client.getDrsSummary(),
    client.listDrsRecommendations(),
  ])
  return buildDrsAdvisorViewModel({ summaryPayload, recommendationsPayload })
}

export async function loadDrsRecommendationDetail(client = apiV1Client, recommendationId) {
  if (!client || typeof client.getDrsRecommendation !== 'function') {
    throw new Error('DRS Advisor requires an /api/v1 client with getDrsRecommendation()')
  }
  return normalizeRecommendation(await client.getDrsRecommendation(recommendationId))
}

export async function checkDrsRecommendation(client = apiV1Client, recommendationId, payload = {}) {
  if (!client || typeof client.checkDrsRecommendation !== 'function') {
    throw new Error('DRS Advisor requires an /api/v1 client with checkDrsRecommendation()')
  }
  const result = asObject(await client.checkDrsRecommendation(recommendationId, payload))
  return {
    recommendationId: asText(result.recommendation_id ?? result.recommendationId, recommendationId),
    readOnly: result.read_only !== false,
    executable: result.executable === true,
    wouldBeExecutable: result.would_be_executable === true || result.wouldBeExecutable === true,
    execution: normalizeExecution(result.execution),
    blockers: normalizeBlockers(result),
    identityEvidence: asObject(result.identity_evidence ?? result.identityEvidence),
    policyEvidence: asObject(result.policy_evidence ?? result.policyEvidence),
    checkedAt: asText(result.checked_at ?? result.checkedAt, ''),
    check: asObject(result.check),
    recommendation: normalizeRecommendation(result.recommendation),
  }
}

export function drsToneClass(tone) {
  const normalized = String(tone ?? '').toLowerCase()
  if (normalized === 'green' || normalized === 'balanced') return 'border-emerald-200 bg-emerald-50 text-emerald-800'
  if (normalized === 'yellow' || normalized === 'hot' || normalized === 'blocked') return 'border-amber-200 bg-amber-50 text-amber-800'
  if (normalized === 'red' || normalized === 'critical') return 'border-red-200 bg-red-50 text-red-800'
  return 'border-slate-200 bg-slate-50 text-slate-800'
}

export function formatDrsBlocker(code) {
  return asText(code).replaceAll('_', ' ')
}
