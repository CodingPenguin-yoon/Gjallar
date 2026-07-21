import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const {
  INSIGHT_CATEGORIES,
  normalizeInsightsSnapshot,
} = await import('../src/entities/insight/model.js')
const { loadInsightsModel } = await import('../src/features/insights/model.js')

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
assert.equal(model.sections.placement.available, false)

const loaded = await loadInsightsModel({ getInsights: async () => payload })
assert.equal(loaded.sections.risk.findings.length, 1)

const explorer = readFileSync(new URL('../src/features/insights/InsightsExplorer.jsx', import.meta.url), 'utf8')
const featureModel = readFileSync(new URL('../src/features/insights/model.js', import.meta.url), 'utf8')
const drsMaintenance = readFileSync(new URL('../src/components/DrsAdvisorScreen.jsx', import.meta.url), 'utf8')

assert.match(explorer, /allowed actions: none/, 'Insights must make the execution-closed boundary visible')
assert.match(explorer, /빈 결과를 정상 상태로 해석하지 않습니다/, 'Unavailable sources must not render as healthy empty data')
assert.match(explorer, /section\.ruleVersion/, 'Every section view must expose its rule version')
assert.match(explorer, /finding\.evidence/, 'Finding details must expose evidence')
assert.match(explorer, /section\.summary\.truncated/, 'Bounded finding results must disclose truncation in the UI')
assert.match(featureModel, /client\.getInsights\(\)/, 'Insights feature must use the additive read client')
for (const forbidden of ['createDrsApprovalPacket', 'recordJobRun', 'executeDrsMigration', 'approveVmDraft', 'createVmDraft']) {
  assert.equal(explorer.includes(forbidden), false, `Insights UI must not expose command capability: ${forbidden}`)
  assert.equal(featureModel.includes(forbidden), false, `Insights model must not expose command capability: ${forbidden}`)
}
assert.match(drsMaintenance, /Maintenance compatibility surface/, 'Legacy DRS must identify itself as maintenance')
assert.match(drsMaintenance, /to="\/insights\/placement"/, 'Legacy DRS must link to canonical Placement Insights')

console.log('Insights product and execution-closed UI contract exercised')
