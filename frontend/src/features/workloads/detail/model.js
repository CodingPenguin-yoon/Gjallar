import { INSIGHT_CATEGORIES, normalizeInsightsSnapshot } from '../../../entities/insight/model.js'
import { normalizeOperation } from '../../../entities/operation/model.js'
import { apiV1Client } from '../../../shared/api/apiV1.js'
import { normalizeVmid, vmidFromTarget, vmTargetId } from '../../../shared/navigation/targetPaths.js'
import { normalizeVm } from '../../../utils/apiV1ViewModels.js'

export const VM_OPERATION_QUERY_LIMIT = 100

const COMPLETE_INSIGHT_STATUSES = new Set(['ready', 'attention'])
const CURRENT_INSIGHT_FRESHNESS = new Set(['fresh', 'recorded', 'fixture'])
const CURRENT_INVENTORY_FRESHNESS = new Set(['fresh', 'fixture'])

function asObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function asText(value, fallback = '') {
  const text = String(value ?? '').trim()
  return text || fallback
}

function pickList(payload, key) {
  if (Array.isArray(payload)) return payload
  if (payload && Array.isArray(payload[key])) return payload[key]
  if (payload && Array.isArray(payload.items)) return payload.items
  return []
}

function findingPriority(finding) {
  if (finding.severity === 'critical') return 0
  if (finding.severity === 'warning') return 1
  if (finding.severity === 'unknown') return 2
  return 3
}

function operationTime(operation) {
  const parsed = Date.parse(operation.updatedAt || operation.createdAt || '')
  return Number.isNaN(parsed) ? 0 : parsed
}

function insightContext(snapshot, available, loading) {
  if (loading) {
    return {
      status: 'loading',
      unavailableCategories: [],
      uncertainCategories: [],
      truncatedCategories: [],
    }
  }
  if (!available || !snapshot) {
    return {
      status: 'unavailable',
      unavailableCategories: [...INSIGHT_CATEGORIES],
      uncertainCategories: [],
      truncatedCategories: [],
    }
  }
  const unavailableCategories = INSIGHT_CATEGORIES.filter((category) => !snapshot.sections[category].available)
  const uncertainCategories = INSIGHT_CATEGORIES.filter((category) => {
    const section = snapshot.sections[category]
    return section.available
      && (!COMPLETE_INSIGHT_STATUSES.has(section.status) || !CURRENT_INSIGHT_FRESHNESS.has(section.freshness))
  })
  const truncatedCategories = INSIGHT_CATEGORIES.filter(
    (category) => snapshot.sections[category].summary.truncated === true,
  )
  if (unavailableCategories.length === 0 && uncertainCategories.length === 0) {
    return { status: 'available', unavailableCategories, uncertainCategories, truncatedCategories }
  }
  if (unavailableCategories.length === INSIGHT_CATEGORIES.length) {
    return { status: 'unavailable', unavailableCategories, uncertainCategories, truncatedCategories }
  }
  return {
    status: 'partial',
    unavailableCategories,
    uncertainCategories,
    truncatedCategories,
  }
}

function inventorySourceContext(sources, sourceName, targetKey, applicable = true) {
  const source = asObject(sources[sourceName])
  const failedTargets = Array.isArray(source.failed_targets) ? source.failed_targets.map(String) : []
  let status = 'unknown'
  if (!applicable) {
    status = 'not_applicable'
  } else if (failedTargets.includes(targetKey) || source.available === false) {
    status = 'unavailable'
  } else if (Object.keys(source).length > 0) {
    status = 'available'
  }
  return {
    status,
    available: status === 'available',
    complete: source.complete === true,
    expectedTargets: Number(source.expected_targets) || 0,
    observedTargets: Number(source.observed_targets) || 0,
    failedTargets,
  }
}

function inventoryContext(meta, vm) {
  const payload = asObject(meta)
  const connection = asObject(payload.connection)
  const availability = asObject(payload.availability)
  const sources = asObject(availability.sources)
  const targetKey = `${vm.nodeId}:${vm.vmid}`
  const vmConfig = inventorySourceContext(sources, 'vm_config', targetKey)
  const guestAgent = inventorySourceContext(
    sources,
    'guest_agent',
    targetKey,
    vm.status === 'running',
  )
  const vmDetail = inventorySourceContext(sources, 'vm_detail', targetKey)
  const freshness = asText(payload.freshness ?? connection.freshness, 'unknown')
  const hasAvailability = Object.keys(availability).length > 0
  const targetSources = [vmConfig, vmDetail, ...(vm.status === 'running' ? [guestAgent] : [])]
  const targetIncomplete = targetSources.some((source) => source.status !== 'available')
  let status = 'unknown'
  if (availability.available === false) {
    status = 'unavailable'
  } else if (hasAvailability) {
    status = CURRENT_INVENTORY_FRESHNESS.has(freshness)
      && !targetIncomplete
      ? 'available'
      : 'partial'
  }
  return {
    status,
    source: asText(payload.source ?? connection.source, 'unknown'),
    observedAt: asText(payload.observed_at ?? connection.observed_at),
    freshness,
    available: availability.available === true,
    complete: availability.complete === true,
    targetKey,
    sources: { vmConfig, guestAgent, vmDetail },
  }
}

function relatedFindings(snapshot, vmid) {
  if (!snapshot) return []
  return INSIGHT_CATEGORIES
    .flatMap((category) => snapshot.sections[category].findings)
    .filter((finding) => finding.status !== 'clear' && vmidFromTarget(finding.targetType, finding.targetId) === vmid)
    .sort((left, right) => findingPriority(left) - findingPriority(right))
}

function relatedOperations(payload, targetId) {
  return pickList(payload, 'operations')
    .map(normalizeOperation)
    .filter((operation) => operation.targetType === 'proxmox_vm' && operation.targetId === targetId)
    .sort((left, right) => operationTime(right) - operationTime(left))
}

export function buildVmDetailModel({
  requestedVmid,
  vm,
  vmMeta = {},
  insights = null,
  operations = [],
  insightsAvailable = true,
  operationsAvailable = true,
  contextLoading = false,
} = {}) {
  const exactVmid = normalizeVmid(requestedVmid)
  if (!exactVmid) throw new Error('VMID는 0보다 큰 정수여야 합니다.')

  const normalizedVm = normalizeVm(vm)
  if (normalizeVmid(normalizedVm.vmid) !== exactVmid) {
    throw new Error(`요청한 VMID ${exactVmid}와 inventory 응답의 VMID가 일치하지 않습니다.`)
  }

  const targetId = vmTargetId(exactVmid)
  const insightsSnapshot = insightsAvailable && insights ? normalizeInsightsSnapshot(insights) : null
  const insightsState = insightContext(insightsSnapshot, insightsAvailable, contextLoading)
  const observation = inventoryContext(vmMeta, normalizedVm)

  return {
    vm: {
      ...normalizedVm,
      targetType: 'proxmox_vm',
      targetId,
    },
    findings: relatedFindings(insightsSnapshot, exactVmid),
    operations: contextLoading || !operationsAvailable ? [] : relatedOperations(operations, targetId),
    observation,
    context: {
      insightsStatus: insightsState.status,
      unavailableInsightCategories: insightsState.unavailableCategories,
      uncertainInsightCategories: insightsState.uncertainCategories,
      insightsTruncated: insightsState.truncatedCategories.length > 0,
      truncatedInsightCategories: insightsState.truncatedCategories,
      findingCoverageComplete: insightsState.status === 'available'
        && insightsState.truncatedCategories.length === 0,
      operationsStatus: contextLoading ? 'loading' : operationsAvailable ? 'available' : 'unavailable',
      operationQueryLimit: VM_OPERATION_QUERY_LIMIT,
    },
  }
}

export async function loadVmDetailModel(
  client = apiV1Client,
  requestedVmid,
  { onVmLoaded } = {},
) {
  const exactVmid = normalizeVmid(requestedVmid)
  if (!exactVmid) throw new Error('VMID는 0보다 큰 정수여야 합니다.')

  const vmResponse = await client.getVmWithMeta(Number(exactVmid))
  const vm = vmResponse.data
  const vmMeta = vmResponse.meta
  const initialModel = buildVmDetailModel({
    requestedVmid: exactVmid,
    vm,
    vmMeta,
    insightsAvailable: false,
    operationsAvailable: false,
    contextLoading: true,
  })
  if (typeof onVmLoaded === 'function') onVmLoaded(initialModel)

  const [insightsResult, operationsResult] = await Promise.allSettled([
    client.getInsights(),
    client.listOperations({
      target_type: 'proxmox_vm',
      target_id: initialModel.vm.targetId,
      limit: VM_OPERATION_QUERY_LIMIT,
    }),
  ])

  return buildVmDetailModel({
    requestedVmid: exactVmid,
    vm,
    vmMeta,
    insights: insightsResult.status === 'fulfilled' ? insightsResult.value : null,
    operations: operationsResult.status === 'fulfilled' ? operationsResult.value : [],
    insightsAvailable: insightsResult.status === 'fulfilled',
    operationsAvailable: operationsResult.status === 'fulfilled',
  })
}
