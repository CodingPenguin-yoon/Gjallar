import assert from 'node:assert/strict'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const srcRoot = fileURLToPath(new URL('../src/', import.meta.url))

function sourceFiles(root) {
  return readdirSync(root)
    .flatMap((entry) => {
      const path = join(root, entry)
      return statSync(path).isDirectory() ? sourceFiles(path) : [path]
    })
    .filter((path) => path.endsWith('.js') || path.endsWith('.jsx'))
}

const {
  INSIGHT_CATEGORIES,
  insightSectionCoverageComplete,
  normalizeInsightsSnapshot,
} = await import('../src/entities/insight/model.js')
const {
  loadInsightsModel,
  selectExactTargetFindingView,
} = await import('../src/features/insights/model.js')

const payload = {
  generated_at: '2026-07-21T02:00:00+00:00',
  status: 'partial',
  execution_mode: 'observe_only',
  read_only: true,
  allowed_actions: [],
  connection: { state: 'unconfigured', freshness: 'unavailable' },
  sections: {
    risk: {
      status: 'attention',
      available: true,
      source: 'job_runs',
      observed_at: '2026-07-21T01:00:00+00:00',
      freshness: 'recorded',
      rule_version: 'job-risk.v1',
      summary: { finding_count: 1 },
      findings: [{
        finding_id: 'insight-risk-1',
        severity: 'critical',
        status: 'active',
        code: 'blocked',
        title: 'Blocked job',
        message: 'Review required',
        target: { type: 'job', id: 'job-1' },
        source: 'job_runs',
        observed_at: '2026-07-21T01:00:00+00:00',
        freshness: 'recorded',
        rule_version: 'job-risk.v1',
        evidence: { job_id: 'job-1' },
        read_only: true,
        allowed_actions: [],
      }],
      read_only: true,
      allowed_actions: [],
    },
    readiness: {
      status: 'unavailable', available: false, source: 'unavailable', observed_at: null,
      freshness: 'unavailable', rule_version: 'operational-readiness.v1', summary: { finding_count: 0 },
      findings: [], unavailable_reason: 'proxmox_unconfigured', read_only: true, allowed_actions: [],
    },
    placement: {
      status: 'attention',
      available: true,
      source: 'drs_advisor',
      observed_at: '2026-07-21T01:00:00+00:00',
      freshness: 'recorded',
      rule_version: 'placement-insight.v1',
      summary: { finding_count: 1 },
      findings: [{
        finding_id: 'drs-rec-vm-101-node-a-node-b',
        severity: 'warning',
        status: 'active',
        code: 'placement_candidate',
        title: 'Placement candidate',
        message: 'Review current placement evidence.',
        target: { type: 'vm', id: '101' },
        source: 'drs_advisor',
        observed_at: '2026-07-21T01:00:00+00:00',
        freshness: 'recorded',
        rule_version: 'placement-insight.v1',
        evidence: { source_node_id: 'node-a', candidate_node_id: 'node-b' },
        read_only: true,
        allowed_actions: [],
      }],
      read_only: true,
      allowed_actions: [],
    },
  },
}

const model = normalizeInsightsSnapshot(payload)
assert.deepEqual(INSIGHT_CATEGORIES, ['risk', 'readiness', 'capacity', 'placement'])
assert.equal(model.executionMode, 'observe_only')
assert.equal(model.readOnly, true)
assert.deepEqual(model.allowedActions, [])
assert.equal(model.sections.risk.findings[0].targetId, 'job-1')
assert.equal(model.sections.readiness.available, false)
assert.equal(model.sections.readiness.unavailableReason, 'proxmox_unconfigured')
assert.equal(model.sections.capacity.status, 'unavailable')
assert.equal(model.sections.placement.available, true)
assert.equal(model.sections.placement.source, 'drs_advisor', 'Insight source identifiers must remain opaque compatibility values')
assert.equal(model.sections.placement.findings[0].id, 'drs-rec-vm-101-node-a-node-b', 'Insight finding IDs must remain opaque compatibility values')
assert.equal(model.sections.placement.findings[0].source, 'drs_advisor')
assert.equal(insightSectionCoverageComplete({
  available: true,
  status: 'ready',
  freshness: 'fresh',
  summary: { finding_count: 0, returned_finding_count: 0, truncated: false },
}), true)
for (const incompleteSection of [
  { available: true, status: 'unknown', freshness: 'fresh', summary: {} },
  { available: true, status: 'ready', freshness: 'partial', summary: {} },
  { available: true, status: 'ready', freshness: 'stale', summary: {} },
  { available: true, status: 'error', freshness: 'fresh', summary: {} },
  { available: true, status: 'ready', freshness: 'expired', summary: {} },
  { available: true, status: 'ready', freshness: 'fresh', summary: { finding_count: 201, returned_finding_count: 200, truncated: true } },
]) {
  assert.equal(insightSectionCoverageComplete(incompleteSection), false)
}

const loaded = await loadInsightsModel({ getInsights: async () => payload })
assert.equal(loaded.sections.risk.findings.length, 1)

const exactTargetSections = [{
  category: 'readiness',
  findings: [
    { id: 'finding-current', targetType: 'proxmox_vm', targetId: 'vmid:101' },
    { id: 'finding-other-target', targetType: 'proxmox_vm', targetId: 'vmid:102' },
  ],
}]
const matchedFindingView = selectExactTargetFindingView(exactTargetSections, {
  targetType: 'proxmox_vm', targetId: 'vmid:101', findingId: 'finding-current',
})
assert.equal(matchedFindingView.requestedFindingMatched, true)
assert.deepEqual(matchedFindingView.sections[0].findings.map((finding) => finding.id), ['finding-current'])
const staleFindingView = selectExactTargetFindingView(exactTargetSections, {
  targetType: 'proxmox_vm', targetId: 'vmid:101', findingId: 'finding-stale',
})
assert.equal(staleFindingView.requestedFindingMatched, false)
assert.deepEqual(staleFindingView.sections[0].findings.map((finding) => finding.id), ['finding-current'])

const explorer = readFileSync(new URL('../src/features/insights/InsightsExplorer.jsx', import.meta.url), 'utf8')
const featureModel = readFileSync(new URL('../src/features/insights/model.js', import.meta.url), 'utf8')
const appSource = readFileSync(new URL('../src/app/App.jsx', import.meta.url), 'utf8')

assert.match(explorer, /allowed actions: none/, 'Insights must make the execution-closed boundary visible')
assert.match(explorer, /빈 결과를 정상 상태로 해석하지 않습니다/, 'Unavailable sources must not render as healthy empty data')
assert.match(explorer, /section\.ruleVersion/, 'Every section view must expose its rule version')
assert.match(explorer, /finding\.evidence/, 'Finding details must expose evidence')
assert.match(explorer, /section\.summary\.truncated/, 'Bounded finding results must disclose truncation in the UI')
assert.match(explorer, /finding 부재를 확정할 수 없습니다/, 'Incomplete exact-target coverage must not render as a definitive no-finding state')
assert.match(explorer, /현재 반환된 exact-target finding을 대신 표시합니다/, 'A stale finding link must preserve current exact-target evidence')
assert.match(featureModel, /client\.getInsights\(\)/, 'Insights feature must use the additive read client')
for (const forbidden of ['createDrsApprovalPacket', 'recordJobRun', 'executeDrsMigration', 'approveVmDraft', 'createVmDraft']) {
  assert.equal(explorer.includes(forbidden), false, `Insights UI must not expose command capability: ${forbidden}`)
  assert.equal(featureModel.includes(forbidden), false, `Insights model must not expose command capability: ${forbidden}`)
}

const canonicalInsightsSources = [
  ...sourceFiles(join(srcRoot, 'features', 'insights')),
  join(srcRoot, 'pages', 'insights', 'InsightsPage.jsx'),
]
const forbiddenDrsMaintenanceCapabilities = [
  'DrsAdvisorScreen',
  'DrsPoliciesScreen',
  'DrsPolicyReviewModal',
  'checkDrsRecommendation',
  'createDrsApprovalPacket',
  'updateDrsPolicy',
  'reconcilePreviewDrsMigrationJob',
]
for (const path of canonicalInsightsSources) {
  const source = readFileSync(path, 'utf8')
  for (const forbidden of forbiddenDrsMaintenanceCapabilities) {
    assert.equal(
      source.includes(forbidden),
      false,
      `${relative(srcRoot, path)} must not consume DRS maintenance capability: ${forbidden}`,
    )
  }
}

const drsConsumerPattern = /\b(?:DrsAdvisorScreen|DrsPoliciesScreen|DrsPolicyReviewModal|getDrsSummary|listDrsRecommendations|getDrsRecommendation|checkDrsRecommendation|createDrsApprovalPacket|drsPolicies|drsPolicy|updateDrsPolicy|reconcilePreviewDrsMigrationJob)\b/
const drsConsumerFiles = sourceFiles(srcRoot)
  .filter((path) => drsConsumerPattern.test(readFileSync(path, 'utf8')))
  .map((path) => relative(srcRoot, path))
  .sort()
assert.deepEqual(drsConsumerFiles, [], 'DRS maintenance must not have a frontend consumer')

const drsRoutes = [...appSource.matchAll(/path="([^"]*drs[^"]*)"/gi)]
  .map((match) => match[1])
  .sort()
assert.deepEqual(
  drsRoutes,
  [],
  'DRS maintenance must not have a frontend route',
)

console.log('Insights product and execution-closed UI contract exercised')
