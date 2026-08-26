// Read-only inventory can remain available when optional sources are partial.
// Mutations still require a complete authoritative live observation.
const LIVE_SOURCE = 'live_read_only'

export function normalizeProxmoxConnection(value = {}) {
  const state = String(value?.state || '').trim().toLowerCase()
  const source = String(value?.source || '').trim().toLowerCase()
  const inventoryAvailable = value?.inventory_available === true
  const authoritativeInventory = ['live', 'degraded'].includes(state)
    && source === LIVE_SOURCE
    && inventoryAvailable
  const authoritativeLive = state === 'live' && authoritativeInventory

  return {
    state: authoritativeLive ? 'live' : state === 'unconfigured' ? 'unconfigured' : 'degraded',
    source: source || 'unavailable',
    clusterId: String(value?.cluster_id || 'gjallar-mvp'),
    observedAt: value?.observed_at || null,
    freshness: String(value?.freshness || 'unknown'),
    reason: String(value?.reason || (authoritativeLive ? '' : 'proxmox_connection_status_unavailable')),
    configured: authoritativeLive || value?.configured === true,
    inventoryAvailable: authoritativeInventory,
    missingConfiguration: Array.isArray(value?.missing_configuration)
      ? value.missing_configuration.map(String).filter(Boolean)
      : [],
  }
}

export function isProxmoxOperational(value) {
  return normalizeProxmoxConnection(value).state === 'live'
}

export function isProxmoxInventoryAvailable(value) {
  return normalizeProxmoxConnection(value).inventoryAvailable
}

export function proxmoxConnectionBadge(requestStatus, value) {
  if (requestStatus === 'loading' || requestStatus === 'idle') {
    return { label: 'CHECKING', tone: 'slate' }
  }
  const connection = normalizeProxmoxConnection(value)
  if (connection.state === 'live') return { label: 'LIVE', tone: 'green' }
  if (connection.state === 'unconfigured') return { label: 'UNCONFIGURED', tone: 'yellow' }
  if (connection.inventoryAvailable) return { label: 'PARTIAL', tone: 'yellow' }
  return { label: 'DEGRADED', tone: 'red' }
}
