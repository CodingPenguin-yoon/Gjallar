function asArray(value) {
  return Array.isArray(value) ? value : []
}

function asText(value, fallback = '') {
  const text = String(value ?? '').trim()
  return text || fallback
}

function normalizeStaticIpRanges(value, legacyRange = '') {
  const ranges = asArray(value)
    .map((range) => ({
      start: asText(range?.start),
      end: asText(range?.end),
    }))
    .filter((range) => range.start || range.end)

  if (ranges.length > 0) return ranges

  return String(legacyRange || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => {
      const [start, end] = item.split('-').map((part) => part.trim())
      return { start, end: end || start }
    })
}

function defaultStaticIpRanges(value, legacyRange = '') {
  const ranges = Array.isArray(value) ? normalizeStaticIpRanges(value, legacyRange) : normalizeStaticIpRanges([], value || legacyRange)
  return ranges.length > 0 ? ranges : [{ start: '', end: '' }]
}

function normalizePolicy(policy = {}) {
  return {
    apiVersion: policy.apiVersion || 'gjallar/v1',
    kind: policy.kind || 'NetworkPolicySet',
    networks: asArray(policy.networks).map((network) => ({
      network_id: asText(network.network_id || network.id),
      display_name: asText(network.display_name || network.name || network.network_id),
      description: asText(network.description),
      nodes: asArray(network.nodes).map((node) => ({
        node_id: asText(node.node_id),
        bridge_id: asText(node.bridge_id),
        subnet: asText(node.subnet),
        gateway: asText(node.gateway),
        dns: asArray(node.dns).map((item) => asText(item)).filter(Boolean),
        static_ip_ranges: normalizeStaticIpRanges(node.static_ip_ranges, node.ip_range),
      })).filter((node) => node.node_id && node.bridge_id),
    })).filter((network) => network.network_id),
  }
}

function normalizeBridge(row = {}) {
  const policy = row.policy || null
  return {
    id: `${row.node_id || 'unknown'}:${row.bridge_id || 'unknown'}`,
    nodeId: asText(row.node_id, 'unknown'),
    bridgeId: asText(row.bridge_id, 'unknown'),
    type: asText(row.type, 'bridge'),
    active: row.active !== false,
    registered: row.registered === true,
    policy,
    displayName: asText(policy?.display_name),
    networkId: asText(policy?.network_id),
    subnet: asText(policy?.subnet),
    gateway: asText(policy?.gateway),
    staticIpRanges: normalizeStaticIpRanges(policy?.static_ip_ranges, policy?.ip_range),
  }
}

export function buildNetworkPolicyModel(data = {}) {
  const bridges = asArray(data.bridges).map(normalizeBridge)
  const nodes = Array.from(new Set(bridges.map((bridge) => bridge.nodeId))).sort((left, right) => left.localeCompare(right, undefined, { numeric: true }))
  const bridgesByNode = Object.fromEntries(nodes.map((nodeId) => [
    nodeId,
    bridges
      .filter((bridge) => bridge.nodeId === nodeId)
      .sort((left, right) => left.bridgeId.localeCompare(right.bridgeId, undefined, { numeric: true })),
  ]))
  return {
    iacRoot: asText(data.iac_root),
    policyPath: asText(data.policy_path),
    policyRelativePath: asText(data.policy_relative_path),
    policyExists: data.policy_exists === true,
    policy: normalizePolicy(data.policy),
    bridges,
    nodes,
    bridgesByNode,
    missingPolicyBridges: asArray(data.missing_policy_bridges),
    summary: {
      total: bridges.length,
      registered: bridges.filter((bridge) => bridge.registered).length,
      unregistered: bridges.filter((bridge) => !bridge.registered).length,
      nodes: nodes.length,
    },
  }
}

export function upsertNetworkPolicyBinding(policy, form) {
  const networkId = asText(form.networkId)
  const nodeId = asText(form.nodeId)
  const bridgeId = asText(form.bridgeId)
  if (!networkId || !nodeId || !bridgeId) return normalizePolicy(policy)

  const next = normalizePolicy(policy)
  const binding = {
    node_id: nodeId,
    bridge_id: bridgeId,
    subnet: asText(form.subnet),
    gateway: asText(form.gateway),
    dns: String(form.dns || '').split(',').map((item) => item.trim()).filter(Boolean),
    static_ip_ranges: normalizeStaticIpRanges(form.staticIpRanges),
  }
  const index = next.networks.findIndex((network) => network.network_id === networkId)
  const network = index >= 0
    ? {
      ...next.networks[index],
      display_name: asText(form.displayName, next.networks[index].display_name || networkId),
      description: asText(form.description, next.networks[index].description),
    }
    : {
      network_id: networkId,
      display_name: asText(form.displayName, networkId),
      description: asText(form.description),
      nodes: [],
    }

  const nodeIndex = network.nodes.findIndex((node) => node.node_id === nodeId && node.bridge_id === bridgeId)
  const nodes = nodeIndex >= 0
    ? network.nodes.map((node, currentIndex) => currentIndex === nodeIndex ? binding : node)
    : [...network.nodes, binding]
  const updatedNetwork = { ...network, nodes }

  if (index >= 0) {
    next.networks[index] = updatedNetwork
  } else {
    next.networks.push(updatedNetwork)
  }
  return next
}

export function formFromBridge(bridge = {}) {
  return {
    nodeId: bridge.nodeId || bridge.node_id || '',
    bridgeId: bridge.bridgeId || bridge.bridge_id || '',
    networkId: bridge.networkId || bridge.policy?.network_id || 'server-net',
    displayName: bridge.displayName || bridge.policy?.display_name || '',
    description: bridge.policy?.description || '',
    subnet: bridge.subnet || bridge.policy?.subnet || '',
    gateway: bridge.gateway || bridge.policy?.gateway || '',
    dns: asArray(bridge.policy?.dns).join(', '),
    staticIpRanges: defaultStaticIpRanges(bridge.policy?.static_ip_ranges, bridge.policy?.ip_range),
  }
}
