import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

async function importExpected(path, description) {
  try {
    return await import(path)
  } catch (error) {
    assert.fail(`Expected ${description} at ${path}, but it is missing or invalid: ${error.message}`)
  }
}

const { buildPlacementViewModel, loadPlacementModel } = await importExpected(
  '../src/utils/placement.js',
  'Placement view model utility',
)

const baseNodes = [
  {
    node_id: 'yoonmanserver2',
    display_name: 'yoonmanserver2',
    status: 'online',
    cpu_usage_percent: 24,
    memory_usage_percent: 31,
    memory_total_mb: 65536,
    memory_used_mb: 20316,
  },
  {
    node_id: 'yoonmanserver3',
    display_name: 'yoonmanserver3',
    status: 'online',
    cpu_usage_percent: 22,
    memory_usage_percent: 29,
    memory_total_mb: 65536,
    memory_used_mb: 19005,
  },
]

const baseStorage = [
  { storage_id: 'local-lvm', node_id: 'yoonmanserver2', type: 'lvmthin', total_gb: 512, free_gb: 220, content: ['images'] },
  { storage_id: 'local-lvm', node_id: 'yoonmanserver3', type: 'lvmthin', total_gb: 512, free_gb: 260, content: ['images'] },
]

const baseNetworks = [
  { bridge_id: 'vmbr0', node_id: 'yoonmanserver2', active: true },
  { bridge_id: 'vmbr0', node_id: 'yoonmanserver3', active: true },
]

const baseVms = [
  {
    vmid: 101,
    name: 'app-01',
    node_id: 'yoonmanserver2',
    status: 'running',
    template: false,
    memory_mb: 4096,
    disk_gb: 40,
    storage_id: 'local-lvm',
    ip_addresses: ['192.168.2.141'],
    guest_agent: { available: true },
  },
  {
    vmid: 102,
    name: 'app-02',
    node_id: 'yoonmanserver3',
    status: 'stopped',
    template: false,
    memory_mb: 2048,
    disk_gb: 20,
    storage_id: 'local-lvm',
  },
]

const balanced = buildPlacementViewModel({
  cluster: { cluster_id: 'gjallar-mvp' },
  nodes: baseNodes,
  vms: baseVms,
  storage: baseStorage,
  networks: baseNetworks,
  risks: [],
})
assert.equal(balanced.readOnly, true)
assert.deepEqual(balanced.allowedActions, [])
assert.equal(balanced.status, 'Balanced')
assert.equal(balanced.summary.totalNodes, 2)
assert.equal(balanced.summary.onlineNodes, 2)
assert.equal(balanced.summary.runningVms, 1)
assert.equal(balanced.summary.busiestNode, 'yoonmanserver2')
assert.equal(balanced.summary.roomiestNode, 'yoonmanserver3')

const watch = buildPlacementViewModel({
  nodes: [
    { ...baseNodes[0], cpu_usage_percent: 72, memory_usage_percent: 64 },
    { ...baseNodes[1], cpu_usage_percent: 35, memory_usage_percent: 32 },
  ],
  vms: baseVms,
  storage: baseStorage,
  networks: baseNetworks,
  risks: [],
})
assert.equal(watch.status, 'Watch')
assert.equal(watch.summary.cpuImbalance, 37)

const imbalanced = buildPlacementViewModel({
  nodes: [
    { ...baseNodes[0], cpu_usage_percent: 86, memory_usage_percent: 76 },
    { ...baseNodes[1], cpu_usage_percent: 31, memory_usage_percent: 34 },
  ],
  vms: baseVms,
  storage: baseStorage,
  networks: baseNetworks,
  risks: [],
})
assert.equal(imbalanced.status, 'Imbalanced')

const recommended = buildPlacementViewModel({
  nodes: [
    { ...baseNodes[0], cpu_usage_percent: 82, memory_usage_percent: 76 },
    { ...baseNodes[1], cpu_usage_percent: 31, memory_usage_percent: 42 },
  ],
  vms: [
    { ...baseVms[0], node_id: 'yoonmanserver2', status: 'running', memory_mb: 8192 },
    { ...baseVms[1], node_id: 'yoonmanserver2', status: 'running', memory_mb: 4096 },
  ],
  storage: baseStorage,
  networks: baseNetworks,
  risks: [],
})
assert.equal(recommended.recommendations.length > 0, true)
assert.equal(recommended.recommendations[0].sourceNodeId, 'yoonmanserver2')
assert.equal(recommended.recommendations[0].targetNodeId, 'yoonmanserver3')
assert.equal(recommended.recommendations[0].reason, 'Source node is hotter and target node has capacity')
assert.equal(recommended.recommendations[0].execution.available, false)
assert.equal(recommended.recommendations[0].readOnly, true)
assert.deepEqual(recommended.recommendations[0].allowedActions, [])

const offlineTarget = buildPlacementViewModel({
  nodes: [
    { ...baseNodes[0], cpu_usage_percent: 82, memory_usage_percent: 76 },
    { ...baseNodes[1], status: 'offline', cpu_usage_percent: 10, memory_usage_percent: 12 },
  ],
  vms: [{ ...baseVms[0], node_id: 'yoonmanserver2', status: 'running' }],
  storage: baseStorage,
  networks: baseNetworks,
  risks: [],
})
assert.equal(offlineTarget.recommendations.length, 0)

const redRiskVm = buildPlacementViewModel({
  nodes: [
    { ...baseNodes[0], cpu_usage_percent: 82, memory_usage_percent: 76 },
    { ...baseNodes[1], cpu_usage_percent: 31, memory_usage_percent: 42 },
  ],
  vms: [{ ...baseVms[0], node_id: 'yoonmanserver2', status: 'running' }],
  storage: baseStorage,
  networks: baseNetworks,
  risks: [{ risk_id: 'risk-101', vmid: 101, level: 'red', code: 'vm_blocked' }],
})
assert.equal(redRiskVm.recommendations.length, 0)

const missingBridgeEvidence = buildPlacementViewModel({
  nodes: [
    { ...baseNodes[0], cpu_usage_percent: 82, memory_usage_percent: 76 },
    { ...baseNodes[1], cpu_usage_percent: 31, memory_usage_percent: 42 },
  ],
  vms: [{ ...baseVms[0], node_id: 'yoonmanserver2', status: 'running' }],
  storage: baseStorage,
  networks: [{ bridge_id: 'vmbr0', node_id: 'yoonmanserver2', active: true }],
  risks: [],
})
assert.equal(missingBridgeEvidence.recommendations.length, 1)
assert.equal(missingBridgeEvidence.recommendations[0].riskLevel, 'yellow')
assert.deepEqual(missingBridgeEvidence.recommendations[0].blockers, ['network_bridge_evidence_missing'])

const calls = []
const fakeClient = {
  async clusterSummary() {
    calls.push('clusterSummary')
    return { cluster_id: 'gjallar-mvp' }
  },
  async listNodes() {
    calls.push('listNodes')
    return baseNodes
  },
  async listVms() {
    calls.push('listVms')
    return baseVms
  },
  async listStorage() {
    calls.push('listStorage')
    return baseStorage
  },
  async listNetworks() {
    calls.push('listNetworks')
    return baseNetworks
  },
  async listRisks() {
    calls.push('listRisks')
    return []
  },
  async listJobs() {
    calls.push('listJobs')
    return []
  },
}
const loaded = await loadPlacementModel(fakeClient)
assert.equal(loaded.status, 'Balanced')
assert.deepEqual(calls.sort(), ['clusterSummary', 'listJobs', 'listNetworks', 'listNodes', 'listRisks', 'listStorage', 'listVms'].sort())

const appSource = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8')
assert.match(appSource, /Placement/)
assert.match(appSource, /path="\/placement"/)

const utilitySource = readFileSync(new URL('../src/utils/placement.js', import.meta.url), 'utf8')
assert.doesNotMatch(utilitySource, /DRS/i)

console.log('placement RED contract exercised')
