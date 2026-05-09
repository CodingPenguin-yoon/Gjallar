import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

async function importExpected(path, description) {
  try {
    return await import(path)
  } catch (error) {
    assert.fail(`Expected ${description} at ${path}, but it is missing or invalid: ${error.message}`)
  }
}

const { loadRisksScreenModel } = await importExpected(
  '../src/utils/risksScreen.js',
  'Risks screen loader',
)

const calls = []
const fakeClient = {
  async listRisks() {
    calls.push('listRisks')
    return [
      { risk_id: 'risk-red', job_id: 'job-1', level: 'red', code: 'ip_collision', message: 'Static IP collision detected', artifacts_url: '/api/v1/jobs/job-1/artifacts' },
      { risk_id: 'risk-yellow', job_id: 'job-2', level: 'yellow', code: 'dhcp_discovery', message: 'DHCP requires operator review' },
      { risk_id: 'risk-green', job_id: 'job-3', level: 'green', code: 'policy_ok', message: 'No blocking risk' },
    ]
  },
  async getOperationalRisks() {
    calls.push('getOperationalRisks')
    throw new Error('legacy operational risks client must not be called')
  },
  async updateOperationalRiskThresholds() {
    calls.push('updateOperationalRiskThresholds')
    throw new Error('threshold mutation must not be called')
  },
  async updateOperationalRiskOverride() {
    calls.push('updateOperationalRiskOverride')
    throw new Error('risk override mutation must not be called')
  },
  async clearOperationalRiskOverride() {
    calls.push('clearOperationalRiskOverride')
    throw new Error('risk override clear mutation must not be called')
  },
}

const model = await loadRisksScreenModel(fakeClient)
assert.deepEqual(calls, ['listRisks'])
assert.equal(model.readOnly, true)
assert.deepEqual(model.allowedActions, [])
assert.equal(model.summary.total, 3)
assert.equal(model.summary.red, 1)
assert.equal(model.summary.yellow, 1)
assert.equal(model.summary.green, 1)
assert.equal(model.items[0].id, 'risk-red')
assert.equal(model.items[0].readOnly, true)
assert.deepEqual(model.items[0].allowedActions, [])

const source = readFileSync(new URL('../src/components/OperationalRiskDashboard.jsx', import.meta.url), 'utf8')
assert.match(source, /apiV1Client/)
assert.match(source, /loadRisksScreenModel/)
assert.doesNotMatch(source, /from ['"]\.\.\/services\/api(?:\.js)?['"]/, 'Risks screen must not import the legacy /api client')

const forbidden = (...parts) => parts.join('')
for (const blocked of [
  forbidden('get', 'OperationalRisks'),
  forbidden('update', 'OperationalRiskThresholds'),
  forbidden('update', 'OperationalRiskOverride'),
  forbidden('clear', 'OperationalRiskOverride'),
  forbidden('Threshold', 'Editor'),
  forbidden('Save', ' thresholds'),
  forbidden('Acknowledge'),
  forbidden('Suppress'),
  forbidden('Clear'),
  forbidden('override'),
  forbidden('suppression'),
  forbidden('include', 'Suppressed'),
  forbidden('/api/', 'risks'),
  forbidden('/api/', 'operational'),
  forbidden('window.', 'confirm'),
  forbidden('window.', 'prompt'),
]) {
  assert.ok(!source.toLowerCase().includes(blocked.toLowerCase()), `Risks screen must not expose legacy/edit term: ${blocked}`)
}

console.log('risksScreen RED contract exercised')
