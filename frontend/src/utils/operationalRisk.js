export const riskCategoryLabels = {
  node_status: 'Node status',
  storage_capacity: 'Storage capacity',
  guest_agent: 'Guest agent',
  guest_ssh_evidence: 'Guest SSH evidence',
  governance: 'Governance',
  compliance: 'Compliance',
  snapshot_age: 'Snapshot age',
  backup_coverage: 'Backup coverage',
  backup_recency: 'Backup recency',
  rpo_violation: 'RPO violation',
  restore_readiness: 'Restore readiness',
  pbs_datastore_capacity: 'PBS datastore capacity',
  pbs_datastore_health: 'PBS datastore health',
  restore_drill: 'Restore drill',
  long_stopped: 'Long stopped VM',
}

export const defaultRiskThresholds = {
  storageWarningPercent: 80,
  storageCriticalPercent: 90,
  snapshotWarningDays: 14,
  snapshotCriticalDays: 30,
  backupWarningDays: 7,
  stoppedWarningDays: 30,
  stoppedCriticalDays: 90,
}

const thresholdKeyMap = {
  storage_warning_percent: 'storageWarningPercent',
  storage_critical_percent: 'storageCriticalPercent',
  snapshot_warning_days: 'snapshotWarningDays',
  snapshot_critical_days: 'snapshotCriticalDays',
  backup_warning_days: 'backupWarningDays',
  stopped_warning_days: 'stoppedWarningDays',
  stopped_critical_days: 'stoppedCriticalDays',
}

const reverseThresholdKeyMap = Object.fromEntries(
  Object.entries(thresholdKeyMap).map(([snakeKey, camelKey]) => [camelKey, snakeKey]),
)

function toNumber(value, fallback) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

export function getRiskCategoryLabel(category) {
  return riskCategoryLabels[category] || category || 'Unknown'
}

export function normalizeRiskThresholds(rawThresholds = {}) {
  const source = rawThresholds.thresholds && typeof rawThresholds.thresholds === 'object'
    ? rawThresholds.thresholds
    : rawThresholds
  const normalized = { ...defaultRiskThresholds }
  Object.entries(thresholdKeyMap).forEach(([snakeKey, camelKey]) => {
    normalized[camelKey] = toNumber(source?.[snakeKey] ?? source?.[camelKey], normalized[camelKey])
  })
  return normalized
}

export function serializeRiskThresholds(draft = {}) {
  const normalized = normalizeRiskThresholds(draft)
  return Object.fromEntries(
    Object.entries(reverseThresholdKeyMap).map(([camelKey, snakeKey]) => [snakeKey, normalized[camelKey]]),
  )
}

export function validateRiskThresholdDraft(draft = {}) {
  const thresholds = normalizeRiskThresholds(draft)
  const positiveKeys = [
    'storageWarningPercent',
    'storageCriticalPercent',
    'snapshotWarningDays',
    'snapshotCriticalDays',
    'backupWarningDays',
    'stoppedWarningDays',
    'stoppedCriticalDays',
  ]
  if (positiveKeys.some((key) => !Number.isFinite(Number(thresholds[key])) || Number(thresholds[key]) <= 0)) {
    return { valid: false, message: 'All threshold values must be positive numbers.' }
  }
  if (thresholds.storageWarningPercent > 100 || thresholds.storageCriticalPercent > 100) {
    return { valid: false, message: 'Storage thresholds must be 100 percent or lower.' }
  }
  if ([thresholds.snapshotWarningDays, thresholds.snapshotCriticalDays, thresholds.backupWarningDays, thresholds.stoppedWarningDays, thresholds.stoppedCriticalDays].some((value) => Number(value) > 3650)) {
    return { valid: false, message: 'Day-based thresholds must be 3650 days or lower.' }
  }
  if (thresholds.storageWarningPercent > thresholds.storageCriticalPercent) {
    return { valid: false, message: 'Storage warning threshold must be lower than or equal to critical threshold.' }
  }
  if (thresholds.snapshotWarningDays > thresholds.snapshotCriticalDays) {
    return { valid: false, message: 'Snapshot warning threshold must be lower than or equal to critical threshold.' }
  }
  if (thresholds.stoppedWarningDays > thresholds.stoppedCriticalDays) {
    return { valid: false, message: 'Stopped VM warning threshold must be lower than or equal to critical threshold.' }
  }
  return { valid: true, message: '' }
}

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

export function normalizeRiskOverride(rawOverride = null) {
  if (!rawOverride || typeof rawOverride !== 'object') return null
  return {
    riskId: rawOverride.risk_id || rawOverride.riskId || '',
    status: rawOverride.status || null,
    reason: rawOverride.reason || '',
    updatedAt: rawOverride.updated_at ?? rawOverride.updatedAt ?? null,
    expiresAt: rawOverride.expires_at ?? rawOverride.expiresAt ?? null,
    updatedBy: rawOverride.updated_by || rawOverride.updatedBy || '',
  }
}

function normalizeRpoRtoProfile(source = {}) {
  const evidence = source.evidence && typeof source.evidence === 'object' ? source.evidence : source
  const profileId = evidence.rpo_rto_profile_id || evidence.rpoRtoProfileId || evidence.profileId || ''
  if (!profileId) return null
  return {
    profileId: String(profileId),
    source: evidence.rpo_rto_profile_source || evidence.rpoRtoProfileSource || evidence.source || 'default',
    rpoHours: toNumber(evidence.rpo_hours ?? evidence.rpoHours, null),
    restoreDrillMaxAgeDays: toNumber(
      evidence.restore_drill_max_age_days ?? evidence.restoreDrillMaxAgeDays,
      null,
    ),
  }
}

function formatProfileNumber(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return 'unknown'
  return Number.isInteger(number) ? String(number) : String(Number(number.toFixed(2)))
}

export function formatRiskPolicyProfile(item = {}) {
  const profile = item.rpoRtoProfile || normalizeRpoRtoProfile(item)
  if (!profile) return 'default RPO/RTO policy'
  return `${profile.profileId} · RPO ${formatProfileNumber(profile.rpoHours)}h · drill ${formatProfileNumber(profile.restoreDrillMaxAgeDays)}d`
}

function normalizeSuggestedAction(action = {}) {
  const requiresApproval = Boolean(action.requires_approval ?? action.requiresApproval ?? true)
  return {
    actionId: action.action_id || action.actionId || '',
    label: action.label || 'Review suggested action',
    description: action.description || '',
    link: action.link || action.href || '/risks',
    requiresApproval,
    executionMode: action.execution_mode || action.executionMode || 'proposal_only',
    mutationAllowed: Boolean(action.mutation_allowed ?? action.mutationAllowed ?? false),
    approvalLabel: requiresApproval ? 'Approval required' : 'Review only',
    target: action.target || {},
  }
}

function normalizeRiskItem(item = {}) {
  const normalized = { ...item }
  if (item.override) {
    normalized.override = normalizeRiskOverride(item.override)
  }
  const rpoRtoProfile = normalizeRpoRtoProfile(item)
  if (rpoRtoProfile) {
    normalized.rpoRtoProfile = rpoRtoProfile
  }
  const rawSuggestedActions = Array.isArray(item.suggested_actions)
    ? item.suggested_actions
    : (Array.isArray(item.suggestedActions) ? item.suggestedActions : [])
  normalized.suggestedActions = rawSuggestedActions.map(normalizeSuggestedAction)
  return normalized
}

export function normalizeRiskDashboard(payload = {}) {
  const rawRiskItems = Array.isArray(payload.risk_items) ? payload.risk_items : []
  const rawSuppressedRiskItems = Array.isArray(payload.suppressed_risk_items) ? payload.suppressed_risk_items : []
  const riskItems = rawRiskItems.map(normalizeRiskItem)
  const suppressedRiskItems = rawSuppressedRiskItems.map(normalizeRiskItem)
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
      acknowledged: Number(summary.acknowledged || 0),
      suppressed: Number(summary.suppressed ?? summary.suppressed_count ?? suppressedRiskItems.length ?? 0),
      categories: summary.categories || {},
    },
    riskItems,
    suppressedRiskItems,
    evidence: payload.evidence || {},
    thresholds: payload.thresholds || {},
    thresholdConfig: payload.threshold_config || null,
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
  if (item.scope === 'pbs_datastore') {
    return item.datastore || item.evidence?.datastore || 'pbs datastore'
  }
  return item.scope || 'unknown'
}

export function formatGeneratedAt(epochSeconds) {
  if (!epochSeconds) return 'unknown'
  const date = new Date(Number(epochSeconds) * 1000)
  if (Number.isNaN(date.getTime())) return 'unknown'
  return date.toLocaleString()
}
