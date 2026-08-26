const VM_TARGET_TYPES = new Set(['proxmox_vm', 'vm'])
const INSIGHT_CATEGORY_PATHS = Object.freeze({
  risk: '/insights/risks',
  readiness: '/insights/readiness',
  capacity: '/insights/capacity',
  placement: '/insights/placement',
})

export function normalizeVmid(value) {
  const text = String(value ?? '').trim()
  if (!/^\d+$/.test(text)) return null
  const parsed = Number(text)
  return Number.isSafeInteger(parsed) && parsed > 0 ? String(parsed) : null
}

export function vmTargetId(vmid) {
  const normalized = normalizeVmid(vmid)
  return normalized ? `vmid:${normalized}` : null
}

export function vmidFromTarget(targetType, targetId) {
  const normalizedType = String(targetType ?? '').trim().toLowerCase()
  if (!VM_TARGET_TYPES.has(normalizedType)) return null

  const normalizedTarget = String(targetId ?? '').trim()
  const canonicalMatch = /^vmid:(\d+)$/.exec(normalizedTarget)
  if (canonicalMatch) return normalizeVmid(canonicalMatch[1])
  return normalizedType === 'vm' ? normalizeVmid(normalizedTarget) : null
}

export function vmDetailPath(vmid) {
  const normalized = normalizeVmid(vmid)
  return normalized ? `/instances/${encodeURIComponent(normalized)}` : null
}

export function vmDetailPathFromTarget(targetType, targetId) {
  return vmDetailPath(vmidFromTarget(targetType, targetId))
}

export function insightCategoryPath(category) {
  return INSIGHT_CATEGORY_PATHS[String(category ?? '').trim().toLowerCase()] || '/insights'
}

export function insightFindingPath(finding = {}) {
  const path = insightCategoryPath(finding.category)
  const targetType = String(finding.targetType ?? '').trim()
  const targetId = String(finding.targetId ?? '').trim()
  if (!targetType || !targetId) return path

  const search = new URLSearchParams({ target_type: targetType, target_id: targetId })
  const findingId = String(finding.id ?? '').trim()
  if (findingId) search.set('finding', findingId)
  return `${path}?${search.toString()}`
}

export function operationsTargetPath(targetType, targetId) {
  const normalizedType = String(targetType ?? '').trim()
  const normalizedId = String(targetId ?? '').trim()
  if (!normalizedType || !normalizedId) return '/operations'
  const search = new URLSearchParams({ target_type: normalizedType, target_id: normalizedId })
  return `/operations?${search.toString()}`
}

export function workloadActionPath(vmid, action) {
  const normalizedVmid = normalizeVmid(vmid)
  const normalizedAction = String(action ?? '').trim().toLowerCase()
  if (!normalizedVmid || !['start', 'shutdown'].includes(normalizedAction)) return '/instances'
  const search = new URLSearchParams({ vmid: normalizedVmid, action: normalizedAction })
  return `/instances?${search.toString()}`
}
