import assert from 'node:assert/strict'
import { buildProvisioningSummary } from '../src/utils/provisioningSummary.js'

const summary = buildProvisioningSummary({
  selectedServerId: 'pve-01',
  selectedTemplateId: 'pve-01/9000',
  selectedStorageId: 'local-lvm',
  selectedNetworkIds: ['vmbr0'],
  serverName: 'web-01',
  cpuCores: '4',
  memory: '8',
  ipMode: 'static',
  vmIp: '192.168.2.120/24',
  vmGateway: '192.168.2.1',
  selectedPackages: ['nginx'],
  selectedRoles: ['web'],
})

assert.equal(summary.title, 'web-01')
assert.equal(summary.target.node, 'pve-01')
assert.equal(summary.network.mode, 'static')
assert.equal(summary.bootstrap.enabled, true)
assert.equal(summary.ready, true)
assert.deepEqual(summary.missingRequiredFields, [])

const missing = buildProvisioningSummary({ selectedServerId: 'pve-01' })
assert.equal(missing.ready, false)
assert.ok(missing.missingRequiredFields.includes('template'))
assert.ok(missing.missingRequiredFields.includes('storage'))
assert.ok(missing.missingRequiredFields.includes('network'))

console.log('provisioningSummary tests passed')
