export const INSIGHT_CATEGORIES = Object.freeze(['risk', 'readiness', 'capacity', 'placement'])

export const INSIGHT_CATEGORY_LABELS = Object.freeze({
  risk: 'Risks',
  readiness: 'Readiness',
  capacity: 'Capacity',
  placement: 'Placement',
})

function asObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function asText(value, fallback = '') {
  const text = String(value ?? '').trim()
  return text || fallback
}

function normalizeFinding(value, category) {
  const finding = asObject(value)
  const target = asObject(finding.target)
  return Object.freeze({
    id: asText(finding.finding_id, `${category}-unknown`),
    category,
    severity: asText(finding.severity, 'unknown').toLowerCase(),
    status: asText(finding.status, 'unknown').toLowerCase(),
    code: asText(finding.code, 'unclassified'),
    title: asText(finding.title, 'Untitled finding'),
    message: asText(finding.message, 'No explanatory message was provided.'),
    targetType: asText(target.type, 'unknown'),
    targetId: asText(target.id, 'unknown'),
    source: asText(finding.source, 'unknown'),
    observedAt: asText(finding.observed_at),
    freshness: asText(finding.freshness, 'unknown'),
    ruleVersion: asText(finding.rule_version, 'unknown'),
    evidence: asObject(finding.evidence),
    readOnly: finding.read_only !== false,
    allowedActions: Array.isArray(finding.allowed_actions) ? finding.allowed_actions : [],
  })
}

function normalizeSection(value, category) {
  const section = asObject(value)
  return Object.freeze({
    category,
    label: INSIGHT_CATEGORY_LABELS[category],
    status: asText(section.status, 'unavailable').toLowerCase(),
    available: section.available === true,
    source: asText(section.source, 'unavailable'),
    observedAt: asText(section.observed_at),
    freshness: asText(section.freshness, 'unavailable'),
    ruleVersion: asText(section.rule_version, 'unknown'),
    summary: asObject(section.summary),
    findings: (Array.isArray(section.findings) ? section.findings : []).map((item) => normalizeFinding(item, category)),
    unavailableReason: asText(section.unavailable_reason),
    readOnly: section.read_only !== false,
    allowedActions: Array.isArray(section.allowed_actions) ? section.allowed_actions : [],
  })
}

export function normalizeInsightsSnapshot(value) {
  const payload = asObject(value)
  const rawSections = asObject(payload.sections)
  const sections = Object.fromEntries(
    INSIGHT_CATEGORIES.map((category) => [category, normalizeSection(rawSections[category], category)]),
  )
  return Object.freeze({
    generatedAt: asText(payload.generated_at),
    status: asText(payload.status, 'unavailable').toLowerCase(),
    executionMode: asText(payload.execution_mode, 'observe_only'),
    readOnly: payload.read_only !== false,
    allowedActions: Array.isArray(payload.allowed_actions) ? payload.allowed_actions : [],
    connection: asObject(payload.connection),
    sections: Object.freeze(sections),
  })
}

export function insightStatusTone(status) {
  const normalized = asText(status).toLowerCase()
  if (normalized === 'attention' || normalized === 'critical') return 'red'
  if (normalized === 'partial' || normalized === 'warning' || normalized === 'unknown') return 'amber'
  if (normalized === 'ready' || normalized === 'info' || normalized === 'clear') return 'emerald'
  return 'slate'
}

export function insightToneClass(tone) {
  if (tone === 'red') return 'border-red-200 bg-red-50 text-red-800'
  if (tone === 'amber') return 'border-amber-200 bg-amber-50 text-amber-800'
  if (tone === 'emerald') return 'border-emerald-200 bg-emerald-50 text-emerald-800'
  return 'border-slate-200 bg-slate-50 text-slate-700'
}
