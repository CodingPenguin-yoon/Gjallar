function asArray(value) {
  return Array.isArray(value) ? value : []
}

function asText(value, fallback = '') {
  const text = String(value ?? '').trim()
  return text || fallback
}

function asNullableInteger(value, { min = Number.MIN_SAFE_INTEGER, max = Number.MAX_SAFE_INTEGER } = {}) {
  const text = String(value ?? '').trim()
  if (!text) return null
  const parsed = Number(text)
  if (!Number.isInteger(parsed) || parsed < min || parsed > max) return null
  return parsed
}

function naturalCompare(left, right) {
  return String(left).localeCompare(String(right), undefined, { numeric: true, sensitivity: 'base' })
}

function uniqueTextList(values) {
  const seen = new Set()
  const unique = []
  asArray(values).forEach((value) => {
    const text = asText(value)
    if (!text || seen.has(text)) return
    seen.add(text)
    unique.push(text)
  })
  return unique
}

function sameTextSet(leftValues, rightValues) {
  const left = new Set(uniqueTextList(leftValues))
  const right = new Set(uniqueTextList(rightValues))
  if (left.size !== right.size) return false
  return Array.from(left).every((value) => right.has(value))
}

function sharedTextList(leftValues, rightValues) {
  const right = new Set(uniqueTextList(rightValues))
  return uniqueTextList(leftValues).filter((value) => right.has(value)).sort(naturalCompare)
}

function normalizeBridgePorts(value) {
  if (typeof value === 'string') {
    return uniqueTextList(value.split(/[\s,]+/).filter(Boolean))
  }
  return uniqueTextList(value)
}

function normalizeActive(value) {
  if (value === undefined || value === null) return true
  if (value === false || value === 0) return false
  const text = String(value).trim().toLowerCase()
  return !['0', 'false', 'inactive'].includes(text)
}

function normalizeOptionalBoolean(value) {
  if (value === undefined || value === null || value === '') return null
  if (value === true || value === false) return value
  if (value === 1 || value === '1') return true
  if (value === 0 || value === '0') return false
  const text = String(value).trim().toLowerCase()
  if (['true', 'yes', 'on'].includes(text)) return true
  if (['false', 'no', 'off'].includes(text)) return false
  return null
}

function normalizeNode(row = {}) {
  const nodeId = asText(row.node_id ?? row.nodeId ?? row.node ?? row.id, 'unknown')
  return {
    nodeId,
    displayName: asText(row.display_name ?? row.displayName ?? row.name, nodeId),
    status: asText(row.status, 'unknown').toLowerCase(),
    raw: row,
  }
}

function normalizeBridge(row = {}) {
  const nodeId = asText(row.node_id ?? row.nodeId ?? row.node, 'unknown')
  const bridgeId = asText(row.bridge_id ?? row.bridgeId ?? row.name ?? row.id, 'unknown')
  const prefix = asNullableInteger(row.prefix ?? row.prefix_len ?? row.prefixLen, { min: 0, max: 32 })
  const activeValue = row.active
  return {
    id: `${nodeId}:${bridgeId}`,
    nodeId,
    bridgeId,
    type: asText(row.type, 'bridge'),
    active: normalizeActive(activeValue),
    activeObserved: activeValue !== undefined && activeValue !== null && activeValue !== '',
    address: asText(row.address ?? row.ip_address ?? row.ipAddress),
    netmask: asText(row.netmask ?? row.mask),
    prefix,
    cidr: asText(row.cidr),
    gateway: asText(row.gateway ?? row.gw),
    bridgePorts: normalizeBridgePorts(row.bridge_ports ?? row.bridgePorts ?? row.ports),
    vlanAware: normalizeOptionalBoolean(row.vlan_aware ?? row.vlanAware ?? row.bridge_vlan_aware),
    mtu: asNullableInteger(row.mtu, { min: 1 }),
    raw: row,
  }
}

function normalizeGuestAgent(row = {}) {
  const guestAgent = row.guest_agent ?? row.guestAgent ?? {}
  return {
    available: Boolean(guestAgent.available),
    ipAddresses: uniqueTextList(guestAgent.ip_addresses ?? guestAgent.ipAddresses),
  }
}

function normalizeIpEvidence(row = {}) {
  return asArray(row.ip_evidence ?? row.ipEvidence)
    .map((item = {}) => ({
      ipAddress: asText(item.ip_address ?? item.ipAddress),
      source: asText(item.source, 'unknown'),
      interfaceName: asText(item.interface_name ?? item.interfaceName),
      interfaceType: asText(item.interface_type ?? item.interfaceType),
      scope: asText(item.scope, 'observed'),
      primaryCandidate: Boolean(item.primary_candidate ?? item.primaryCandidate),
      duplicateWarningEligible: Boolean(item.duplicate_warning_eligible ?? item.duplicateWarningEligible),
      raw: item,
    }))
    .filter((item) => item.ipAddress)
}

function normalizeVm(row = {}) {
  const guestAgent = normalizeGuestAgent(row)
  const ipEvidence = normalizeIpEvidence(row)
  const hasStructuredIpEvidence = ipEvidence.length > 0
  const ipAddresses = hasStructuredIpEvidence
    ? uniqueTextList(ipEvidence.map((item) => item.ipAddress))
    : uniqueTextList([
        ...asArray(row.ip_addresses ?? row.ipAddresses),
        ...guestAgent.ipAddresses,
      ])
  const duplicateWarningIps = hasStructuredIpEvidence
    ? uniqueTextList(ipEvidence.filter((item) => item.duplicateWarningEligible).map((item) => item.ipAddress))
    : ipAddresses
  const vmid = row.vmid ?? row.id ?? 'unknown'
  return {
    id: asText(vmid, 'unknown'),
    vmid,
    name: asText(row.name ?? row.vm_name ?? row.vmName, `vm-${vmid}`),
    nodeId: asText(row.node_id ?? row.nodeId ?? row.node, 'unknown'),
    status: asText(row.status, 'unknown').toLowerCase(),
    template: Boolean(row.template),
    ipAddresses,
    ipEvidence,
    duplicateWarningIps,
    guestAgent,
    readiness: {
      status: 'unknown',
      reason: 'vm_nic_bridge_evidence_missing',
    },
    raw: row,
  }
}

function bridgeRowsFromNodes(nodes) {
  return asArray(nodes).flatMap((node) => (
    asArray(node?.networks).map((network) => ({
      ...network,
      node_id: network?.node_id ?? network?.nodeId ?? node?.node_id ?? node?.nodeId ?? node?.id,
    }))
  ))
}

function mergeBridgeEvidence(existing, bridge) {
  if (!existing) return bridge

  const merged = { ...existing }
  if (!existing.activeObserved && bridge.activeObserved) {
    merged.active = bridge.active
    merged.activeObserved = true
  }

  const textEvidenceFields = ['address', 'netmask', 'cidr', 'gateway']
  textEvidenceFields.forEach((field) => {
    if (!asText(merged[field]) && asText(bridge[field])) {
      merged[field] = bridge[field]
    }
  })

  if (merged.prefix === null && bridge.prefix !== null) merged.prefix = bridge.prefix
  if (merged.mtu === null && bridge.mtu !== null) merged.mtu = bridge.mtu
  if (merged.vlanAware === null && bridge.vlanAware !== null) merged.vlanAware = bridge.vlanAware
  if (merged.bridgePorts.length === 0 && bridge.bridgePorts.length > 0) merged.bridgePorts = bridge.bridgePorts

  return merged
}

function buildDuplicateIpWarnings(vms) {
  const byIp = new Map()
  vms.forEach((vm) => {
    vm.duplicateWarningIps.forEach((ip) => {
      if (!byIp.has(ip)) byIp.set(ip, new Map())
      byIp.get(ip).set(vm.id, vm)
    })
  })
  return Array.from(byIp.entries())
    .map(([ipAddress, ownerMap]) => [ipAddress, Array.from(ownerMap.values())])
    .filter(([, owners]) => owners.length > 1)
    .map(([ipAddress, owners]) => ({
      code: 'duplicate_ip_observed',
      ipAddress,
      vmIds: owners.map((vm) => vm.id),
      vmNames: owners.map((vm) => vm.name),
    }))
    .sort((left, right) => naturalCompare(left.ipAddress, right.ipAddress))
}

function buildBridgeMatrix({ nodes, bridges, bridgeIds }) {
  const bridgeMap = new Map(bridges.map((bridge) => [bridge.id, bridge]))
  return nodes.map((node) => ({
    nodeId: node.nodeId,
    displayName: node.displayName,
    status: node.status,
    bridges: bridgeIds.map((bridgeId) => {
      const bridge = bridgeMap.get(`${node.nodeId}:${bridgeId}`)
      if (!bridge) {
        return {
          nodeId: node.nodeId,
          bridgeId,
          status: 'missing',
          active: false,
          evidence: null,
        }
      }
      return {
        nodeId: node.nodeId,
        bridgeId,
        status: bridge.active ? 'active' : 'inactive',
        active: bridge.active,
        evidence: bridge,
      }
    }),
  }))
}

function configEvidenceStatus(values, expectedCount, kind = 'subnet') {
  if (expectedCount <= 0) return 'missing'
  const observedValues = values.map((value) => asText(value)).filter(Boolean)
  if (observedValues.length === 0) return 'unverified'
  if (observedValues.length < expectedCount) return 'partial'
  const uniqueValues = uniqueTextList(observedValues)
  if (uniqueValues.length === 1) return kind === 'gateway' ? 'gateway_match' : 'subnet_match'
  return kind === 'gateway' ? 'gateway_mismatch' : 'subnet_mismatch'
}

function buildBridgeCoverageSummary({ nodes, bridges, bridgeIds }) {
  const bridgeMap = new Map(bridges.map((bridge) => [bridge.id, bridge]))
  return bridgeIds.map((bridgeId) => {
    const presentBridges = []
    const presentNodes = []
    const activeNodes = []
    const missingNodes = []
    nodes.forEach((node) => {
      const bridge = bridgeMap.get(`${node.nodeId}:${bridgeId}`)
      if (!bridge) {
        missingNodes.push(node.nodeId)
        return
      }
      presentBridges.push(bridge)
      presentNodes.push(node.nodeId)
      if (bridge.active) activeNodes.push(node.nodeId)
    })
    const cidrs = uniqueTextList(presentBridges.map((bridge) => bridge.cidr)).sort(naturalCompare)
    const gateways = uniqueTextList(presentBridges.map((bridge) => bridge.gateway)).sort(naturalCompare)
    const subnetEvidenceStatus = configEvidenceStatusForBridge(presentBridges, 'subnet', nodes.length)
    const gatewayEvidenceStatus = configEvidenceStatusForBridge(presentBridges, 'gateway', nodes.length)
    return {
      bridgeId,
      nodeCount: nodes.length,
      presentCount: presentNodes.length,
      activeCount: activeNodes.length,
      missingCount: missingNodes.length,
      presentNodes,
      activeNodes,
      missingNodes,
      cidrs,
      gateways,
      configEvidenceStatus: subnetEvidenceStatus,
      gatewayEvidenceStatus,
    }
  })
}

function configEvidenceStatusForBridge(bridges, kind, expectedCount = asArray(bridges).length) {
  const field = kind === 'gateway' ? 'gateway' : 'cidr'
  return configEvidenceStatus(asArray(bridges).map((bridge) => bridge?.[field]), expectedCount, kind)
}

function buildSubnetCoverageSummary({ nodes, bridges }) {
  const bridgesByCidr = new Map()
  bridges.forEach((bridge) => {
    if (!bridge.cidr) return
    if (!bridgesByCidr.has(bridge.cidr)) bridgesByCidr.set(bridge.cidr, [])
    bridgesByCidr.get(bridge.cidr).push(bridge)
  })

  return Array.from(bridgesByCidr.entries())
    .map(([cidr, subnetBridges]) => {
      const bridgesByNode = new Map()
      subnetBridges.forEach((bridge) => {
        if (!bridgesByNode.has(bridge.nodeId)) bridgesByNode.set(bridge.nodeId, [])
        bridgesByNode.get(bridge.nodeId).push(bridge)
      })
      const nodeMappings = nodes.map((node) => {
        const nodeBridges = asArray(bridgesByNode.get(node.nodeId))
          .sort((left, right) => naturalCompare(left.bridgeId, right.bridgeId))
        const bridgeIds = uniqueTextList(nodeBridges.map((bridge) => bridge.bridgeId)).sort(naturalCompare)
        const activeBridgeIds = uniqueTextList(nodeBridges.filter((bridge) => bridge.active).map((bridge) => bridge.bridgeId)).sort(naturalCompare)
        return {
          nodeId: node.nodeId,
          displayName: node.displayName,
          bridgeIds,
          activeBridgeIds,
          inactiveBridgeIds: bridgeIds.filter((bridgeId) => !activeBridgeIds.includes(bridgeId)),
          gateways: uniqueTextList(nodeBridges.map((bridge) => bridge.gateway)).sort(naturalCompare),
        }
      })
      const presentNodes = nodeMappings.filter((mapping) => mapping.bridgeIds.length > 0).map((mapping) => mapping.nodeId)
      const activeNodes = nodeMappings.filter((mapping) => mapping.activeBridgeIds.length > 0).map((mapping) => mapping.nodeId)
      const missingNodes = nodeMappings.filter((mapping) => mapping.bridgeIds.length === 0).map((mapping) => mapping.nodeId)

      return {
        cidr,
        nodeCount: nodes.length,
        presentCount: presentNodes.length,
        activeCount: activeNodes.length,
        missingCount: missingNodes.length,
        presentNodes,
        activeNodes,
        missingNodes,
        gateways: uniqueTextList(subnetBridges.map((bridge) => bridge.gateway)).sort(naturalCompare),
        nodeMappings,
      }
    })
    .sort((left, right) => naturalCompare(left.cidr, right.cidr))
}

function bridgeEndpointEvidence(bridge) {
  return {
    nodeId: bridge.nodeId,
    bridgeId: bridge.bridgeId,
    active: bridge.active,
    address: bridge.address,
    netmask: bridge.netmask,
    prefix: bridge.prefix,
    cidr: bridge.cidr,
    gateway: bridge.gateway,
    bridgePorts: bridge.bridgePorts,
    vlanAware: bridge.vlanAware,
    mtu: bridge.mtu,
  }
}

function sortBridgesById(left, right) {
  return naturalCompare(left.bridgeId, right.bridgeId)
}

function activeBridgesByNode(bridges, nodeId) {
  return asArray(bridges)
    .filter((bridge) => bridge?.nodeId === nodeId && bridge.active)
    .sort(sortBridgesById)
}

function bridgesByNode(bridges, nodeId) {
  return asArray(bridges)
    .filter((bridge) => bridge?.nodeId === nodeId)
    .sort(sortBridgesById)
}

function indexBridgesByCidr(bridges) {
  const byCidr = new Map()
  bridges.forEach((bridge) => {
    if (!bridge.cidr) return
    if (!byCidr.has(bridge.cidr)) byCidr.set(bridge.cidr, [])
    byCidr.get(bridge.cidr).push(bridge)
  })
  return byCidr
}

function bridgeIdsFrom(bridges) {
  return uniqueTextList(asArray(bridges).map((bridge) => bridge.bridgeId)).sort(naturalCompare)
}

function buildSubnetMappings(sourceActive, targetActive) {
  const sourceByCidr = new Map()
  const targetByCidr = new Map()
  sourceActive.forEach((bridge) => {
    if (!bridge.cidr) return
    if (!sourceByCidr.has(bridge.cidr)) sourceByCidr.set(bridge.cidr, [])
    sourceByCidr.get(bridge.cidr).push(bridge)
  })
  targetActive.forEach((bridge) => {
    if (!bridge.cidr) return
    if (!targetByCidr.has(bridge.cidr)) targetByCidr.set(bridge.cidr, [])
    targetByCidr.get(bridge.cidr).push(bridge)
  })

  return Array.from(sourceByCidr.entries())
    .filter(([cidr]) => targetByCidr.has(cidr))
    .map(([cidr, sourceBridges]) => {
      const targetBridges = targetByCidr.get(cidr)
      const sourceBridgeIds = uniqueTextList(sourceBridges.map((bridge) => bridge.bridgeId)).sort(naturalCompare)
      const targetBridgeIds = uniqueTextList(targetBridges.map((bridge) => bridge.bridgeId)).sort(naturalCompare)
      if (sameTextSet(sourceBridgeIds, targetBridgeIds)) return null
      const sharedBridgeIds = sharedTextList(sourceBridgeIds, targetBridgeIds)
      return {
        cidr,
        status: 'remap_candidate',
        sourceBridgeIds,
        targetBridgeIds,
        sharedBridgeIds,
        sourceOnlyBridgeIds: sourceBridgeIds.filter((bridgeId) => !targetBridgeIds.includes(bridgeId)),
        targetOnlyBridgeIds: targetBridgeIds.filter((bridgeId) => !sourceBridgeIds.includes(bridgeId)),
        sourceGateways: uniqueTextList(sourceBridges.map((bridge) => bridge.gateway)).sort(naturalCompare),
        targetGateways: uniqueTextList(targetBridges.map((bridge) => bridge.gateway)).sort(naturalCompare),
        gateways: uniqueTextList([
          ...sourceBridges.map((bridge) => bridge.gateway),
          ...targetBridges.map((bridge) => bridge.gateway),
        ]).sort(naturalCompare),
      }
    })
    .filter(Boolean)
    .sort((left, right) => naturalCompare(left.cidr, right.cidr))
}

function buildNetworkComparisons({ sourceActiveBridges, targetBridges, readinessEvidenceAvailable }) {
  const targetActiveBridges = asArray(targetBridges).filter((bridge) => bridge.active).sort(sortBridgesById)
  const targetByBridgeId = new Map(asArray(targetBridges).map((bridge) => [bridge.bridgeId, bridge]))
  const targetActiveByBridgeId = new Map(targetActiveBridges.map((bridge) => [bridge.bridgeId, bridge]))
  const sourceActiveByCidr = indexBridgesByCidr(sourceActiveBridges)
  const targetActiveByCidr = indexBridgesByCidr(targetActiveBridges)

  return asArray(sourceActiveBridges).map((sourceBridge) => {
    const sourceCidrBridges = sourceBridge.cidr ? asArray(sourceActiveByCidr.get(sourceBridge.cidr)) : []
    const targetCidrBridges = sourceBridge.cidr ? asArray(targetActiveByCidr.get(sourceBridge.cidr)) : []
    const sourceCidrBridgeIds = bridgeIdsFrom(sourceCidrBridges)
    const targetCidrBridgeIds = bridgeIdsFrom(targetCidrBridges)
    const sameCidrBridgeIds = sharedTextList(sourceCidrBridgeIds, targetCidrBridgeIds)
    const exactBridge = targetActiveByBridgeId.get(sourceBridge.bridgeId)
    const sameBridge = targetByBridgeId.get(sourceBridge.bridgeId)
    const remapTargetBridges = targetCidrBridges
      .filter((bridge) => bridge.bridgeId !== sourceBridge.bridgeId)
      .sort(sortBridgesById)
    const base = {
      id: `${sourceBridge.nodeId}:${sourceBridge.bridgeId}->${targetBridges[0]?.nodeId || 'unknown'}`,
      sourceBridgeId: sourceBridge.bridgeId,
      sourceBridge: bridgeEndpointEvidence(sourceBridge),
      sourceCidr: sourceBridge.cidr,
      sourceGateway: sourceBridge.gateway,
      sourceCidrBridgeIds,
      targetCidrBridgeIds,
      sameCidrBridgeIds,
      targetBridgeIds: [],
      targetBridges: [],
      cidrs: uniqueTextList([sourceBridge.cidr]).sort(naturalCompare),
      gateways: uniqueTextList([sourceBridge.gateway]).sort(naturalCompare),
      subnetStatus: sourceBridge.cidr ? 'unverified' : 'missing',
      gatewayStatus: sourceBridge.gateway ? 'unverified' : 'missing',
      reason: 'target_bridge_missing',
    }

    if (!readinessEvidenceAvailable) {
      return {
        ...base,
        status: 'unknown',
        reason: 'bridge_evidence_missing',
      }
    }

    if (exactBridge) {
      const evidence = sharedBridgeEvidence(sourceBridge.bridgeId, sourceBridge, exactBridge)
      const status = evidence.subnetStatus === 'subnet_match'
        ? 'exact'
        : evidence.subnetStatus === 'subnet_mismatch'
          ? 'bridge_id_subnet_mismatch'
          : 'bridge_name_unverified'
      const reason = evidence.subnetStatus === 'subnet_match'
        ? 'cidr_verified_exact_bridge_match'
        : evidence.subnetStatus === 'subnet_mismatch'
          ? 'bridge_id_subnet_mismatch'
          : 'bridge_name_cidr_unverified'
      return {
        ...base,
        status,
        reason,
        targetBridgeIds: [exactBridge.bridgeId],
        targetBridges: [bridgeEndpointEvidence(exactBridge)],
        cidrs: evidence.cidrs,
        gateways: evidence.gateways,
        subnetStatus: evidence.subnetStatus,
        gatewayStatus: evidence.gatewayStatus,
      }
    }

    if (
      sourceBridge.cidr
      && remapTargetBridges.length > 0
      && !sameTextSet(sourceCidrBridgeIds, targetCidrBridgeIds)
    ) {
      return {
        ...base,
        status: 'remap_candidate',
        reason: 'same_cidr_different_bridge_ids',
        targetBridgeIds: bridgeIdsFrom(remapTargetBridges),
        targetBridges: remapTargetBridges.map(bridgeEndpointEvidence),
        cidrs: uniqueTextList([
          sourceBridge.cidr,
          ...remapTargetBridges.map((bridge) => bridge.cidr),
        ]).sort(naturalCompare),
        gateways: uniqueTextList([
          sourceBridge.gateway,
          ...remapTargetBridges.map((bridge) => bridge.gateway),
        ]).sort(naturalCompare),
        subnetStatus: configEvidenceStatus([
          sourceBridge.cidr,
          ...remapTargetBridges.map((bridge) => bridge.cidr),
        ], remapTargetBridges.length + 1, 'subnet'),
        gatewayStatus: configEvidenceStatus([
          sourceBridge.gateway,
          ...remapTargetBridges.map((bridge) => bridge.gateway),
        ], remapTargetBridges.length + 1, 'gateway'),
      }
    }

    if (sameBridge && !sameBridge.active) {
      return {
        ...base,
        status: 'inactive',
        reason: 'target_bridge_inactive',
        targetBridgeIds: [sameBridge.bridgeId],
        targetBridges: [bridgeEndpointEvidence(sameBridge)],
        cidrs: uniqueTextList([sourceBridge.cidr, sameBridge.cidr]).sort(naturalCompare),
        gateways: uniqueTextList([sourceBridge.gateway, sameBridge.gateway]).sort(naturalCompare),
        subnetStatus: configEvidenceStatus([sourceBridge.cidr, sameBridge.cidr], 2, 'subnet'),
        gatewayStatus: configEvidenceStatus([sourceBridge.gateway, sameBridge.gateway], 2, 'gateway'),
      }
    }

    return {
      ...base,
      status: 'missing',
      reason: sourceBridge.cidr ? 'target_bridge_missing' : 'source_bridge_cidr_unavailable',
    }
  })
}

function buildNetworkComparisonSummary(networkComparisons) {
  const comparisons = asArray(networkComparisons)
  return {
    exact: comparisons.filter((comparison) => comparison.status === 'exact').length,
    remapCandidate: comparisons.filter((comparison) => comparison.status === 'remap_candidate').length,
    bridgeNameUnverified: comparisons.filter((comparison) => comparison.status === 'bridge_name_unverified').length,
    bridgeIdSubnetMismatch: comparisons.filter((comparison) => comparison.status === 'bridge_id_subnet_mismatch').length,
    missing: comparisons.filter((comparison) => comparison.status === 'missing').length,
    inactive: comparisons.filter((comparison) => comparison.status === 'inactive').length,
    unknown: comparisons.filter((comparison) => comparison.status === 'unknown').length,
  }
}

function buildTargetReadinessFromComparisons(networkComparisons, readinessEvidenceAvailable) {
  if (!readinessEvidenceAvailable) {
    return {
      status: 'unknown',
      reason: 'bridge_evidence_missing',
    }
  }

  const comparisons = asArray(networkComparisons)
  const summary = buildNetworkComparisonSummary(comparisons)
  if (comparisons.length === 0) {
    return {
      status: 'blocked',
      reason: 'no_shared_active_bridge',
    }
  }

  if (summary.unknown > 0 && summary.unknown === comparisons.length) {
    return {
      status: 'unknown',
      reason: 'bridge_evidence_missing',
    }
  }

  if (summary.bridgeIdSubnetMismatch > 0) {
    return {
      status: 'blocked',
      reason: 'bridge_id_subnet_mismatch',
    }
  }

  if (summary.missing > 0) {
    return {
      status: 'blocked',
      reason: 'target_bridge_missing',
    }
  }

  if (summary.inactive > 0) {
    return {
      status: 'blocked',
      reason: 'target_bridge_inactive',
    }
  }

  if (summary.unknown > 0) {
    return {
      status: 'unknown',
      reason: 'bridge_evidence_missing',
    }
  }

  if (summary.bridgeNameUnverified > 0) {
    return {
      status: 'needs_review',
      reason: 'bridge_name_cidr_unverified',
    }
  }

  if (summary.remapCandidate > 0) {
    return {
      status: 'needs_review',
      reason: 'same_cidr_different_bridge_ids',
    }
  }

  if (summary.exact === comparisons.length) {
    return {
      status: 'ready',
      reason: 'cidr_verified_exact_bridge_match',
    }
  }

  return {
    status: 'blocked',
    reason: 'no_shared_active_bridge',
  }
}

function sharedBridgeEvidence(bridgeId, sourceBridge, targetBridge) {
  const cidrs = uniqueTextList([sourceBridge?.cidr, targetBridge?.cidr]).sort(naturalCompare)
  const gateways = uniqueTextList([sourceBridge?.gateway, targetBridge?.gateway]).sort(naturalCompare)
  const subnetStatus = configEvidenceStatus([sourceBridge?.cidr, targetBridge?.cidr], 2, 'subnet')
  const gatewayStatus = configEvidenceStatus([sourceBridge?.gateway, targetBridge?.gateway], 2, 'gateway')
  return {
    bridgeId,
    cidrs,
    gateways,
    subnetStatus,
    gatewayStatus,
    status: subnetStatus,
    source: bridgeEndpointEvidence(sourceBridge),
    target: bridgeEndpointEvidence(targetBridge),
  }
}

function buildNodePairReadiness({ nodes, bridges, readinessEvidenceAvailable }) {
  const activeByNode = new Map(nodes.map((node) => [node.nodeId, new Map()]))
  bridges.forEach((bridge) => {
    if (bridge.active && activeByNode.has(bridge.nodeId)) {
      activeByNode.get(bridge.nodeId).set(bridge.bridgeId, bridge)
    }
  })

  const pairs = []
  nodes.forEach((source) => {
    nodes.forEach((target) => {
      if (source.nodeId === target.nodeId) return
      const sourceActive = activeByNode.get(source.nodeId)
      const targetActive = activeByNode.get(target.nodeId)
      const evidenceMissing = !readinessEvidenceAvailable || !sourceActive || !targetActive
      const sharedActiveBridges = evidenceMissing
        ? []
        : Array.from(sourceActive.keys()).filter((bridgeId) => targetActive.has(bridgeId)).sort(naturalCompare)
      const bridgeEvidence = evidenceMissing
        ? []
        : sharedActiveBridges.map((bridgeId) => sharedBridgeEvidence(bridgeId, sourceActive.get(bridgeId), targetActive.get(bridgeId)))
      const subnetMappings = evidenceMissing ? [] : buildSubnetMappings(sourceActive, targetActive)
      const remapSourceBridgeIds = new Set(subnetMappings.flatMap((mapping) => mapping.sourceBridgeIds))
      const missingSourceBridgeIds = evidenceMissing
        ? []
        : Array.from(sourceActive.keys())
          .filter((bridgeId) => !sharedActiveBridges.includes(bridgeId) && !remapSourceBridgeIds.has(bridgeId))
          .sort(naturalCompare)
      const verifiedExactBridgeIds = bridgeEvidence
        .filter((evidence) => evidence.subnetStatus === 'subnet_match')
        .map((evidence) => evidence.bridgeId)
      const unverifiedBridgeIds = bridgeEvidence
        .filter((evidence) => evidence.subnetStatus !== 'subnet_match' && evidence.subnetStatus !== 'subnet_mismatch')
        .map((evidence) => evidence.bridgeId)
      const mismatchedBridgeIds = bridgeEvidence
        .filter((evidence) => evidence.subnetStatus === 'subnet_mismatch')
        .map((evidence) => evidence.bridgeId)
      const status = evidenceMissing
        ? 'unknown'
        : mismatchedBridgeIds.length > 0 || missingSourceBridgeIds.length > 0
          ? 'blocked'
          : unverifiedBridgeIds.length > 0 || subnetMappings.length > 0
            ? 'needs_review'
            : verifiedExactBridgeIds.length > 0 && verifiedExactBridgeIds.length === sourceActive.size
              ? 'ready'
              : 'blocked'
      const reason = status === 'ready'
        ? 'cidr_verified_exact_bridge_match'
        : status === 'needs_review'
          ? unverifiedBridgeIds.length > 0
            ? 'bridge_name_cidr_unverified'
            : 'same_cidr_different_bridge_ids'
          : status === 'blocked'
            ? mismatchedBridgeIds.length > 0
              ? 'bridge_id_subnet_mismatch'
              : missingSourceBridgeIds.length > 0
                ? 'target_bridge_missing'
              : 'no_shared_active_bridge'
            : 'bridge_evidence_missing'
      pairs.push({
        id: `${source.nodeId}->${target.nodeId}`,
        sourceNodeId: source.nodeId,
        targetNodeId: target.nodeId,
        status,
        sharedActiveBridges,
        verifiedExactBridgeIds,
        unverifiedBridgeIds,
        mismatchedBridgeIds,
        missingSourceBridgeIds,
        bridgeEvidence,
        subnetMappings,
        reason,
      })
    })
  })
  return pairs
}

export function buildNetworkReadinessModel({
  nodes = [],
  vms = [],
  networks = [],
  evidence = {},
  errors = [],
} = {}) {
  const nodesAvailable = evidence.nodesAvailable !== false
  const vmsAvailable = evidence.vmsAvailable !== false
  const networksAvailable = evidence.networksAvailable !== false
  const nodeBridgeRows = bridgeRowsFromNodes(nodes)
  const bridgeEvidenceAvailable = networksAvailable || nodeBridgeRows.length > 0
  const normalizedBridges = [
    ...asArray(networks),
    ...nodeBridgeRows,
  ].map(normalizeBridge)

  const bridgeById = new Map()
  normalizedBridges.forEach((bridge) => {
    if (bridge.nodeId === 'unknown' || bridge.bridgeId === 'unknown') return
    bridgeById.set(bridge.id, mergeBridgeEvidence(bridgeById.get(bridge.id), bridge))
  })
  const bridges = Array.from(bridgeById.values())
    .sort((left, right) => naturalCompare(left.nodeId, right.nodeId) || naturalCompare(left.bridgeId, right.bridgeId))

  const nodeById = new Map()
  asArray(nodes).map(normalizeNode).forEach((node) => {
    if (node.nodeId !== 'unknown') nodeById.set(node.nodeId, node)
  })
  bridges.forEach((bridge) => {
    if (!nodeById.has(bridge.nodeId)) {
      nodeById.set(bridge.nodeId, {
        nodeId: bridge.nodeId,
        displayName: bridge.nodeId,
        status: 'unknown',
        raw: {},
      })
    }
  })
  const normalizedNodes = Array.from(nodeById.values()).sort((left, right) => naturalCompare(left.nodeId, right.nodeId))
  const normalizedVms = asArray(vms).map(normalizeVm).sort((left, right) => naturalCompare(left.nodeId, right.nodeId) || naturalCompare(left.name, right.name))
  const duplicateIpWarnings = buildDuplicateIpWarnings(normalizedVms)
  const duplicateIpsByVm = new Map()
  duplicateIpWarnings.forEach((warning) => {
    warning.vmIds.forEach((vmId) => {
      if (!duplicateIpsByVm.has(vmId)) duplicateIpsByVm.set(vmId, [])
      duplicateIpsByVm.get(vmId).push(warning.ipAddress)
    })
  })
  const vmsWithWarnings = normalizedVms.map((vm) => ({
    ...vm,
    duplicateIps: duplicateIpsByVm.get(vm.id) || [],
    warnings: [
      { code: 'vm_nic_bridge_evidence_missing' },
      ...(duplicateIpsByVm.get(vm.id) || []).map((ipAddress) => ({ code: 'duplicate_ip_observed', ipAddress })),
    ],
  }))
  const bridgeIds = Array.from(new Set(bridges.map((bridge) => bridge.bridgeId))).sort(naturalCompare)
  const bridgeMatrix = buildBridgeMatrix({ nodes: normalizedNodes, bridges, bridgeIds })
  const bridgeCoverageSummary = buildBridgeCoverageSummary({ nodes: normalizedNodes, bridges, bridgeIds })
  const subnetCoverageSummary = buildSubnetCoverageSummary({ nodes: normalizedNodes, bridges })
  const readinessEvidenceAvailable = nodesAvailable && bridgeEvidenceAvailable
  const nodePairReadiness = buildNodePairReadiness({ nodes: normalizedNodes, bridges, readinessEvidenceAvailable })

  return {
    nodes: normalizedNodes,
    vms: vmsWithWarnings,
    bridges,
    bridgeIds,
    bridgeMatrix,
    bridgeCoverageSummary,
    subnetCoverageSummary,
    nodePairReadiness,
    duplicateIpWarnings,
    evidence: {
      nodesAvailable,
      vmsAvailable,
      networksAvailable,
      bridgeEvidenceAvailable,
      readinessEvidenceAvailable,
      errors: asArray(errors),
    },
    summary: {
      nodes: normalizedNodes.length,
      bridges: bridges.length,
      activeBridges: bridges.filter((bridge) => bridge.active).length,
      inactiveBridges: bridges.filter((bridge) => !bridge.active).length,
      missingBridgeCells: bridgeMatrix.reduce((total, row) => total + row.bridges.filter((bridge) => bridge.status === 'missing').length, 0),
      readyPairs: nodePairReadiness.filter((pair) => pair.status === 'ready').length,
      needsReviewPairs: nodePairReadiness.filter((pair) => pair.status === 'needs_review').length,
      blockedPairs: nodePairReadiness.filter((pair) => pair.status === 'blocked').length,
      unknownPairs: nodePairReadiness.filter((pair) => pair.status === 'unknown').length,
      vms: vmsWithWarnings.length,
      duplicateIps: duplicateIpWarnings.length,
    },
  }
}

export function buildSourceMigrationReadinessView(model = {}, sourceNodeId) {
  const nodes = asArray(model.nodes)
    .filter((node) => node?.nodeId)
    .sort((left, right) => naturalCompare(left.nodeId, right.nodeId))
  const selectedSourceNodeId = nodes.some((node) => node.nodeId === sourceNodeId)
    ? sourceNodeId
    : nodes[0]?.nodeId || ''
  const sourceNode = nodes.find((node) => node.nodeId === selectedSourceNodeId) || null
  const readinessEvidenceAvailable = model.evidence?.readinessEvidenceAvailable !== false
  const sourceActiveBridges = activeBridgesByNode(model.bridges, selectedSourceNodeId)
  const pairByTarget = new Map(
    asArray(model.nodePairReadiness)
      .filter((pair) => pair?.sourceNodeId === selectedSourceNodeId && pair.targetNodeId !== selectedSourceNodeId)
      .map((pair) => [pair.targetNodeId, pair])
  )
  const targetRows = nodes
    .filter((node) => node.nodeId !== selectedSourceNodeId)
    .map((targetNode) => {
      const pair = pairByTarget.get(targetNode.nodeId)
      const networkComparisons = buildNetworkComparisons({
        sourceActiveBridges,
        targetBridges: bridgesByNode(model.bridges, targetNode.nodeId),
        readinessEvidenceAvailable,
      })
      const networkComparisonSummary = buildNetworkComparisonSummary(networkComparisons)
      const targetReadiness = buildTargetReadinessFromComparisons(networkComparisons, readinessEvidenceAvailable)
      return {
        id: pair?.id || `${selectedSourceNodeId}->${targetNode.nodeId}`,
        sourceNodeId: selectedSourceNodeId,
        targetNodeId: targetNode.nodeId,
        targetNode,
        status: targetReadiness.status,
        sharedActiveBridges: asArray(pair?.sharedActiveBridges),
        reason: targetReadiness.reason,
        bridgeEvidence: asArray(pair?.bridgeEvidence),
        subnetMappings: asArray(pair?.subnetMappings),
        networkComparisons,
        networkComparisonSummary,
        pair: pair || null,
      }
    })
  const sourceVms = asArray(model.vms).filter((vm) => vm?.nodeId === selectedSourceNodeId)
  const sourceVmIds = new Set(sourceVms.map((vm) => vm.id))
  const duplicateIpWarnings = asArray(model.duplicateIpWarnings).filter((warning) => (
    asArray(warning.vmIds).some((vmId) => sourceVmIds.has(vmId))
  ))

  return {
    selectedSourceNodeId,
    sourceNode,
    sourceBridges: sourceActiveBridges.map(bridgeEndpointEvidence),
    targetRows,
    sourceVms,
    duplicateIpWarnings,
    summary: {
      ready: targetRows.filter((row) => row.status === 'ready').length,
      needsReview: targetRows.filter((row) => row.status === 'needs_review').length,
      blocked: targetRows.filter((row) => row.status === 'blocked').length,
      unknown: targetRows.filter((row) => row.status === 'unknown').length,
      sourceBridges: sourceActiveBridges.length,
      sourceBridgeIds: bridgeIdsFrom(sourceActiveBridges),
      exactTargets: targetRows.filter((row) => row.networkComparisonSummary.exact > 0).length,
      remapCandidates: targetRows.filter((row) => row.networkComparisonSummary.remapCandidate > 0).length,
      exactMatches: targetRows.reduce((total, row) => total + row.networkComparisonSummary.exact, 0),
      remapCandidateMappings: targetRows.reduce((total, row) => total + row.networkComparisonSummary.remapCandidate, 0),
      missingMappings: targetRows.reduce((total, row) => total + row.networkComparisonSummary.missing, 0),
      inactiveMappings: targetRows.reduce((total, row) => total + row.networkComparisonSummary.inactive, 0),
      unknownMappings: targetRows.reduce((total, row) => total + row.networkComparisonSummary.unknown, 0),
      bridgeNameUnverifiedMappings: targetRows.reduce((total, row) => total + row.networkComparisonSummary.bridgeNameUnverified, 0),
      bridgeIdSubnetMismatchMappings: targetRows.reduce((total, row) => total + row.networkComparisonSummary.bridgeIdSubnetMismatch, 0),
      impactedVms: sourceVms.length,
      duplicateIpWarnings: duplicateIpWarnings.length,
    },
  }
}

export function statusTone(status) {
  if (status === 'ready' || status === 'active' || status === 'exact') return 'green'
  if (status === 'subnet_match' || status === 'gateway_match') return 'blue'
  if (status === 'blocked' || status === 'inactive' || status === 'subnet_mismatch' || status === 'gateway_mismatch' || status === 'bridge_id_subnet_mismatch') return 'red'
  if (status === 'needs_review' || status === 'missing' || status === 'unknown' || status === 'unverified' || status === 'partial' || status === 'remap_candidate' || status === 'bridge_name_unverified') return 'yellow'
  return 'slate'
}
