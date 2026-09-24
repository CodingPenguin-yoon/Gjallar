// Connection availability and per-resource observation coverage are separate.
// Each server action validates its own required observations.
const LIVE_SOURCE = 'live_read_only'

export function normalizeProxmoxConnection(value = {}) {
  const state = String(value?.state || '').trim().toLowerCase()
  const source = String(value?.source || '').trim().toLowerCase()
  const inventoryAvailable = value?.inventory_available === true
  const authoritativeInventory = ['live', 'degraded'].includes(state)
    && source === LIVE_SOURCE
    && inventoryAvailable
  const authoritativeLive = authoritativeInventory

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
    return { label: '확인 중', tone: 'slate' }
  }
  if (requestStatus !== 'ready') return { label: '연결 확인 필요', tone: 'red' }
  const connection = normalizeProxmoxConnection(value)
  if (connection.state === 'live') return { label: '연결됨', tone: 'green', observation: '연결 확인', observationTone: 'green' }
  if (connection.state === 'unconfigured') return { label: '설정 필요', tone: 'yellow' }
  return { label: '연결 확인 필요', tone: 'red' }
}
