import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

async function importExpected(path, description) {
  try {
    return await import(path)
  } catch (error) {
    assert.fail(`Expected ${description} at ${path}, but it is missing or invalid: ${error.message}`)
  }
}

const {
  buildDrsAdvisorViewModel,
  checkDrsRecommendation,
  drsToneClass,
  formatDrsBlocker,
  loadDrsAdvisorModel,
  loadDrsRecommendationDetail,
} = await importExpected('../src/utils/drsAdvisor.js', 'DRS Advisor view model utility')

const recommendation = {
  id: 'drs-rec-vm-101-node-a-node-b',
  status: 'blocked',
  risk_level: 'yellow',
  vmid: 101,
  vm_name: 'app-01',
  source_node_id: 'node-a',
  source_node_name: 'node-a',
  target_node_id: 'node-b',
  target_node_name: 'node-b',
  reason: 'Source node is hot and target pressure is lower by 42%.',
  blockers: ['migration_policy_unknown', 'policy_unknown', 'final_precheck_not_run', 'local_storage_dependency'],
  identity_evidence: {
    vm_identity_id: 'vmid-1',
    stable_fingerprint: 'sha256:abcdef0123456789',
    match_confidence: 'high',
    identity_status: 'active',
  },
  policy_evidence: {
    policy: 'unknown',
    source: 'default',
    reason: 'No DRS migration policy has been recorded',
  },
  thresholds: { hot: 70, critical: 85, source_target_delta: 25 },
  estimated_effect: {
    source_pressure_before: 82,
    source_pressure_after: 74,
    target_pressure_before: 40,
    target_pressure_after: 48,
    source_target_delta: 42,
  },
  evidence: {
    route: {
      matching_target_bridge_ids: ['vmbr0'],
      network_evidence_sufficient: true,
      storage_evidence_sufficient: true,
    },
  },
  read_only: true,
  executable: false,
  allowed_actions: [],
  execution: {
    available: false,
    allowed_actions: [],
    reason: 'DRS Phase 1 is advisory only',
  },
}

const drsModel = {
  summary: {
    cluster_state: 'hot',
    total_nodes: 2,
    online_nodes: 2,
    total_vms: 4,
    running_candidate_vms: 3,
    excluded_red_risk_vms: 1,
    recommendation_count: 1,
    hot_node_count: 1,
    critical_node_count: 0,
    source_target_delta: 42,
    thresholds: { hot: 70, critical: 85, source_target_delta: 25 },
    read_only: true,
    executable: false,
    execution: { available: false, allowed_actions: [], reason: 'advisory only' },
  },
  recommendations: [recommendation],
  thresholds: { hot: 70, critical: 85, source_target_delta: 25 },
  read_only: true,
  executable: false,
  allowed_actions: [],
  execution: { available: false, allowed_actions: [], reason: 'advisory only' },
}

const viewModel = buildDrsAdvisorViewModel({
  summaryPayload: drsModel,
  recommendationsPayload: drsModel,
})
assert.equal(viewModel.readOnly, true)
assert.equal(viewModel.executable, false)
assert.equal(viewModel.summary.clusterState, 'hot')
assert.equal(viewModel.summary.recommendationCount, 1)
assert.equal(viewModel.summary.runningCandidateVms, 3)
assert.equal(viewModel.summary.excludedRedRiskVms, 1)
assert.equal(viewModel.thresholds.hot, 70)
assert.equal(viewModel.thresholds.critical, 85)
assert.equal(viewModel.thresholds.source_target_delta, 25)
assert.equal(viewModel.execution.available, false)
assert.equal(viewModel.recommendations[0].id, recommendation.id)
assert.equal(viewModel.recommendations[0].vmName, 'app-01')
assert.deepEqual(viewModel.recommendations[0].blockers, recommendation.blockers)
assert.equal(viewModel.recommendations[0].identityEvidence.match_confidence, 'high')
assert.equal(viewModel.recommendations[0].policyEvidence.policy, 'unknown')
assert.equal(viewModel.recommendations[0].estimatedEffect.sourceTargetDelta, 42)
assert.equal(drsToneClass('critical').includes('red'), true)
assert.equal(drsToneClass('hot').includes('amber'), true)
assert.equal(formatDrsBlocker('identity_unknown'), 'identity unknown')

const calls = []
const fakeClient = {
  async getDrsSummary() {
    calls.push('getDrsSummary')
    return drsModel
  },
  async listDrsRecommendations() {
    calls.push('listDrsRecommendations')
    return drsModel
  },
  async getDrsRecommendation(id) {
    calls.push(`getDrsRecommendation:${id}`)
    return recommendation
  },
  async checkDrsRecommendation(id, payload) {
    calls.push(`checkDrsRecommendation:${id}:${payload.reference_only === true}`)
    return {
      recommendation_id: id,
      read_only: true,
      executable: false,
      would_be_executable: false,
      execution: { available: false, allowed_actions: [], reason: 'advisory only' },
      blockers: recommendation.blockers,
      identity_evidence: recommendation.identity_evidence,
      policy_evidence: recommendation.policy_evidence,
      check: {
        status: 'blocked',
        reference_only: true,
        recalculated: true,
        blockers: recommendation.blockers,
      },
      recommendation,
    }
  },
}

const loaded = await loadDrsAdvisorModel(fakeClient)
assert.equal(loaded.summary.clusterState, 'hot')
assert.equal(loaded.recommendations.length, 1)
assert.deepEqual(calls, ['getDrsSummary', 'listDrsRecommendations'])

const detail = await loadDrsRecommendationDetail(fakeClient, recommendation.id)
assert.equal(detail.id, recommendation.id)
const checkResult = await checkDrsRecommendation(fakeClient, recommendation.id, { reference_only: true })
assert.equal(checkResult.recommendationId, recommendation.id)
assert.equal(checkResult.readOnly, true)
assert.equal(checkResult.executable, false)
assert.equal(checkResult.wouldBeExecutable, false)
assert.equal(checkResult.check.reference_only, true)
assert.equal(checkResult.execution.available, false)
assert.equal(checkResult.identityEvidence.match_confidence, 'high')
assert.equal(checkResult.policyEvidence.policy, 'unknown')

const utilitySource = readFileSync(new URL('../src/utils/drsAdvisor.js', import.meta.url), 'utf8')
for (const forbidden of ['loadPlacementModel', 'buildPlacementViewModel', 'listNodes', 'listVms', 'listStorage', 'listNetworks']) {
  assert.ok(!utilitySource.includes(forbidden), `DRS Advisor utility must not use frontend-only Placement calculation or inventory endpoint ${forbidden}`)
}
assert.match(utilitySource, /getDrsSummary/)
assert.match(utilitySource, /listDrsRecommendations/)
assert.match(utilitySource, /getDrsRecommendation/)
assert.match(utilitySource, /checkDrsRecommendation/)

const screenSource = readFileSync(new URL('../src/components/DrsAdvisorScreen.jsx', import.meta.url), 'utf8')
assert.match(screenSource, /loadDrsAdvisorModel/)
assert.match(screenSource, /loadDrsRecommendationDetail/)
assert.match(screenSource, /checkDrsRecommendation/)
assert.match(screenSource, /Balance Overview/)
assert.match(screenSource, /RecommendationQueue/)
assert.match(screenSource, /Recommendation Queue/)
assert.match(screenSource, /PressureBar/)
assert.match(screenSource, /Source Pressure/)
assert.match(screenSource, /Target Pressure/)
assert.match(screenSource, /Projected Target/)
assert.match(screenSource, /Route Status/)
assert.match(screenSource, /Network evidence/)
assert.match(screenSource, /Storage evidence/)
assert.match(screenSource, /CompactBlockerList/)
assert.match(screenSource, /Detail/)
assert.match(screenSource, /Check/)
assert.match(screenSource, /Route Evidence/)
assert.match(screenSource, /Storage Evidence/)
assert.match(screenSource, /Passthrough Evidence/)
assert.match(screenSource, /Target Threshold/)
assert.match(screenSource, /Identity \/ Metadata \/ Policy/)
assert.match(screenSource, /Execution Boundary/)
assert.match(screenSource, /executable false/)
assert.match(screenSource, /allowed actions: none/)
assert.match(screenSource, /allowed actions none/)
assert.doesNotMatch(screenSource, /Approve & Migrate/)
assert.doesNotMatch(screenSource, /Recommendation Impact|RecommendationImpactList|RecommendationTable|<table|overflow-x-auto/)
assert.doesNotMatch(screenSource, /PlacementScreen|loadPlacementModel|placementToneClass/)

console.log('drsAdvisor RED contract exercised')
