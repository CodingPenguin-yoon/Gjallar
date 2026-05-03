import assert from 'node:assert/strict'
import { summarizeResourcePreflight } from '../src/utils/resourcePreflight.js'

const readySummary = summarizeResourcePreflight({
  status: 'ready',
  checks: [
    { id: 'target_node', status: 'ok' },
    { id: 'template', status: 'ok' },
    { id: 'storage', status: 'ok' },
    { id: 'networks', status: 'ok' },
  ],
  next_actions: [],
})

assert.equal(readySummary.tone, 'green')
assert.equal(readySummary.canProvision, true)
assert.equal(readySummary.counts.ok, 4)
assert.deepEqual(readySummary.nextActions, ['Selected Proxmox resources are ready.'])

const warningSummary = summarizeResourcePreflight({
  status: 'warning',
  checks: [
    { id: 'storage', status: 'warning' },
  ],
})

assert.equal(warningSummary.tone, 'yellow')
assert.equal(warningSummary.canProvision, true)
assert.equal(warningSummary.counts.warning, 1)

const errorSummary = summarizeResourcePreflight({
  status: 'error',
  checks: [
    { id: 'template', status: 'error' },
  ],
  next_actions: ['Refresh templates.'],
})

assert.equal(errorSummary.tone, 'red')
assert.equal(errorSummary.canProvision, false)
assert.equal(errorSummary.counts.error, 1)
assert.deepEqual(errorSummary.nextActions, ['Refresh templates.'])

const emptySummary = summarizeResourcePreflight(null)
assert.equal(emptySummary.tone, 'gray')
assert.equal(emptySummary.canProvision, false)
assert.equal(emptySummary.label, 'Resource check unknown')

console.log('resourcePreflight tests passed')
