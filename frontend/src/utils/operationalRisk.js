const severityOrder = {
  critical: 0,
  warning: 1,
  info: 2,
  healthy: 3,
}

export function getRiskSeverityTone(severity) {
  const normalized = String(severity || 'info').toLowerCase()
  if (normalized === 'critical') {
    return {
      level: 'critical',
      label: 'Critical',
      cardClass: 'border-red-200 bg-red-50 text-red-800',
      badgeClass: 'bg-red-100 text-red-700 border-red-200',
      dotClass: 'bg-red-500',
    }
  }
  if (normalized === 'warning') {
    return {
      level: 'warning',
      label: 'Warning',
      cardClass: 'border-yellow-200 bg-yellow-50 text-yellow-800',
      badgeClass: 'bg-yellow-100 text-yellow-700 border-yellow-200',
      dotClass: 'bg-yellow-500',
    }
  }
  if (normalized === 'healthy') {
    return {
      level: 'healthy',
      label: 'Healthy',
      cardClass: 'border-green-200 bg-green-50 text-green-800',
      badgeClass: 'bg-green-100 text-green-700 border-green-200',
      dotClass: 'bg-green-500',
    }
  }
  return {
    level: 'info',
    label: 'Info',
    cardClass: 'border-blue-200 bg-blue-50 text-blue-800',
    badgeClass: 'bg-blue-100 text-blue-700 border-blue-200',
    dotClass: 'bg-blue-500',
  }
}

export function normalizeRiskDashboard(payload = {}) {
  const riskItems = Array.isArray(payload.risk_items) ? payload.risk_items : []
  const summary = payload.summary || {}
  return {
    status: payload.status || 'healthy',
    generatedAt: payload.generated_at || null,
    summary: {
      totalRisks: Number(summary.total_risks || riskItems.length || 0),
      critical: Number(summary.critical || 0),
      warning: Number(summary.warning || 0),
      info: Number(summary.info || 0),
      affectedNodes: Number(summary.affected_nodes || 0),
      affectedVms: Number(summary.affected_vms || 0),
      totalNodes: Number(summary.total_nodes || 0),
      totalVms: Number(summary.total_vms || 0),
      categories: summary.categories || {},
    },
    riskItems,
    thresholds: payload.thresholds || {},
  }
}

export function sortRiskItems(items = []) {
  return [...items].sort((left, right) => {
    const severityDiff = (severityOrder[left.severity] ?? 99) - (severityOrder[right.severity] ?? 99)
    if (severityDiff !== 0) return severityDiff
    const categoryDiff = String(left.category || '').localeCompare(String(right.category || ''))
    if (categoryDiff !== 0) return categoryDiff
    const nodeDiff = String(left.node || '').localeCompare(String(right.node || ''), undefined, { numeric: true, sensitivity: 'base' })
    if (nodeDiff !== 0) return nodeDiff
    return Number(left.vmid || 0) - Number(right.vmid || 0)
  })
}

export function groupRisksByCategory(items = []) {
  return items.reduce((groups, item) => {
    const category = item.category || 'unknown'
    groups[category] = groups[category] || []
    groups[category].push(item)
    return groups
  }, {})
}

export function formatRiskScope(item = {}) {
  if (item.scope === 'vm') {
    return `${item.node || 'unknown'}/${item.vmid || '?'} ${item.vm_name || ''}`.trim()
  }
  if (item.scope === 'storage') {
    return item.node || 'storage'
  }
  if (item.scope === 'node') {
    return item.node || 'node'
  }
  return item.scope || 'unknown'
}

export function formatGeneratedAt(epochSeconds) {
  if (!epochSeconds) return 'unknown'
  const date = new Date(Number(epochSeconds) * 1000)
  if (Number.isNaN(date.getTime())) return 'unknown'
  return date.toLocaleString()
}
