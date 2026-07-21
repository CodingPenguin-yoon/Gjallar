// Only authoritative live inventory can enable Proxmox-backed screens.
const LIVE_SOURCE = 'live_read_only'

export function normalizeProxmoxConnection(value = {}) {
  const state = String(value?.state || '').trim().toLowerCase()
  const source = String(value?.source || '').trim().toLowerCase()
  const inventoryAvailable = value?.inventory_available === true
  const authoritativeLive = state === 'live' && source === LIVE_SOURCE && inventoryAvailable

  return {
    state: authoritativeLive ? 'live' : state === 'unconfigured' ? 'unconfigured' : 'degraded',
    source: source || 'unavailable',
    clusterId: String(value?.cluster_id || 'gjallar-mvp'),
    observedAt: value?.observed_at || null,
    freshness: String(value?.freshness || 'unknown'),
    reason: String(value?.reason || (authoritativeLive ? '' : 'proxmox_connection_status_unavailable')),
    configured: authoritativeLive || value?.configured === true,
    inventoryAvailable: authoritativeLive,
    missingConfiguration: Array.isArray(value?.missing_configuration)
      ? value.missing_configuration.map(String).filter(Boolean)
      : [],
  }
}

export function isProxmoxOperational(value) {
  return normalizeProxmoxConnection(value).state === 'live'
}

export function proxmoxConnectionBadge(requestStatus, value) {
  if (requestStatus === 'loading' || requestStatus === 'idle') {
    return { label: 'CHECKING', tone: 'slate' }
  }
  const connection = normalizeProxmoxConnection(value)
  if (connection.state === 'live') return { label: 'LIVE', tone: 'green' }
  if (connection.state === 'unconfigured') return { label: 'UNCONFIGURED', tone: 'yellow' }
  return { label: 'DEGRADED', tone: 'red' }
}
