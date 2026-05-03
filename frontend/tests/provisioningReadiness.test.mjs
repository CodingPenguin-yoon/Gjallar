import assert from 'node:assert/strict'
import { summarizeProvisioningReadiness } from '../src/utils/provisioningReadiness.js'

const readySummary = summarizeProvisioningReadiness({
  status: 'ready',
  checks: [
    { id: 'terraform_cli', status: 'ok' },
    { id: 'ansible_playbook_cli', status: 'ok' },
  ],
  next_actions: [],
})

assert.equal(readySummary.tone, 'green')
assert.equal(readySummary.canProvision, true)
assert.equal(readySummary.counts.ok, 2)
assert.equal(readySummary.counts.warning, 0)
assert.equal(readySummary.counts.error, 0)
assert.deepEqual(readySummary.nextActions, ['Provisioning runtime is ready.'])

const warningSummary = summarizeProvisioningReadiness({
  status: 'warning',
  checks: [
    { id: 'terraform_cli', status: 'ok' },
    { id: 'terraform_validate', status: 'warning' },
  ],
})

assert.equal(warningSummary.tone, 'yellow')
assert.equal(warningSummary.canProvision, true)
assert.equal(warningSummary.counts.warning, 1)

const errorSummary = summarizeProvisioningReadiness({
  status: 'error',
  checks: [
    { id: 'terraform_cli', status: 'error' },
    { id: 'ansible_playbook_cli', status: 'ok' },
  ],
  next_actions: ['Install terraform.'],
})

assert.equal(errorSummary.tone, 'red')
assert.equal(errorSummary.canProvision, false)
assert.equal(errorSummary.counts.error, 1)
assert.deepEqual(errorSummary.nextActions, ['Install terraform.'])

const emptySummary = summarizeProvisioningReadiness(null)
assert.equal(emptySummary.tone, 'gray')
assert.equal(emptySummary.canProvision, false)
assert.equal(emptySummary.label, 'Readiness unknown')

console.log('provisioningReadiness tests passed')
