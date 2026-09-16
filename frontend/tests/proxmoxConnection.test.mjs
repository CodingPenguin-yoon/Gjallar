import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const {
  isProxmoxInventoryAvailable,
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
assert.equal(isProxmoxInventoryAvailable(live), true)
assert.deepEqual(proxmoxConnectionBadge('ready', live), { label: '연결됨', tone: 'green', observation: '관찰 완료', observationTone: 'green' })

const unconfigured = {
  state: 'unconfigured',
  source: 'unavailable',
  reason: 'proxmox_inventory_configuration_missing',
  missing_configuration: ['PROXMOX_API_URL', 'PROXMOX_API_TOKEN_ID'],
  inventory_available: false,
}
assert.equal(isProxmoxOperational(unconfigured), false)
assert.deepEqual(normalizeProxmoxConnection(unconfigured).missingConfiguration, ['PROXMOX_API_URL', 'PROXMOX_API_TOKEN_ID'])
assert.deepEqual(proxmoxConnectionBadge('ready', unconfigured), { label: '설정 필요', tone: 'yellow' })

const partial = {
  state: 'degraded',
  source: 'live_read_only',
  freshness: 'partial',
  reason: 'proxmox_inventory_partial',
  configured: true,
  inventory_available: true,
}
assert.equal(isProxmoxInventoryAvailable(partial), true, 'Partial authoritative inventory must remain readable')
assert.equal(isProxmoxOperational(partial), false, 'Partial inventory must not enable mutation')
assert.deepEqual(proxmoxConnectionBadge('ready', partial), { label: '연결됨', tone: 'green', observation: '관찰 일부 누락', observationTone: 'yellow' })

const fixture = {
  state: 'test_fixture',
  source: 'fake_read_only',
  inventory_available: true,
}
assert.equal(isProxmoxOperational(fixture), false, 'Fixture inventory must never open product operation screens')
assert.equal(isProxmoxInventoryAvailable(fixture), false, 'Fixture inventory must never open product read screens')
assert.deepEqual(proxmoxConnectionBadge('ready', fixture), { label: '연결 확인 필요', tone: 'red' })

const boundary = readFileSync(new URL('../src/shared/proxmox/ProxmoxConnectionBoundary.jsx', import.meta.url), 'utf8')
assert.match(boundary, /isProxmoxInventoryAvailable/)
assert.match(boundary, /partial inventory는 유지하지만 Create와 mutation에는 complete live observation이 필요합니다/)
assert.doesNotMatch(boundary, /DRS 폐기 안내/)
assert.doesNotMatch(boundary, /demo data|mock data|샘플 데이터/)

console.log('proxmox connection truth contract exercised')

assert.deepEqual(proxmoxConnectionBadge('loading', live), {label: '확인 중', tone: 'slate'})
assert.equal(proxmoxConnectionBadge('ready', {...partial, inventory_available: false}).observation, undefined)

assert.deepEqual(proxmoxConnectionBadge('error', live), {label: '연결 확인 필요', tone: 'red'})
