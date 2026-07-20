import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const {
  isProxmoxOperational,
  normalizeProxmoxConnection,
  proxmoxConnectionBadge,
} = await import('../src/utils/proxmoxConnection.js')

const live = {
  state: 'live',
  source: 'live_read_only',
  cluster_id: 'cluster-a',
  observed_at: '2026-07-20T10:00:00+09:00',
  freshness: 'fresh',
  inventory_available: true,
}
assert.equal(isProxmoxOperational(live), true)
assert.deepEqual(proxmoxConnectionBadge('ready', live), { label: 'LIVE', tone: 'green' })

const unconfigured = {
  state: 'unconfigured',
  source: 'unavailable',
  reason: 'proxmox_inventory_configuration_missing',
  missing_configuration: ['PROXMOX_API_URL', 'PROXMOX_API_TOKEN_ID'],
  inventory_available: false,
}
assert.equal(isProxmoxOperational(unconfigured), false)
assert.deepEqual(normalizeProxmoxConnection(unconfigured).missingConfiguration, ['PROXMOX_API_URL', 'PROXMOX_API_TOKEN_ID'])
assert.deepEqual(proxmoxConnectionBadge('ready', unconfigured), { label: 'UNCONFIGURED', tone: 'yellow' })

const fixture = {
  state: 'test_fixture',
  source: 'fake_read_only',
  inventory_available: true,
}
assert.equal(isProxmoxOperational(fixture), false, 'Fixture inventory must never open product operation screens')
assert.deepEqual(proxmoxConnectionBadge('ready', fixture), { label: 'DEGRADED', tone: 'red' })

const boundary = readFileSync(new URL('../src/components/ProxmoxConnectionBoundary.jsx', import.meta.url), 'utf8')
assert.match(boundary, /Jobs, Risks, Account, Admin은 계속 사용할 수 있습니다/)
assert.doesNotMatch(boundary, /demo data|mock data|샘플 데이터/)

console.log('proxmox connection truth contract exercised')
