const READ_ONLY_ACTIONS = Object.freeze([])
const RUNNING_STATUSES = new Set(['running', 'pending', 'in_progress', 'processing'])
const COMPLETED_STATUSES = new Set(['completed', 'success'])
const BLOCKED_STATUSES = new Set(['blocked'])
const FAILED_STATUSES = new Set(['failed', 'error'])
const RISK_LEVELS = new Set(['red', 'yellow', 'green'])

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

function normalizeStatus(status) {
  return String(status ?? '').trim().toLowerCase()
}

function normalizeNodeId(source = {}) {
  return asText(source.node_id ?? source.node ?? source.server_id ?? source.id, 'unknown')
}

function normalizeVmName(source = {}) {
  return asText(source.name ?? source.vm_name ?? source.server_name ?? `vm-${source.vmid ?? 'unknown'}`, 'unknown')
}

function memoryToGb(source = {}) {
  if (source.memory_gb !== undefined) return asNumber(source.memory_gb)
  if (source.memoryGb !== undefined) return asNumber(source.memoryGb)
  if (source.memory_mb !== undefined) return asNumber(source.memory_mb) / 1024
  if (source.memoryMb !== undefined) return asNumber(source.memoryMb) / 1024
  if (source.memory !== undefined) return asNumber(source.memory)
  return 0
}

function diskToGb(source = {}) {
  if (source.disk_gb !== undefined) return asNumber(source.disk_gb)
  if (source.diskGb !== undefined) return asNumber(source.diskGb)
  const disks = asArray(source.disks)
  if (disks.length > 0) {
    return disks.reduce((total, disk) => total + asNumber(disk?.size_gb ?? disk?.sizeGb ?? disk?.gb), 0)
  }
  return 0
}

function cpuCount(source = {}) {
  return asNumber(source.cpu_cores ?? source.cpuCores ?? source.cpu ?? source.cpus)
}

function primaryIp(source = {}) {
  const ips = asArray(source.ip_addresses ?? source.ipAddresses)
  return asText(source.primary_ip ?? source.primaryIp ?? ips[0], '-')
}

function parseIpv4Octets(value) {
  const text = String(value ?? '').trim()
  const parts = text.split('.')
  if (parts.length !== 4) return null
  const octets = parts.map((part) => Number(part))
  if (octets.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) return null
  return octets
}

function isLikelyContainerIp(value) {
  const octets = parseIpv4Octets(value)
  if (!octets) return false
  return octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31
}

function rankDisplayIp(value) {
  const octets = parseIpv4Octets(value)
  if (!octets) return 100
  if (octets[0] === 127 || (octets[0] === 169 && octets[1] === 254)) return 90
  if (isLikelyContainerIp(value)) return 80
  if (octets[0] === 192 && octets[1] === 168) return 0
  if (octets[0] === 10) return 10
  return 20
}

function uniqueTextList(values) {
  const seen = new Set()
  const unique = []
  asArray(values).forEach((value) => {
    const text = String(value ?? '').trim()
    if (!text || seen.has(text)) return
    seen.add(text)
    unique.push(text)
  })
  return unique
}

function pickDisplayIp(addresses) {
  const ranked = uniqueTextList(addresses)
    .map((address, index) => ({ address, index, rank: rankDisplayIp(address) }))
    .filter((item) => item.rank < 80)
    .sort((left, right) => left.rank - right.rank || left.index - right.index)
  return ranked[0]?.address || '-'
}

function hiddenDisplayIps(addresses, displayIp) {
  const ips = uniqueTextList(addresses)
  if (!displayIp || displayIp === '-') return ips
  return ips.filter((address) => address !== displayIp)
}

function normalizeDisk(source = {}, index = 0) {
  return {
    device: asText(source.device, `disk-${index + 1}`),
    bus: asText(source.bus, ''),
    index: asNumber(source.index, index),
    sizeGb: asNumber(source.size_gb ?? source.sizeGb ?? source.gb),
    storageId: asText(source.storage_id ?? source.storageId ?? source.storage, 'unknown'),
    volumeId: asText(source.volume_id ?? source.volumeId, ''),
    volume: asText(source.volume, ''),
    boot: Boolean(source.boot),
    format: asText(source.format, ''),
    cache: asText(source.cache, ''),
    discard: asText(source.discard, ''),
    iothread: asText(source.iothread, ''),
    ssd: asText(source.ssd, ''),
    backup: asText(source.backup, ''),
    readonly: asText(source.readonly, ''),
  }
}

function normalizeGuestAgent(source = {}) {
  const guestAgent = source.guest_agent ?? source.guestAgent ?? {}
  return {
    available: Boolean(guestAgent.available),
    ipAddresses: asArray(guestAgent.ip_addresses ?? guestAgent.ipAddresses).filter(Boolean),
  }
}

function normalizeVm(source = {}) {
  const disks = asArray(source.disks).map(normalizeDisk)
  const configuredPrimaryIp = primaryIp(source)
  const sourceIpAddresses = uniqueTextList(source.ip_addresses ?? source.ipAddresses)
  const ipAddresses = sourceIpAddresses.length > 0
    ? sourceIpAddresses
    : configuredPrimaryIp !== '-' ? [configuredPrimaryIp] : []
  const primaryIpAddress = pickDisplayIp(ipAddresses)
  const hiddenIpAddresses = hiddenDisplayIps(ipAddresses, primaryIpAddress)
  const guestAgent = normalizeGuestAgent(source)
  return {
    id: asText(source.vmid ?? source.id, 'unknown'),
    vmid: source.vmid ?? source.id ?? null,
    name: normalizeVmName(source),
    nodeId: normalizeNodeId(source),
    status: normalizeStatus(source.status) || 'unknown',
    primaryIp: primaryIpAddress,
    ipAddresses,
    hiddenIpAddresses,
    hiddenIpCount: hiddenIpAddresses.length,
    guestAgent,
    cpuCores: cpuCount(source),
    memoryGb: memoryToGb(source),
    diskGb: diskToGb({ ...source, disks }),
    disks,
    storageId: asText(source.storage_id ?? source.storageId ?? disks[0]?.storageId, 'unknown'),
    tags: asArray(source.tags).filter(Boolean),
    template: Boolean(source.template),
    readOnly: true,
    allowedActions: READ_ONLY_ACTIONS,
    raw: source,
  }
}

function compareByName(left, right) {
  return String(left.name).localeCompare(String(right.name), undefined, { numeric: true, sensitivity: 'base' })
}

export function buildInfraExplorerModel({ nodes = [], vms = [] } = {}) {
  const nodeMap = new Map()
  asArray(nodes).forEach((node) => {
    const id = normalizeNodeId(node)
    nodeMap.set(id, {
      id,
      name: asText(node.display_name ?? node.name ?? node.node_name ?? id, id),
      status: normalizeStatus(node.status) || 'unknown',
      vms: [],
      readOnly: true,
      allowedActions: READ_ONLY_ACTIONS,
      raw: node,
    })
  })

  asArray(vms).map(normalizeVm).forEach((vm) => {
    if (!nodeMap.has(vm.nodeId)) {
      nodeMap.set(vm.nodeId, {
        id: vm.nodeId,
        name: vm.nodeId === 'unknown' ? 'Unknown' : vm.nodeId,
        status: 'unknown',
        vms: [],
        readOnly: true,
        allowedActions: READ_ONLY_ACTIONS,
        raw: {},
      })
    }
    nodeMap.get(vm.nodeId).vms.push(vm)
  })

  const normalizedNodes = Array.from(nodeMap.values())
    .map((node) => ({ ...node, vms: [...node.vms].sort(compareByName) }))
    .sort((left, right) => {
      if (left.id === 'unknown') return 1
      if (right.id === 'unknown') return -1
      return compareByName(left, right)
    })
  const allVms = normalizedNodes.flatMap((node) => node.vms)

  return {
    readOnly: true,
    allowedActions: READ_ONLY_ACTIONS,
    nodes: normalizedNodes,
    summary: {
      totalNodes: normalizedNodes.filter((node) => node.id !== 'unknown').length,
      totalVms: allVms.length,
      runningVms: allVms.filter((vm) => vm.status === 'running').length,
      stoppedVms: allVms.filter((vm) => vm.status === 'stopped').length,
      visibleIpCount: allVms.filter((vm) => vm.primaryIp !== '-').length,
      guestAgentCount: allVms.filter((vm) => vm.guestAgent.available).length,
    },
  }
}

function normalizeRiskLevel(level) {
  const normalized = String(level ?? '').trim().toLowerCase()
  return RISK_LEVELS.has(normalized) ? normalized : 'unknown'
}

function normalizeJob(source = {}) {
  const status = normalizeStatus(source.status) || 'unknown'
  const riskLevel = normalizeRiskLevel(source.risk_level ?? source.riskLevel)
  return {
    id: asText(source.job_id ?? source.id, 'unknown'),
    type: asText(source.job_type ?? source.type, 'unknown'),
    status,
    targetId: asText(source.target_id ?? source.targetId, '-'),
    riskLevel,
    tone: riskLevel === 'unknown' ? status : riskLevel,
    artifactCount: asNumber(source.artifact_count ?? source.artifactCount),
    riskCount: asNumber(source.risk_count ?? source.riskCount),
    startedAt: source.started_at ?? source.startedAt ?? null,
    finishedAt: source.finished_at ?? source.finishedAt ?? null,
    artifactsUrl: source.artifacts_url ?? source.artifactsUrl ?? null,
    readOnly: true,
    allowedActions: READ_ONLY_ACTIONS,
    raw: source,
  }
}

export function buildJobsViewModel(jobs = []) {
  const items = asArray(jobs).map(normalizeJob)
  return {
    readOnly: true,
    allowedActions: READ_ONLY_ACTIONS,
    items,
    summary: {
      total: items.length,
      running: items.filter((job) => RUNNING_STATUSES.has(job.status)).length,
      completed: items.filter((job) => COMPLETED_STATUSES.has(job.status)).length,
      blocked: items.filter((job) => BLOCKED_STATUSES.has(job.status)).length,
      failed: items.filter((job) => FAILED_STATUSES.has(job.status)).length,
    },
  }
}

function normalizeRisk(source = {}) {
  const level = normalizeRiskLevel(source.level ?? source.risk_level ?? source.riskLevel)
  return {
    id: asText(source.risk_id ?? source.id ?? `${source.job_id ?? 'job'}:${source.code ?? 'risk'}`, 'unknown'),
    jobId: source.job_id ?? source.jobId ?? null,
    level,
    code: asText(source.code, 'unknown'),
    message: asText(source.message ?? source.detail ?? source.title, ''),
    artifactsUrl: source.artifacts_url ?? source.artifactsUrl ?? null,
    readOnly: true,
    allowedActions: READ_ONLY_ACTIONS,
    raw: source,
  }
}

export function buildRisksViewModel(risks = []) {
  const items = asArray(risks).map(normalizeRisk)
  return {
    readOnly: true,
    allowedActions: READ_ONLY_ACTIONS,
    items,
    summary: {
      total: items.length,
      red: items.filter((risk) => risk.level === 'red').length,
      yellow: items.filter((risk) => risk.level === 'yellow').length,
      green: items.filter((risk) => risk.level === 'green').length,
      unknown: items.filter((risk) => risk.level === 'unknown').length,
    },
  }
}
