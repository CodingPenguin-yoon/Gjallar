import assert from 'node:assert/strict'
import {
  formatRiskScope,
  getRiskSeverityTone,
  groupRisksByCategory,
  normalizeRiskDashboard,
  sortRiskItems,
} from '../src/utils/operationalRisk.js'

const payload = {
  status: 'warning',
  generated_at: 1700000000,
  summary: {
    total_risks: 3,
    critical: 1,
    warning: 1,
    info: 1,
    affected_nodes: 2,
    affected_vms: 1,
    total_nodes: 3,
    total_vms: 7,
    categories: { storage_capacity: 1, governance: 1, guest_agent: 1 },
  },
  risk_items: [
    { id: 'info', severity: 'info', category: 'governance', scope: 'vm', node: 'node-b', vmid: 20, vm_name: 'vm-b' },
    { id: 'critical', severity: 'critical', category: 'storage_capacity', scope: 'storage', node: 'node-a' },
    { id: 'warning', severity: 'warning', category: 'guest_agent', scope: 'vm', node: 'node-a', vmid: 10, vm_name: 'vm-a' },
  ],
}

const dashboard = normalizeRiskDashboard(payload)
assert.equal(dashboard.summary.totalRisks, 3)
assert.equal(dashboard.summary.affectedNodes, 2)
assert.equal(getRiskSeverityTone('critical').level, 'critical')
assert.equal(getRiskSeverityTone('unknown').level, 'info')
assert.deepEqual(sortRiskItems(payload.risk_items).map((item) => item.id), ['critical', 'warning', 'info'])
assert.equal(Object.keys(groupRisksByCategory(payload.risk_items)).length, 3)
assert.equal(formatRiskScope(payload.risk_items[2]), 'node-a/10 vm-a')

console.log('operationalRisk tests passed')
