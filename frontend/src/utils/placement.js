import { apiV1Client } from '../services/apiV1.js'

const READ_ONLY_ACTIONS = Object.freeze([])
const RISK_LEVELS = new Set(['red', 'yellow', 'green'])
const RISK_RANK = Object.freeze({ green: 0, yellow: 1, unknown: 2, red: 3 })

function asArray(value) {
  return Array.isArray(value) ? value : []
}

function asText(value, fallback = '-') {
  const text = String(value ?? '').trim()
  return text || fallback
}

function asNumber(value, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function optionalNumber(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function normalizeStatus(value) {
  return String(value ?? '').trim().toLowerCase()
}

function normalizeRiskLevel(level) {
  const normalized = normalizeStatus(level)
  return RISK_LEVELS.has(normalized) ? normalized : 'unknown'
}

function pickList(payload, key) {
  if (Array.isArray(payload)) return payload
  if (payload && Array.isArray(payload.data)) return payload.data
  if (payload && Array.isArray(payload[key])) return payload[key]
  if (payload && Array.isArray(payload.items)) return payload.items
  return []
}

function pickObject(payload, key) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return {}
  if (payload.data && typeof payload.data === 'object' && !Array.isArray(payload.data)) return payload.data
  if (payload[key] && typeof payload[key] === 'object' && !Array.isArray(payload[key])) return payload[key]
  return payload
}

function nodeIdOf(source = {}) {
  return asText(source.node_id ?? source.nodeId ?? source.node ?? source.id ?? source.name, 'unknown')
}

function nodeNameOf(source = {}) {
  return asText(source.display_name ?? source.displayName ?? source.node_name ?? source.name ?? nodeIdOf(source), nodeIdOf(source))
}

function vmNodeIdOf(source = {}) {
  return asText(source.node_id ?? source.nodeId ?? source.node ?? source.server_id, 'unknown')
}

function vmIdOf(source = {}) {
  return asText(source.vmid ?? source.vm_id ?? source.id, 'unknown')
}

function vmNameOf(source = {}) {
  return asText(source.name ?? source.vm_name ?? source.server_name ?? `vm-${vmIdOf(source)}`, `vm-${vmIdOf(source)}`)
}

function normalizeGuestAgent(source = {}) {
  const guestAgent = source.guest_agent ?? source.guestAgent ?? {}
  return {
    available: Boolean(guestAgent.available),
    ipAddresses: asArray(guestAgent.ip_addresses ?? guestAgent.ipAddresses).filter(Boolean),
  }
}

function vmIpAddresses(source = {}) {
  return [
    ...asArray(source.ip_addresses ?? source.ipAddresses),
    ...asArray(source.guest_agent?.ip_addresses ?? source.guestAgent?.ipAddresses),
  ].filter(Boolean)
}

function vmMemoryGb(source = {}) {
  if (source.memory_gb !== undefined) return asNumber(source.memory_gb)
  if (source.memoryGb !== undefined) return asNumber(source.memoryGb)
  if (source.memory_mb !== undefined) return asNumber(source.memory_mb) / 1024
  if (source.memoryMb !== undefined) return asNumber(source.memoryMb) / 1024
  return asNumber(source.memory, 0)
}

function vmDiskGb(source = {}) {
  if (source.disk_gb !== undefined) return asNumber(source.disk_gb)
  if (source.diskGb !== undefined) return asNumber(source.diskGb)
  return asArray(source.disks).reduce((sum, disk) => sum + asNumber(disk?.size_gb ?? disk?.sizeGb ?? disk?.gb), 0)
}

function storageIdsForVm(source = {}) {
  const ids = [
    source.storage_id,
    source.storageId,
    ...asArray(source.disks).map((disk) => disk?.storage_id ?? disk?.storageId ?? disk?.storage),
  ]
  return uniqueText(ids).filter((id) => id !== 'unknown')
}

function uniqueText(values) {
  const seen = new Set()
  const result = []
  asArray(values).forEach((value) => {
    const text = String(value ?? '').trim()
    if (!text || seen.has(text)) return
    seen.add(text)
    result.push(text)
  })
  return result
}

function normalizeStorage(source = {}) {
  return {
    id: asText(source.storage_id ?? source.storageId ?? source.id, 'unknown'),
    nodeId: nodeIdOf(source),
    type: asText(source.type, 'unknown'),
    totalGb: asNumber(source.total_gb ?? source.totalGb),
    freeGb: asNumber(source.free_gb ?? source.freeGb),
    content: asArray(source.content).map(String),
    raw: source,
  }
}

function normalizeNetwork(source = {}) {
  return {
    bridgeId: asText(source.bridge_id ?? source.bridgeId ?? source.id, 'unknown'),
    nodeId: nodeIdOf(source),
    active: source.active === undefined ? true : Boolean(source.active),
    type: asText(source.type, 'bridge'),
    raw: source,
  }
}

function normalizeVm(source = {}) {
  const guestAgent = normalizeGuestAgent(source)
  const ipAddresses = uniqueText(vmIpAddresses(source))
  return {
    id: vmIdOf(source),
    vmid: source.vmid ?? source.vm_id ?? source.id ?? null,
    name: vmNameOf(source),
    nodeId: vmNodeIdOf(source),
    status: normalizeStatus(source.status) || 'unknown',
    template: Boolean(source.template),
    cpu: asNumber(source.cpu ?? source.cpus ?? source.cpu_cores ?? source.cpuCores),
    memoryGb: vmMemoryGb(source),
    diskGb: vmDiskGb(source),
    storageIds: storageIdsForVm(source),
    guestAgent,
    ipAddresses,
    readOnly: true,
    allowedActions: READ_ONLY_ACTIONS,
    raw: source,
  }
}

function directRiskFields(risk = {}) {
  const detail = risk.detail && typeof risk.detail === 'object' ? risk.detail : {}
  return [
    risk.vmid,
    risk.vm_id,
    risk.target_vmid,
    risk.target_id,
    risk.targetId,
    risk.resource_id,
    risk.resourceId,
    risk.vm_name,
    risk.target_name,
    detail.vmid,
    detail.vm_id,
    detail.target_vmid,
    detail.target_id,
    detail.vm_name,
    detail.node_id,
  ].map((value) => String(value ?? '').trim()).filter(Boolean)
}

function riskTargetsVm(risk, vm) {
  const fields = directRiskFields(risk)
  const vmTargets = [String(vm.id), String(vm.vmid ?? ''), vm.name].filter(Boolean)
  return fields.some((field) => vmTargets.includes(field))
}

function riskTargetsNode(risk, node) {
  const fields = directRiskFields(risk)
  return fields.includes(node.id) || fields.includes(node.name)
}

function risksForVm(risks, vm) {
  return asArray(risks).filter((risk) => riskTargetsVm(risk, vm))
}

function riskCounts(risks) {
  return asArray(risks).reduce((counts, risk) => {
    const level = normalizeRiskLevel(risk.level ?? risk.risk_level ?? risk.riskLevel)
    counts[level] = (counts[level] || 0) + 1
    return counts
  }, { red: 0, yellow: 0, green: 0, unknown: 0 })
}

function pressureOf(node) {
  return Math.max(node.cpuUsagePercent ?? 0, node.memoryUsagePercent ?? 0)
}

function classifyNode(node) {
  const pressure = pressureOf(node)
  if (node.riskCounts.red > 0 || pressure >= 85) return 'Imbalanced'
  if (node.riskCounts.yellow > 0 || pressure >= 70) return 'Watch'
  return 'Balanced'
}

function statusTone(status) {
  if (status === 'Imbalanced') return 'red'
  if (status === 'Watch') return 'yellow'
  if (status === 'Balanced') return 'green'
  return 'slate'
}

function maxDelta(values) {
  const numbers = values.filter((value) => Number.isFinite(value))
  if (numbers.length < 2) return 0
  return Math.max(...numbers) - Math.min(...numbers)
}

function compareByName(left, right) {
  return String(left.name).localeCompare(String(right.name), undefined, { numeric: true, sensitivity: 'base' })
}

function buildNodes({ nodes, vms, storages, networks, risks }) {
  return asArray(nodes).map((node) => {
    const id = nodeIdOf(node)
    const nodeStorages = asArray(node.storage).length
      ? asArray(node.storage).map(normalizeStorage)
      : storages.filter((storage) => storage.nodeId === id)
    const nodeNetworks = asArray(node.networks).length
      ? asArray(node.networks).map(normalizeNetwork)
      : networks.filter((network) => network.nodeId === id)
    const nodeVms = vms.filter((vm) => vm.nodeId === id)
    const vmRisks = nodeVms.flatMap((vm) => risksForVm(risks, vm))
    const targetedNodeRisks = asArray(risks).filter((risk) => riskTargetsNode(risk, { id, name: nodeNameOf(node) }))
    const allNodeRisks = [...targetedNodeRisks, ...vmRisks]
    const counts = riskCounts(allNodeRisks)
    const cpuUsagePercent = optionalNumber(node.cpu_usage_percent ?? node.cpuUsagePercent)
    const memoryUsagePercent = optionalNumber(node.memory_usage_percent ?? node.memoryUsagePercent)
    const row = {
      id,
      name: nodeNameOf(node),
      status: normalizeStatus(node.status) || 'unknown',
      online: normalizeStatus(node.status) === 'online',
      cpuUsagePercent,
      memoryUsagePercent,
      memoryTotalGb: asNumber(node.memory_total_mb ?? node.memoryTotalMb) / 1024,
      memoryUsedGb: asNumber(node.memory_used_mb ?? node.memoryUsedMb) / 1024,
      storageFreeGb: nodeStorages.reduce((sum, storage) => sum + Math.max(0, storage.freeGb), 0),
      storageTotalGb: nodeStorages.reduce((sum, storage) => sum + Math.max(0, storage.totalGb), 0),
      storage: nodeStorages,
      networks: nodeNetworks,
      bridgeIds: uniqueText(nodeNetworks.filter((network) => network.active).map((network) => network.bridgeId)).filter((bridge) => bridge !== 'unknown'),
      runningVmCount: nodeVms.filter((vm) => vm.status === 'running').length,
      stoppedVmCount: nodeVms.filter((vm) => vm.status === 'stopped').length,
      templateVmCount: nodeVms.filter((vm) => vm.template).length,
      totalVmCount: nodeVms.length,
      guestAgentVmCount: nodeVms.filter((vm) => vm.guestAgent.available).length,
      visibleIpVmCount: nodeVms.filter((vm) => vm.ipAddresses.length > 0).length,
      riskVmCount: nodeVms.filter((vm) => risksForVm(risks, vm).length > 0).length,
      riskCounts: counts,
      readOnly: true,
      allowedActions: READ_ONLY_ACTIONS,
      raw: node,
    }
    return {
      ...row,
      pressure: pressureOf(row),
      state: classifyNode(row),
    }
  }).sort(compareByName)
}

function clusterStatus({ nodes, risks }) {
  const onlineNodes = nodes.filter((node) => node.online)
  const cpuImbalance = maxDelta(onlineNodes.map((node) => node.cpuUsagePercent).filter((value) => value !== null))
  const memoryImbalance = maxDelta(onlineNodes.map((node) => node.memoryUsagePercent).filter((value) => value !== null))
  const counts = riskCounts(risks)
  if (counts.red > 0 || onlineNodes.some((node) => node.pressure >= 85) || cpuImbalance >= 50 || memoryImbalance >= 50) {
    return { status: 'Imbalanced', cpuImbalance, memoryImbalance }
  }
  if (onlineNodes.some((node) => node.pressure >= 70) || cpuImbalance >= 25 || memoryImbalance >= 25) {
    return { status: 'Watch', cpuImbalance, memoryImbalance }
  }
  return { status: 'Balanced', cpuImbalance, memoryImbalance }
}

function nodeByPressure(nodes, direction) {
  const candidates = nodes.filter((node) => node.online)
  if (!candidates.length) return null
  return [...candidates].sort((left, right) => {
    const delta = direction === 'asc' ? left.pressure - right.pressure : right.pressure - left.pressure
    return delta || compareByName(left, right)
  })[0]
}

function bridgeEvidence(sourceNode, targetNode) {
  const sourceBridges = new Set(sourceNode.bridgeIds)
  const targetBridges = new Set(targetNode.bridgeIds)
  if (!sourceBridges.size || !targetBridges.size) {
    return {
      verified: false,
      sharedBridgeIds: [],
      blocker: 'network_bridge_evidence_missing',
      message: 'Network bridge evidence is incomplete',
    }
  }
  const sharedBridgeIds = [...sourceBridges].filter((bridgeId) => targetBridges.has(bridgeId))
  if (!sharedBridgeIds.length) {
    return {
      verified: false,
      sharedBridgeIds: [],
      blocker: 'target_bridge_not_found',
      message: 'Target node does not expose a matching bridge',
    }
  }
  return { verified: true, sharedBridgeIds, blocker: null, message: 'Matching bridge evidence found' }
}

function storageEvidence(vm, targetNode) {
  const targetStorageIds = new Set(targetNode.storage.map((storage) => storage.id))
  const neededStorageIds = vm.storageIds
  const hasCapacity = targetNode.storage.some((storage) => storage.freeGb >= Math.max(1, vm.diskGb))
  if (!targetNode.storage.length) {
    return {
      verified: false,
      blocker: 'storage_evidence_missing',
      message: 'Target storage evidence is missing',
    }
  }
  if (neededStorageIds.length && neededStorageIds.some((storageId) => targetStorageIds.has(storageId)) && hasCapacity) {
    return {
      verified: true,
      blocker: null,
      message: 'Target node has matching storage evidence',
    }
  }
  if (!neededStorageIds.length && hasCapacity) {
    return {
      verified: false,
      blocker: 'storage_evidence_incomplete',
      message: 'VM storage identity is incomplete',
    }
  }
  return {
    verified: false,
    blocker: 'storage_constraint_unverified',
    message: 'Target storage compatibility needs review',
  }
}

function estimateVmPressure(vm, sourceNode) {
  const vmCountShare = sourceNode.runningVmCount > 0 ? sourceNode.pressure / sourceNode.runningVmCount : 5
  const memoryShare = sourceNode.memoryTotalGb > 0 ? (vm.memoryGb / sourceNode.memoryTotalGb) * 100 : 0
  return Math.max(4, Math.min(18, Math.max(vmCountShare, memoryShare)))
}

function recommendationRiskLevel(blockers) {
  if (blockers.length > 0) return 'yellow'
  return 'green'
}

function buildRecommendations({ nodes, vms, risks }) {
  const recommendations = []
  const sources = nodes
    .filter((node) => node.online && node.pressure >= 70)
    .sort((left, right) => right.pressure - left.pressure || compareByName(left, right))

  sources.forEach((sourceNode) => {
    const targetNode = nodes
      .filter((node) => node.online && node.id !== sourceNode.id)
      .sort((left, right) => left.pressure - right.pressure || compareByName(left, right))[0]
    if (!targetNode) return

    const imbalanceDelta = sourceNode.pressure - targetNode.pressure
    if (imbalanceDelta < 25) return

    vms
      .filter((vm) => vm.nodeId === sourceNode.id && vm.status === 'running' && !vm.template)
      .filter((vm) => !risksForVm(risks, vm).some((risk) => normalizeRiskLevel(risk.level ?? risk.risk_level ?? risk.riskLevel) === 'red'))
      .sort((left, right) => right.memoryGb - left.memoryGb || String(left.name).localeCompare(String(right.name), undefined, { numeric: true, sensitivity: 'base' }))
      .slice(0, 3)
      .forEach((vm) => {
        const network = bridgeEvidence(sourceNode, targetNode)
        const storage = storageEvidence(vm, targetNode)
        const blockers = [network.blocker, storage.blocker].filter(Boolean)
        const estimatedPressure = estimateVmPressure(vm, sourceNode)
        const riskLevel = recommendationRiskLevel(blockers)
        recommendations.push({
          id: `placement-rec-${vm.id}-${sourceNode.id}-${targetNode.id}`,
          vmid: vm.vmid,
          vmName: vm.name,
          sourceNodeId: sourceNode.id,
          sourceNodeName: sourceNode.name,
          targetNodeId: targetNode.id,
          targetNodeName: targetNode.name,
          reason: 'Source node is hotter and target node has capacity',
          estimatedEffect: {
            sourcePressureBefore: Math.round(sourceNode.pressure),
            targetPressureBefore: Math.round(targetNode.pressure),
            sourcePressureAfter: Math.max(0, Math.round(sourceNode.pressure - estimatedPressure)),
            targetPressureAfter: Math.min(100, Math.round(targetNode.pressure + estimatedPressure)),
            imbalanceDelta: Math.round(imbalanceDelta),
          },
          riskLevel,
          blockers,
          evidence: {
            sourceCpuUsagePercent: sourceNode.cpuUsagePercent,
            sourceMemoryUsagePercent: sourceNode.memoryUsagePercent,
            targetCpuUsagePercent: targetNode.cpuUsagePercent,
            targetMemoryUsagePercent: targetNode.memoryUsagePercent,
            networkBridgeVerified: network.verified,
            sharedBridgeIds: network.sharedBridgeIds,
            storageVerified: storage.verified,
            storageMessage: storage.message,
            networkMessage: network.message,
          },
          execution: {
            available: false,
            reason: 'Migration execution is deferred',
          },
          readOnly: true,
          allowedActions: READ_ONLY_ACTIONS,
        })
      })
  })

  return recommendations
    .sort((left, right) => {
      const riskDelta = (RISK_RANK[left.riskLevel] ?? RISK_RANK.unknown) - (RISK_RANK[right.riskLevel] ?? RISK_RANK.unknown)
      return riskDelta || right.estimatedEffect.imbalanceDelta - left.estimatedEffect.imbalanceDelta
    })
    .slice(0, 6)
}

function buildHistory(jobs) {
  return asArray(jobs)
    .filter((job) => String(job.job_type ?? job.type ?? '').toLowerCase().includes('placement'))
    .map((job) => ({
      id: asText(job.job_id ?? job.id, 'unknown'),
      type: asText(job.job_type ?? job.type, 'placement'),
      status: normalizeStatus(job.status) || 'unknown',
      riskLevel: normalizeRiskLevel(job.risk_level ?? job.riskLevel),
      updatedAt: job.finished_at ?? job.finishedAt ?? job.started_at ?? job.startedAt ?? null,
      readOnly: true,
      allowedActions: READ_ONLY_ACTIONS,
      raw: job,
    }))
}

export function buildPlacementViewModel({
  cluster = {},
  nodes = [],
  vms = [],
  storage = [],
  storages = [],
  networks = [],
  risks = [],
  jobs = [],
} = {}) {
  const normalizedVms = asArray(vms).map(normalizeVm)
  const normalizedStorages = asArray(storage).concat(asArray(storages)).map(normalizeStorage)
  const normalizedNetworks = asArray(networks).map(normalizeNetwork)
  const normalizedRisks = asArray(risks)
  const nodeRows = buildNodes({
    nodes,
    vms: normalizedVms,
    storages: normalizedStorages,
    networks: normalizedNetworks,
    risks: normalizedRisks,
  })
  const status = clusterStatus({ nodes: nodeRows, risks: normalizedRisks })
  const busiestNode = nodeByPressure(nodeRows, 'desc')
  const roomiestNode = nodeByPressure(nodeRows, 'asc')
  const recommendations = buildRecommendations({ nodes: nodeRows, vms: normalizedVms, risks: normalizedRisks })
  const counts = riskCounts(normalizedRisks)

  return {
    readOnly: true,
    allowedActions: READ_ONLY_ACTIONS,
    status: status.status,
    tone: statusTone(status.status),
    clusterId: asText(cluster.cluster_id ?? cluster.clusterId, 'gjallar-mvp'),
    summary: {
      totalNodes: nodeRows.length,
      onlineNodes: nodeRows.filter((node) => node.online).length,
      totalVms: normalizedVms.length,
      runningVms: normalizedVms.filter((vm) => vm.status === 'running').length,
      busiestNode: busiestNode?.name || '-',
      roomiestNode: roomiestNode?.name || '-',
      cpuImbalance: Math.round(status.cpuImbalance),
      memoryImbalance: Math.round(status.memoryImbalance),
      redRisks: counts.red,
      yellowRisks: counts.yellow,
      recommendations: recommendations.length,
    },
    nodes: nodeRows,
    vmDistribution: nodeRows.map((node) => ({
      nodeId: node.id,
      nodeName: node.name,
      running: node.runningVmCount,
      stopped: node.stoppedVmCount,
      templates: node.templateVmCount,
      total: node.totalVmCount,
      guestAgentVisible: node.guestAgentVmCount,
      ipVisible: node.visibleIpVmCount,
      risks: node.riskVmCount,
      state: node.state,
    })),
    recommendations,
    rules: {
      status: 'display_only',
      editing: 'deferred',
      candidates: [
        'Keep selected VMs apart',
        'Restrict selected VMs to a node group',
        'Exclude selected VMs from automatic movement',
        'Require matching storage and network evidence',
      ],
    },
    history: buildHistory(jobs),
  }
}

export async function loadPlacementModel(client = apiV1Client) {
  for (const method of ['clusterSummary', 'listNodes', 'listVms', 'listStorage', 'listNetworks', 'listRisks', 'listJobs']) {
    if (!client || typeof client[method] !== 'function') {
      throw new Error(`Placement requires an /api/v1 client with ${method}()`)
    }
  }

  const [clusterPayload, nodesPayload, vmsPayload, storagePayload, networksPayload, risksPayload, jobsPayload] = await Promise.all([
    client.clusterSummary(),
    client.listNodes(),
    client.listVms(),
    client.listStorage(),
    client.listNetworks(),
    client.listRisks(),
    client.listJobs(),
  ])

  return buildPlacementViewModel({
    cluster: pickObject(clusterPayload, 'cluster'),
    nodes: pickList(nodesPayload, 'nodes'),
    vms: pickList(vmsPayload, 'vms'),
    storage: pickList(storagePayload, 'storage'),
    networks: pickList(networksPayload, 'networks'),
    risks: pickList(risksPayload, 'risks'),
    jobs: pickList(jobsPayload, 'jobs'),
  })
}

export function placementToneClass(tone) {
  const normalized = String(tone ?? '').toLowerCase()
  if (normalized === 'green' || normalized === 'balanced') return 'border-emerald-200 bg-emerald-50 text-emerald-800'
  if (normalized === 'yellow' || normalized === 'watch') return 'border-amber-200 bg-amber-50 text-amber-800'
  if (normalized === 'red' || normalized === 'imbalanced') return 'border-red-200 bg-red-50 text-red-800'
  return 'border-slate-200 bg-slate-50 text-slate-800'
}
