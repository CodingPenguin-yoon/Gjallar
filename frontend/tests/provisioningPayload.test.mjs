import assert from 'node:assert/strict'
import {
  DEFAULT_DISK_SIZE_GB,
  buildProvisioningPayload,
  buildProvisioningResourcePreflightPayload,
} from '../src/utils/provisioningPayload.js'

const wizardConfig = {
  selectedServerId: 'pve1',
  selectedTemplateId: 'pve1/9000',
  selectedStorageId: 'local-lvm',
  selectedNetworkIds: ['vmbr0'],
  serverName: 'new-vm',
  vmid: 202,
  vmIp: '192.168.2.50/24',
  vmGateway: '192.168.2.1',
}

const preflightPayload = buildProvisioningResourcePreflightPayload(wizardConfig)
assert.equal(preflightPayload.disk_size_gb, DEFAULT_DISK_SIZE_GB)
assert.equal(preflightPayload.vmid, 202)
assert.equal(preflightPayload.server_name, 'new-vm')
assert.equal(preflightPayload.vm_ip, '192.168.2.50/24')
assert.equal(preflightPayload.vm_gateway, '192.168.2.1')

const provisionPayload = buildProvisioningPayload(wizardConfig)
assert.equal(provisionPayload.disk_size_gb, DEFAULT_DISK_SIZE_GB)
assert.equal(Object.prototype.hasOwnProperty.call(provisionPayload, 'vmid'), false)
assert.deepEqual(provisionPayload.network_ids, ['vmbr0'])

const explicitDiskPayload = buildProvisioningResourcePreflightPayload({
  ...wizardConfig,
  diskSize: '80',
})
assert.equal(explicitDiskPayload.disk_size_gb, 80)

const apiStylePreflightPayload = buildProvisioningResourcePreflightPayload({
  server_id: 'pve1',
  template_id: 'pve1/9000',
  storage_id: 'local-lvm',
  network_ids: ['vmbr0'],
  server_name: 'api-vm',
})
assert.equal(apiStylePreflightPayload.disk_size_gb, DEFAULT_DISK_SIZE_GB)

console.log('provisioningPayload tests passed')
