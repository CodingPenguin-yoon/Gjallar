import { apiV1Client } from '../../../shared/api/apiV1.js'
import { normalizeInsightsSnapshot } from '../../../entities/insight/model.js'
import { normalizeOperation } from '../../../entities/operation/model.js'
import { buildInfraExplorerModel } from '../../../utils/apiV1ViewModels.js'

const OPERATION_CONTEXT_LIMIT = 200
const OPTIONAL_CONTEXT_TIMEOUT_MS = 10_000
const DIRECT_INSIGHT_CATEGORIES = Object.freeze(['readiness', 'placement'])
const COMPLETE_INSIGHT_STATUSES = new Set(['ready', 'attention'])
const CURRENT_INSIGHT_FRESHNESS = new Set(['fresh', 'recorded', 'fixture'])

function pickList(payload, key) {
  if (Array.isArray(payload)) return payload
  if (payload && Array.isArray(payload[key])) return payload[key]
  if (payload && Array.isArray(payload.items)) return payload.items
  return []
}

function asObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function asText(value, fallback = '') {
  const text = String(value ?? '').trim()
  return text || fallback
}

function inventoryObservation(meta, scope) {
  const payload = asObject(meta)
  const connection = asObject(payload.connection)
  return {
    scope,
    source: asText(payload.source ?? connection.source, 'unavailable'),
    observedAt: asText(payload.observed_at ?? connection.observed_at),
    freshness: asText(payload.freshness ?? connection.freshness, 'unavailable'),
  }
}

function workloadTargetId(vmid) {
  const parsed = Number(vmid)
  return Number.isInteger(parsed) && parsed > 0 ? `vmid:${parsed}` : ''
}

function insightFindings(snapshot) {
  if (!snapshot) return []
  return DIRECT_INSIGHT_CATEGORIES
    .flatMap((category) => snapshot.sections[category].findings)
    .filter((finding) => finding.status !== 'clear' && finding.targetType === 'proxmox_vm' && finding.targetId.startsWith('vmid:'))
}

function insightContext(snapshot, requestAvailable, contextLoading) {
  if (contextLoading) {
    return { status: 'loading', unavailableCategories: [], uncertainCategories: [], truncatedCategories: [] }
  }
  if (!requestAvailable || !snapshot) {
    return {
      status: 'unavailable',
      unavailableCategories: [...DIRECT_INSIGHT_CATEGORIES],
      uncertainCategories: [],
      truncatedCategories: [],
    }
  }
  const unavailableCategories = DIRECT_INSIGHT_CATEGORIES.filter((category) => !snapshot.sections[category].available)
  const uncertainCategories = DIRECT_INSIGHT_CATEGORIES.filter((category) => {
    const section = snapshot.sections[category]
    return section.available
      && (!COMPLETE_INSIGHT_STATUSES.has(section.status) || !CURRENT_INSIGHT_FRESHNESS.has(section.freshness))
  })
  const truncatedCategories = DIRECT_INSIGHT_CATEGORIES.filter(
    (category) => snapshot.sections[category].summary.truncated === true,
  )
  if (unavailableCategories.length === 0 && uncertainCategories.length === 0) {
    return { status: 'available', unavailableCategories, uncertainCategories, truncatedCategories }
  }
  if (unavailableCategories.length === DIRECT_INSIGHT_CATEGORIES.length) {
    return { status: 'unavailable', unavailableCategories, uncertainCategories, truncatedCategories }
  }
  return { status: 'partial', unavailableCategories, uncertainCategories, truncatedCategories }
}

function normalizedOperations(payload) {
  return pickList(payload, 'operations')
    .map(normalizeOperation)
    .filter((operation) => operation.targetType === 'proxmox_vm' && operation.targetId.startsWith('vmid:'))
}

function findingPriority(finding) {
  if (finding.severity === 'critical') return 0
  if (finding.severity === 'warning') return 1
  if (finding.severity === 'unknown') return 2
  return 3
}

function operationTime(operation) {
  const value = Date.parse(operation.updatedAt || operation.createdAt || '')
  return Number.isNaN(value) ? 0 : value
}

export function buildWorkloadCockpitModel({
  nodes = [],
  vms = [],
  nodesMeta = {},
  vmsMeta = {},
  insights = null,
  operations = [],
  insightsAvailable = true,
  operationsAvailable = true,
  contextLoading = false,
} = {}) {
  const inventory = buildInfraExplorerModel({ nodes, vms })
  const insightsSnapshot = insightsAvailable && insights ? normalizeInsightsSnapshot(insights) : null
  const insightsContext = insightContext(insightsSnapshot, insightsAvailable, contextLoading)
  const findingsByTarget = new Map()
  insightFindings(insightsSnapshot).forEach((finding) => {
    const items = findingsByTarget.get(finding.targetId) || []
    items.push(finding)
    findingsByTarget.set(finding.targetId, items)
  })
  findingsByTarget.forEach((items) => items.sort((left, right) => findingPriority(left) - findingPriority(right)))

  const operationsByTarget = new Map()
  normalizedOperations(operations)
    .sort((left, right) => operationTime(right) - operationTime(left))
    .forEach((operation) => {
      if (!operationsByTarget.has(operation.targetId)) operationsByTarget.set(operation.targetId, operation)
    })

  let relatedFindingCount = 0
  let workloadsWithFindings = 0
  let workloadsWithRecentOperations = 0
  const decoratedNodes = inventory.nodes.map((node) => ({
    ...node,
    vms: node.vms.map((vm) => {
      const targetId = workloadTargetId(vm.vmid)
      const relatedFindings = targetId ? findingsByTarget.get(targetId) || [] : []
      const recentOperation = targetId ? operationsByTarget.get(targetId) || null : null
      relatedFindingCount += relatedFindings.length
      if (relatedFindings.length > 0) workloadsWithFindings += 1
      if (recentOperation) workloadsWithRecentOperations += 1
      return { ...vm, targetId, relatedFindings, recentOperation }
    }),
  }))

  return {
    ...inventory,
    nodes: decoratedNodes,
    observations: [
      inventoryObservation(nodesMeta, 'Nodes'),
      inventoryObservation(vmsMeta, 'VMs'),
    ],
    context: {
      insightsAvailable: insightsContext.status === 'available',
      insightsStatus: insightsContext.status,
      unavailableInsightCategories: insightsContext.unavailableCategories,
      uncertainInsightCategories: insightsContext.uncertainCategories,
      insightsTruncated: insightsContext.truncatedCategories.length > 0,
      truncatedInsightCategories: insightsContext.truncatedCategories,
      operationsAvailable: !contextLoading && operationsAvailable,
      operationsStatus: contextLoading ? 'loading' : operationsAvailable ? 'available' : 'unavailable',
      operationWindow: OPERATION_CONTEXT_LIMIT,
    },
    summary: {
      ...inventory.summary,
      relatedFindingCount,
      workloadsWithFindings,
      workloadsWithRecentOperations,
    },
  }
}

export async function operationResultDestination(client, operationId) {
  const encodedId = encodeURIComponent(operationId)
  try {
    await client.getOperation(operationId)
    return { path: `/operations/${encodedId}`, compatibilityFallback: false }
  } catch (error) {
    if (Number(error?.status) === 404) {
      return { path: `/operations/jobs?job=${encodedId}&compatibility=operation`, compatibilityFallback: true }
    }
    return { path: null, compatibilityFallback: false, lookupError: error }
  }
}

export function operationIdFromActionError(error) {
  const details = error?.details && typeof error.details === 'object' ? error.details : {}
  const nested = details.details && typeof details.details === 'object' ? details.details : {}
  return String(details.operation_id || details.job_id || nested.operation_id || nested.job_id || '').trim()
}

function loadOptionalContext(load, timeoutMs) {
  return new Promise((resolve, reject) => {
    let completed = false
    const timer = setTimeout(() => {
      completed = true
      reject(new Error(`Optional workload context timed out after ${timeoutMs} ms`))
    }, timeoutMs)

    Promise.resolve()
      .then(load)
      .then(
        (value) => {
          if (completed) return
          completed = true
          clearTimeout(timer)
          resolve(value)
        },
        (error) => {
          if (completed) return
          completed = true
          clearTimeout(timer)
          reject(error)
        },
      )
  })
}

export async function loadInfraExplorerModel(
  client = apiV1Client,
  { onInventoryLoaded, contextTimeoutMs = OPTIONAL_CONTEXT_TIMEOUT_MS } = {},
) {
  const boundedContextTimeoutMs = Number.isFinite(Number(contextTimeoutMs)) && Number(contextTimeoutMs) > 0
    ? Number(contextTimeoutMs)
    : OPTIONAL_CONTEXT_TIMEOUT_MS
  const contextPromise = Promise.allSettled([
    loadOptionalContext(() => client.getInsights(), boundedContextTimeoutMs),
    loadOptionalContext(() => client.listOperations({ limit: OPERATION_CONTEXT_LIMIT }), boundedContextTimeoutMs),
  ])
  const [nodesResponse, vmsResponse] = await Promise.all([
    client.listNodesWithMeta(),
    client.listVmsWithMeta(),
  ])

  const inventoryInput = {
    nodes: pickList(nodesResponse.data, 'nodes'),
    vms: pickList(vmsResponse.data, 'vms'),
    nodesMeta: nodesResponse.meta,
    vmsMeta: vmsResponse.meta,
  }
  if (typeof onInventoryLoaded === 'function') {
    onInventoryLoaded(buildWorkloadCockpitModel({
      ...inventoryInput,
      insightsAvailable: false,
      operationsAvailable: false,
      contextLoading: true,
    }))
  }

  const [insightsResult, operationsResult] = await contextPromise

  return buildWorkloadCockpitModel({
    ...inventoryInput,
    insights: insightsResult.status === 'fulfilled' ? insightsResult.value : null,
    operations: operationsResult.status === 'fulfilled' ? operationsResult.value : [],
    insightsAvailable: insightsResult.status === 'fulfilled',
    operationsAvailable: operationsResult.status === 'fulfilled',
  })
}
