import assert from 'node:assert/strict'
import { buildMonitoringSummary, getResourceTone } from '../src/utils/monitoringSignals.js'

const nodes = [
  { node: 'pve-01', status: 'online', cpu_usage_percent: 20, memory_usage_percent: 72, storages: [{ name: 'local', usage_percent: 91 }] },
  { node: 'pve-02', status: 'offline', cpu_usage_percent: 95, memory_usage_percent: 40, storages: [{ name: 'data', usage_percent: 65 }] },
]
const summary = buildMonitoringSummary(nodes)
assert.equal(summary.totalNodes, 2)
assert.equal(summary.onlineNodes, 1)
assert.equal(summary.criticalSignals, 3)
assert.equal(summary.warningSignals, 1)
assert.equal(getResourceTone(91).level, 'critical')
assert.equal(getResourceTone(72).level, 'warning')

console.log('monitoringSignals tests passed')
