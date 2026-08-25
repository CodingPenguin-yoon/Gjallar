import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const {
  buildNetworkReadinessModel,
  buildSourceMigrationReadinessView,
  buildVmIpEvidenceDisplay,
  statusTone,
} = await import('../src/utils/networkReadiness.js')

const model = buildNetworkReadinessModel({
  nodes: [
    { node_id: 'yoonmanserver2', display_name: 'yoonmanserver2', status: 'online' },
    { node_id: 'yoonmanserver3', display_name: 'yoonmanserver3', status: 'online' },
    { node_id: 'yoonmanserver4', display_name: 'yoonmanserver4', status: 'online' },
  ],
  networks: [
    { node_id: 'yoonmanserver2', bridge_id: 'vmbr0', type: 'bridge', active: true },
    { node_id: 'yoonmanserver2', bridge_id: 'vmbr1', type: 'bridge', active: false },
    { node_id: 'yoonmanserver3', bridge_id: 'vmbr0', type: 'bridge', active: true },
    { node_id: 'yoonmanserver4', bridge_id: 'vmbr2', type: 'bridge', active: true },
  ],
  vms: [
    {
      vmid: 101,
      name: 'app-01',
      node_id: 'yoonmanserver2',
      status: 'running',
      ip_addresses: ['192.168.2.141'],
      guest_agent: { available: true, ip_addresses: ['192.168.2.141'] },
    },
    {
      vmid: 102,
      name: 'app-02',
      node_id: 'yoonmanserver3',
      status: 'running',
      ip_addresses: ['192.168.2.141'],
      guest_agent: { available: false, ip_addresses: [] },
    },
  ],
})

assert.equal(model.summary.nodes, 3)
assert.equal(model.summary.bridges, 4)
assert.equal(model.summary.activeBridges, 3)
assert.equal(model.summary.inactiveBridges, 1)
assert.deepEqual(model.bridgeIds, ['vmbr0', 'vmbr1', 'vmbr2'])
assert.equal(model.bridgeCoverageSummary.length, 3)
const vmbr0Coverage = model.bridgeCoverageSummary.find((bridge) => bridge.bridgeId === 'vmbr0')
assert.equal(vmbr0Coverage.presentCount, 2)
assert.equal(vmbr0Coverage.activeCount, 2)
assert.deepEqual(vmbr0Coverage.missingNodes, ['yoonmanserver4'])
assert.equal(vmbr0Coverage.configEvidenceStatus, 'unverified')

const node2Matrix = model.bridgeMatrix.find((row) => row.nodeId === 'yoonmanserver2')
const node3Matrix = model.bridgeMatrix.find((row) => row.nodeId === 'yoonmanserver3')
assert.equal(node2Matrix.bridges.find((bridge) => bridge.bridgeId === 'vmbr0').status, 'active')
assert.equal(node2Matrix.bridges.find((bridge) => bridge.bridgeId === 'vmbr1').status, 'inactive')
assert.equal(node3Matrix.bridges.find((bridge) => bridge.bridgeId === 'vmbr1').status, 'missing')

const needsReviewPair = model.nodePairReadiness.find((pair) => pair.id === 'yoonmanserver2->yoonmanserver3')
assert.equal(needsReviewPair.status, 'needs_review')
assert.deepEqual(needsReviewPair.sharedActiveBridges, ['vmbr0'])
assert.deepEqual(needsReviewPair.unverifiedBridgeIds, ['vmbr0'])
assert.equal(needsReviewPair.bridgeEvidence.length, 1)
assert.equal(needsReviewPair.bridgeEvidence[0].subnetStatus, 'unverified')
assert.equal(needsReviewPair.reason, 'bridge_name_cidr_unverified')

const blockedPair = model.nodePairReadiness.find((pair) => pair.id === 'yoonmanserver2->yoonmanserver4')
assert.equal(blockedPair.status, 'blocked')
assert.deepEqual(blockedPair.sharedActiveBridges, [])
assert.deepEqual(blockedPair.bridgeEvidence, [])
assert.equal(blockedPair.reason, 'target_bridge_missing')

const sourceView = buildSourceMigrationReadinessView(model, 'yoonmanserver2')
assert.equal(sourceView.selectedSourceNodeId, 'yoonmanserver2')
assert.equal(sourceView.sourceNode.nodeId, 'yoonmanserver2')
assert.deepEqual(sourceView.targetRows.map((row) => row.targetNodeId), ['yoonmanserver3', 'yoonmanserver4'])
const sourceViewNeedsReviewTarget = sourceView.targetRows.find((row) => row.targetNodeId === 'yoonmanserver3')
const sourceViewBlockedTarget = sourceView.targetRows.find((row) => row.targetNodeId === 'yoonmanserver4')
assert.equal(sourceViewNeedsReviewTarget.status, 'needs_review')
assert.equal(sourceViewNeedsReviewTarget.reason, 'bridge_name_cidr_unverified')
assert.deepEqual(sourceViewNeedsReviewTarget.sharedActiveBridges, ['vmbr0'])
assert.equal(sourceViewNeedsReviewTarget.bridgeEvidence[0].subnetStatus, 'unverified')
assert.deepEqual(sourceViewNeedsReviewTarget.networkComparisons.map((comparison) => ({
  sourceBridgeId: comparison.sourceBridgeId,
  status: comparison.status,
  targetBridgeIds: comparison.targetBridgeIds,
  reason: comparison.reason,
})), [
  {
    sourceBridgeId: 'vmbr0',
    status: 'bridge_name_unverified',
    targetBridgeIds: ['vmbr0'],
    reason: 'bridge_name_cidr_unverified',
  },
])
assert.equal(sourceViewBlockedTarget.status, 'blocked')
assert.deepEqual(sourceViewBlockedTarget.networkComparisons.map((comparison) => ({
  sourceBridgeId: comparison.sourceBridgeId,
  status: comparison.status,
  targetBridgeIds: comparison.targetBridgeIds,
  reason: comparison.reason,
})), [
  {
    sourceBridgeId: 'vmbr0',
    status: 'missing',
    targetBridgeIds: [],
    reason: 'source_bridge_cidr_unavailable',
  },
])
assert.ok(!sourceView.targetRows.some((row) => row.targetNodeId === 'yoonmanserver2'))
assert.deepEqual(sourceView.nodeVms.map((vm) => `${vm.nodeId}:${vm.name}`), [
  'yoonmanserver2:app-01',
  'yoonmanserver3:app-02',
])
assert.deepEqual(sourceView.nodeVmGroups.map((group) => ({
  nodeId: group.nodeId,
  displayName: group.displayName,
  vmNames: group.vms.map((vm) => vm.name),
})), [
  {
    nodeId: 'yoonmanserver2',
    displayName: 'yoonmanserver2',
    vmNames: ['app-01'],
  },
  {
    nodeId: 'yoonmanserver3',
    displayName: 'yoonmanserver3',
    vmNames: ['app-02'],
  },
])
assert.equal(sourceView.summary.ready, 0)
assert.equal(sourceView.summary.needsReview, 1)
assert.equal(sourceView.summary.blocked, 1)
assert.equal(sourceView.summary.unknown, 0)
assert.equal(sourceView.summary.sourceBridges, 1)
assert.deepEqual(sourceView.summary.sourceBridgeIds, ['vmbr0'])
assert.equal(sourceView.summary.exactTargets, 0)
assert.equal(sourceView.summary.remapCandidates, 0)
assert.equal(sourceView.summary.exactMatches, 0)
assert.equal(sourceView.summary.bridgeNameUnverifiedMappings, 1)
assert.equal(sourceView.summary.missingMappings, 1)
assert.equal(sourceView.summary.nodeVms, 2)
assert.equal(sourceView.summary.duplicateIpWarnings, 1)
assert.deepEqual(sourceView.duplicateIpWarnings.map((warning) => warning.ipAddress), ['192.168.2.141'])
assert.deepEqual(sourceView.duplicateIpWarnings[0].vmIds, ['101', '102'])

const invalidSourceView = buildSourceMigrationReadinessView(model, 'missing-node')
assert.equal(invalidSourceView.selectedSourceNodeId, 'yoonmanserver2')

const missingEvidenceModel = buildNetworkReadinessModel({
  nodes: [{ node_id: 'node-a' }, { node_id: 'node-b' }],
  evidence: { networksAvailable: false },
})
assert.equal(missingEvidenceModel.nodePairReadiness[0].status, 'unknown')
assert.equal(missingEvidenceModel.nodePairReadiness[0].reason, 'bridge_evidence_missing')
const missingEvidenceView = buildSourceMigrationReadinessView(missingEvidenceModel, 'node-a')
assert.equal(missingEvidenceView.targetRows.length, 1)
assert.equal(missingEvidenceView.targetRows[0].status, 'unknown')
assert.equal(missingEvidenceView.targetRows[0].reason, 'bridge_evidence_missing')

assert.deepEqual(model.vms[0].ipAddresses, ['192.168.2.141'])
assert.equal(model.vms[0].guestAgent.available, true)
assert.deepEqual(model.duplicateIpWarnings.map((warning) => warning.ipAddress), ['192.168.2.141'])
assert.deepEqual(model.vms[0].duplicateIps, ['192.168.2.141'])
assert.deepEqual(model.vms[0].warnings.map((warning) => warning.code), ['vm_nic_bridge_evidence_missing', 'duplicate_ip_observed'])
assert.equal(statusTone('ready'), 'green')
assert.equal(statusTone('needs_review'), 'yellow')
assert.equal(statusTone('blocked'), 'red')
assert.equal(statusTone('missing'), 'yellow')

const internalEvidenceModel = buildNetworkReadinessModel({
  vms: [
    {
      vmid: 201,
      name: 'container-host-a',
      node_id: 'node-a',
      ip_addresses: ['172.17.0.1'],
      ip_evidence: [
        {
          ip_address: '172.17.0.1',
          source: 'guest_agent',
          interface_name: 'docker0',
          interface_type: 'guest_internal',
          scope: 'internal',
          primary_candidate: false,
          duplicate_warning_eligible: false,
        },
      ],
    },
    {
      vmid: 202,
      name: 'container-host-b',
      node_id: 'node-b',
      ip_addresses: ['172.17.0.1'],
      ipEvidence: [
        {
          ipAddress: '172.17.0.1',
          source: 'guest_agent',
          interfaceName: 'br-46ea44f7',
          interfaceType: 'guest_internal',
          scope: 'internal',
          primaryCandidate: false,
          duplicateWarningEligible: false,
        },
      ],
    },
  ],
})
assert.deepEqual(internalEvidenceModel.duplicateIpWarnings, [])
assert.deepEqual(internalEvidenceModel.vms[0].ipAddresses, ['172.17.0.1'])
assert.deepEqual(internalEvidenceModel.vms[0].duplicateIps, [])
const internalOnlyIpDisplay = buildVmIpEvidenceDisplay(internalEvidenceModel.vms[0])
assert.equal(internalOnlyIpDisplay.representative.label, '172.17.0.1 (internal)')
assert.deepEqual(internalOnlyIpDisplay.hidden, [])

const mixedIpEvidenceModel = buildNetworkReadinessModel({
  vms: [
    {
      vmid: 203,
      name: 'mixed-ip-evidence',
      node_id: 'node-a',
      ip_evidence: [
        {
          ip_address: '172.17.0.1',
          source: 'guest_agent',
          interface_name: 'docker0',
          scope: 'internal',
          duplicate_warning_eligible: false,
        },
        {
          ip_address: '10.0.0.5',
          source: 'guest_agent',
          interface_name: 'eth1',
          scope: 'observed',
          duplicate_warning_eligible: true,
        },
        {
          ip_address: '192.168.2.141',
          source: 'config',
          interface_name: 'ipconfig0',
          scope: 'primary',
          primary_candidate: true,
          duplicate_warning_eligible: true,
        },
        {
          ip_address: '10.0.0.6',
          source: 'guest_agent',
          interface_name: 'eth2',
          scope: 'observed',
          duplicate_warning_eligible: true,
        },
      ],
    },
  ],
})
assert.deepEqual(mixedIpEvidenceModel.vms[0].ipAddresses, ['172.17.0.1', '10.0.0.5', '192.168.2.141', '10.0.0.6'])
assert.deepEqual(mixedIpEvidenceModel.vms[0].duplicateWarningIps, ['10.0.0.5', '192.168.2.141', '10.0.0.6'])
const mixedIpDisplay = buildVmIpEvidenceDisplay(mixedIpEvidenceModel.vms[0])
assert.equal(mixedIpDisplay.representative.label, '192.168.2.141')
assert.deepEqual(mixedIpDisplay.hidden.map((item) => item.label), [
  '10.0.0.5 (observed)',
  '10.0.0.6 (observed)',
  '172.17.0.1 (internal)',
])

const primaryEvidenceModel = buildNetworkReadinessModel({
  vms: [
    {
      vmid: 301,
      name: 'primary-a',
      node_id: 'node-a',
      ip_evidence: [
        {
          ip_address: '192.168.2.141',
          source: 'guest_agent',
          interface_name: 'eth0',
          scope: 'primary',
          primary_candidate: true,
          duplicate_warning_eligible: true,
        },
      ],
    },
    {
      vmid: 302,
      name: 'primary-b',
      node_id: 'node-b',
      ip_evidence: [
        {
          ip_address: '192.168.2.141',
          source: 'config',
          interface_name: 'ipconfig0',
          scope: 'primary',
          primary_candidate: true,
          duplicate_warning_eligible: true,
        },
      ],
    },
  ],
})
assert.deepEqual(primaryEvidenceModel.duplicateIpWarnings.map((warning) => warning.ipAddress), ['192.168.2.141'])
assert.deepEqual(primaryEvidenceModel.vms[0].duplicateIps, ['192.168.2.141'])
assert.deepEqual(primaryEvidenceModel.vms[1].duplicateIps, ['192.168.2.141'])

const nicBridgeEvidenceModel = buildNetworkReadinessModel({
  vms: [
    {
      vmid: 401,
      name: 'nic-evidence-a',
      node_id: 'node-a',
      ip_addresses: ['10.10.0.5'],
      nic_bridge_evidence: [
        {
          interface_name: 'net0',
          bridge_id: 'vmbr0',
          source: 'config',
          interface_type: 'proxmox_net_config',
          model: 'virtio',
          tag: '40',
          firewall: true,
          link_down: false,
        },
      ],
    },
    {
      vmid: 402,
      name: 'nic-evidence-b',
      node_id: 'node-b',
      ip_addresses: ['10.10.0.5'],
      nicBridgeEvidence: [
        {
          interfaceName: 'net1',
          bridgeId: 'vmbr0',
          source: 'config',
          interfaceType: 'proxmox_net_config',
        },
      ],
    },
  ],
})
assert.deepEqual(nicBridgeEvidenceModel.vms[0].nicBridgeEvidence[0], {
  interfaceName: 'net0',
  bridgeId: 'vmbr0',
  source: 'config',
  interfaceType: 'proxmox_net_config',
  model: 'virtio',
  tag: '40',
  firewall: true,
  linkDown: false,
  raw: nicBridgeEvidenceModel.vms[0].raw.nic_bridge_evidence[0],
})
assert.deepEqual(nicBridgeEvidenceModel.duplicateIpWarnings.map((warning) => warning.ipAddress), ['10.10.0.5'])
assert.deepEqual(nicBridgeEvidenceModel.vms[0].warnings.map((warning) => warning.code), ['duplicate_ip_observed'])
assert.deepEqual(nicBridgeEvidenceModel.vms[1].warnings.map((warning) => warning.code), ['duplicate_ip_observed'])
assert.ok(!nicBridgeEvidenceModel.vms[0].warnings.some((warning) => warning.code === 'vm_nic_bridge_evidence_missing'))

const activeNormalizationModel = buildNetworkReadinessModel({
  nodes: [
    { node_id: 'node-a' },
    { node_id: 'node-b' },
    { node_id: 'node-c' },
    { node_id: 'node-d' },
    { node_id: 'node-e' },
  ],
  networks: [
    { node_id: 'node-a', bridge_id: 'vmbr0', active: false },
    { node_id: 'node-b', bridge_id: 'vmbr0', active: 0 },
    { node_id: 'node-c', bridge_id: 'vmbr0', active: '0' },
    { node_id: 'node-d', bridge_id: 'vmbr0', active: 'false' },
    { node_id: 'node-e', bridge_id: 'vmbr0', active: 'inactive' },
  ],
})
assert.deepEqual(
  activeNormalizationModel.bridgeMatrix.map((row) => row.bridges.find((bridge) => bridge.bridgeId === 'vmbr0').status),
  ['inactive', 'inactive', 'inactive', 'inactive', 'inactive'],
)

const bridgeEvidenceModel = buildNetworkReadinessModel({
  nodes: [
    { node_id: 'node-a' },
    { node_id: 'node-b' },
    { node_id: 'node-c' },
  ],
  networks: [
    {
      node_id: 'node-a',
      bridge_id: 'vmbr0',
      active: true,
      address: '192.168.2.10',
      netmask: '255.255.255.0',
      prefix: 24,
      cidr: '192.168.2.0/24',
      gateway: '192.168.2.1',
      bridge_ports: 'eno1 eno2',
      vlan_aware: '1',
      mtu: '1500',
    },
    { node_id: 'node-b', bridge_id: 'vmbr0', active: true, cidr: '192.168.2.0/24', gateway: '192.168.2.1' },
    { node_id: 'node-c', bridge_id: 'vmbr0', active: true, cidr: '192.168.3.0/24', gateway: '192.168.3.1' },
    { node_id: 'node-a', bridge_id: 'vmbr1', active: true },
    { node_id: 'node-b', bridge_id: 'vmbr1', active: true },
    { node_id: 'node-a', bridge_id: 'vmbr3', active: true, cidr: '10.10.0.0/24', gateway: '10.10.0.1' },
    { node_id: 'node-b', bridge_id: 'vmbr3', active: true },
  ],
})
const normalizedVmbr0 = bridgeEvidenceModel.bridges.find((bridge) => bridge.id === 'node-a:vmbr0')
assert.equal(normalizedVmbr0.address, '192.168.2.10')
assert.equal(normalizedVmbr0.netmask, '255.255.255.0')
assert.equal(normalizedVmbr0.prefix, 24)
assert.deepEqual(normalizedVmbr0.bridgePorts, ['eno1', 'eno2'])
assert.equal(normalizedVmbr0.vlanAware, true)
assert.equal(normalizedVmbr0.mtu, 1500)
const vmbr0EvidenceSummary = bridgeEvidenceModel.bridgeCoverageSummary.find((bridge) => bridge.bridgeId === 'vmbr0')
assert.deepEqual(vmbr0EvidenceSummary.cidrs, ['192.168.2.0/24', '192.168.3.0/24'])
assert.deepEqual(vmbr0EvidenceSummary.gateways, ['192.168.2.1', '192.168.3.1'])
assert.equal(vmbr0EvidenceSummary.configEvidenceStatus, 'subnet_mismatch')
assert.equal(vmbr0EvidenceSummary.gatewayEvidenceStatus, 'gateway_mismatch')
const vmbr1EvidenceSummary = bridgeEvidenceModel.bridgeCoverageSummary.find((bridge) => bridge.bridgeId === 'vmbr1')
assert.equal(vmbr1EvidenceSummary.configEvidenceStatus, 'unverified')
assert.equal(vmbr1EvidenceSummary.gatewayEvidenceStatus, 'unverified')
const vmbr3EvidenceSummary = bridgeEvidenceModel.bridgeCoverageSummary.find((bridge) => bridge.bridgeId === 'vmbr3')
assert.equal(vmbr3EvidenceSummary.configEvidenceStatus, 'partial')
assert.equal(vmbr3EvidenceSummary.gatewayEvidenceStatus, 'partial')
const matchedEvidencePair = bridgeEvidenceModel.nodePairReadiness.find((pair) => pair.id === 'node-a->node-b')
assert.equal(matchedEvidencePair.status, 'needs_review')
assert.equal(matchedEvidencePair.reason, 'bridge_name_cidr_unverified')
const matchedVmbr0Evidence = matchedEvidencePair.bridgeEvidence.find((bridge) => bridge.bridgeId === 'vmbr0')
assert.equal(matchedVmbr0Evidence.subnetStatus, 'subnet_match')
assert.equal(matchedVmbr0Evidence.gatewayStatus, 'gateway_match')
assert.deepEqual(matchedVmbr0Evidence.cidrs, ['192.168.2.0/24'])
const mismatchedEvidencePair = bridgeEvidenceModel.nodePairReadiness.find((pair) => pair.id === 'node-a->node-c')
assert.equal(mismatchedEvidencePair.status, 'blocked')
assert.equal(mismatchedEvidencePair.reason, 'bridge_id_subnet_mismatch')
const mismatchedVmbr0Evidence = mismatchedEvidencePair.bridgeEvidence.find((bridge) => bridge.bridgeId === 'vmbr0')
assert.equal(mismatchedVmbr0Evidence.subnetStatus, 'subnet_mismatch')
assert.equal(mismatchedVmbr0Evidence.gatewayStatus, 'gateway_mismatch')
const subnet192Summary = bridgeEvidenceModel.subnetCoverageSummary.find((subnet) => subnet.cidr === '192.168.2.0/24')
assert.equal(subnet192Summary.presentCount, 2)
assert.equal(subnet192Summary.activeCount, 2)
assert.deepEqual(subnet192Summary.missingNodes, ['node-c'])
assert.deepEqual(subnet192Summary.gateways, ['192.168.2.1'])
assert.deepEqual(subnet192Summary.nodeMappings.find((mapping) => mapping.nodeId === 'node-a').bridgeIds, ['vmbr0'])
assert.deepEqual(subnet192Summary.nodeMappings.find((mapping) => mapping.nodeId === 'node-b').activeBridgeIds, ['vmbr0'])

const sameCidrDifferentBridgeModel = buildNetworkReadinessModel({
  nodes: [{ node_id: 'node-a' }, { node_id: 'node-b' }],
  networks: [
    { node_id: 'node-a', bridge_id: 'vmbr10', active: true, cidr: '172.16.0.0/24', gateway: '172.16.0.1' },
    { node_id: 'node-b', bridge_id: 'vmbr11', active: true, cidr: '172.16.0.0/24', gateway: '172.16.0.1' },
  ],
})
const vmbr10PartialCoverage = sameCidrDifferentBridgeModel.bridgeCoverageSummary.find((bridge) => bridge.bridgeId === 'vmbr10')
assert.equal(vmbr10PartialCoverage.presentCount, 1)
assert.equal(vmbr10PartialCoverage.missingCount, 1)
assert.equal(vmbr10PartialCoverage.configEvidenceStatus, 'partial')
assert.equal(vmbr10PartialCoverage.gatewayEvidenceStatus, 'partial')
assert.equal(sameCidrDifferentBridgeModel.subnetCoverageSummary.length, 1)
const sameCidrSubnet = sameCidrDifferentBridgeModel.subnetCoverageSummary[0]
assert.equal(sameCidrSubnet.cidr, '172.16.0.0/24')
assert.equal(sameCidrSubnet.presentCount, 2)
assert.equal(sameCidrSubnet.activeCount, 2)
assert.deepEqual(sameCidrSubnet.missingNodes, [])
assert.deepEqual(sameCidrSubnet.nodeMappings.find((mapping) => mapping.nodeId === 'node-a').bridgeIds, ['vmbr10'])
assert.deepEqual(sameCidrSubnet.nodeMappings.find((mapping) => mapping.nodeId === 'node-b').bridgeIds, ['vmbr11'])
const sameCidrDifferentBridgePair = sameCidrDifferentBridgeModel.nodePairReadiness.find((pair) => pair.id === 'node-a->node-b')
assert.equal(sameCidrDifferentBridgePair.status, 'needs_review')
assert.equal(sameCidrDifferentBridgePair.reason, 'same_cidr_different_bridge_ids')
assert.deepEqual(sameCidrDifferentBridgePair.sharedActiveBridges, [])
assert.deepEqual(sameCidrDifferentBridgePair.bridgeEvidence, [])
assert.deepEqual(sameCidrDifferentBridgePair.subnetMappings.map((mapping) => ({
  cidr: mapping.cidr,
  sourceBridgeIds: mapping.sourceBridgeIds,
  targetBridgeIds: mapping.targetBridgeIds,
  gateways: mapping.gateways,
})), [
  {
    cidr: '172.16.0.0/24',
    sourceBridgeIds: ['vmbr10'],
    targetBridgeIds: ['vmbr11'],
    gateways: ['172.16.0.1'],
  },
])
const sameCidrDifferentBridgeView = buildSourceMigrationReadinessView(sameCidrDifferentBridgeModel, 'node-a')
const sameCidrDifferentBridgeTarget = sameCidrDifferentBridgeView.targetRows.find((row) => row.targetNodeId === 'node-b')
assert.equal(sameCidrDifferentBridgeTarget.status, 'needs_review')
assert.equal(sameCidrDifferentBridgeTarget.reason, 'same_cidr_different_bridge_ids')
assert.deepEqual(sameCidrDifferentBridgeTarget.subnetMappings.map((mapping) => mapping.cidr), ['172.16.0.0/24'])
assert.deepEqual(sameCidrDifferentBridgeTarget.networkComparisons.map((comparison) => ({
  sourceBridgeId: comparison.sourceBridgeId,
  status: comparison.status,
  targetBridgeIds: comparison.targetBridgeIds,
  reason: comparison.reason,
})), [
  {
    sourceBridgeId: 'vmbr10',
    status: 'remap_candidate',
    targetBridgeIds: ['vmbr11'],
    reason: 'same_cidr_different_bridge_ids',
  },
])
assert.equal(sameCidrDifferentBridgeView.summary.ready, 0)
assert.equal(sameCidrDifferentBridgeView.summary.needsReview, 1)
assert.equal(sameCidrDifferentBridgeView.summary.blocked, 0)
assert.equal(sameCidrDifferentBridgeView.summary.exactTargets, 0)
assert.equal(sameCidrDifferentBridgeView.summary.remapCandidates, 1)
assert.equal(sameCidrDifferentBridgeView.summary.remapCandidateMappings, 1)

const requestedSameCidrRemapCaseModel = buildNetworkReadinessModel({
  nodes: [{ node_id: 'source-node' }, { node_id: 'target-node' }],
  networks: [
    { node_id: 'source-node', bridge_id: 'vmbr2', active: true, cidr: '10.100.100.0/24', gateway: '10.100.100.1' },
    { node_id: 'target-node', bridge_id: 'vmbr1', active: true, cidr: '10.100.100.0/24', gateway: '10.100.100.1' },
  ],
})
const requestedSameCidrRemapPair = requestedSameCidrRemapCaseModel.nodePairReadiness.find((pair) => pair.id === 'source-node->target-node')
assert.equal(requestedSameCidrRemapPair.status, 'needs_review')
assert.equal(requestedSameCidrRemapPair.reason, 'same_cidr_different_bridge_ids')
assert.deepEqual(requestedSameCidrRemapPair.sharedActiveBridges, [])
assert.deepEqual(requestedSameCidrRemapPair.subnetMappings.map((mapping) => ({
  cidr: mapping.cidr,
  sourceBridgeIds: mapping.sourceBridgeIds,
  targetBridgeIds: mapping.targetBridgeIds,
})), [
  {
    cidr: '10.100.100.0/24',
    sourceBridgeIds: ['vmbr2'],
    targetBridgeIds: ['vmbr1'],
  },
])
const requestedSameCidrRemapView = buildSourceMigrationReadinessView(requestedSameCidrRemapCaseModel, 'source-node')
const requestedSameCidrRemapTarget = requestedSameCidrRemapView.targetRows.find((row) => row.targetNodeId === 'target-node')
assert.equal(requestedSameCidrRemapTarget.status, 'needs_review')
assert.equal(requestedSameCidrRemapTarget.reason, 'same_cidr_different_bridge_ids')
assert.deepEqual(requestedSameCidrRemapTarget.networkComparisons.map((comparison) => ({
  sourceBridgeId: comparison.sourceBridgeId,
  sourceCidr: comparison.sourceCidr,
  status: comparison.status,
  targetBridgeIds: comparison.targetBridgeIds,
})), [
  {
    sourceBridgeId: 'vmbr2',
    sourceCidr: '10.100.100.0/24',
    status: 'remap_candidate',
    targetBridgeIds: ['vmbr1'],
  },
])

const requestedNameOnlyWithRemapCaseModel = buildNetworkReadinessModel({
  nodes: [{ node_id: 'source-node' }, { node_id: 'target-node' }],
  networks: [
    { node_id: 'source-node', bridge_id: 'vmbr1', active: true },
    { node_id: 'source-node', bridge_id: 'vmbr2', active: true, cidr: '10.100.100.0/24', gateway: '10.100.100.1' },
    { node_id: 'target-node', bridge_id: 'vmbr1', active: true, cidr: '10.100.100.0/24', gateway: '10.100.100.1' },
  ],
})
const requestedNameOnlyWithRemapPair = requestedNameOnlyWithRemapCaseModel.nodePairReadiness.find((pair) => pair.id === 'source-node->target-node')
assert.equal(requestedNameOnlyWithRemapPair.status, 'needs_review')
assert.equal(requestedNameOnlyWithRemapPair.reason, 'bridge_name_cidr_unverified')
assert.deepEqual(requestedNameOnlyWithRemapPair.sharedActiveBridges, ['vmbr1'])
assert.deepEqual(requestedNameOnlyWithRemapPair.unverifiedBridgeIds, ['vmbr1'])
assert.deepEqual(requestedNameOnlyWithRemapPair.subnetMappings.map((mapping) => ({
  cidr: mapping.cidr,
  sourceBridgeIds: mapping.sourceBridgeIds,
  targetBridgeIds: mapping.targetBridgeIds,
})), [
  {
    cidr: '10.100.100.0/24',
    sourceBridgeIds: ['vmbr2'],
    targetBridgeIds: ['vmbr1'],
  },
])
const requestedNameOnlyWithRemapView = buildSourceMigrationReadinessView(requestedNameOnlyWithRemapCaseModel, 'source-node')
const requestedNameOnlyWithRemapTarget = requestedNameOnlyWithRemapView.targetRows.find((row) => row.targetNodeId === 'target-node')
assert.equal(requestedNameOnlyWithRemapTarget.status, 'needs_review')
assert.equal(requestedNameOnlyWithRemapTarget.reason, 'bridge_name_cidr_unverified')
assert.deepEqual(requestedNameOnlyWithRemapTarget.networkComparisons.map((comparison) => ({
  sourceBridgeId: comparison.sourceBridgeId,
  status: comparison.status,
  targetBridgeIds: comparison.targetBridgeIds,
  reason: comparison.reason,
  subnetStatus: comparison.subnetStatus,
})), [
  {
    sourceBridgeId: 'vmbr1',
    status: 'bridge_name_unverified',
    targetBridgeIds: ['vmbr1'],
    reason: 'bridge_name_cidr_unverified',
    subnetStatus: 'partial',
  },
  {
    sourceBridgeId: 'vmbr2',
    status: 'remap_candidate',
    targetBridgeIds: ['vmbr1'],
    reason: 'same_cidr_different_bridge_ids',
    subnetStatus: 'subnet_match',
  },
])
assert.equal(requestedNameOnlyWithRemapView.summary.ready, 0)
assert.equal(requestedNameOnlyWithRemapView.summary.needsReview, 1)
assert.equal(requestedNameOnlyWithRemapView.summary.exactTargets, 0)
assert.equal(requestedNameOnlyWithRemapView.summary.remapCandidates, 1)
assert.equal(requestedNameOnlyWithRemapView.summary.exactMatches, 0)
assert.equal(requestedNameOnlyWithRemapView.summary.bridgeNameUnverifiedMappings, 1)
assert.equal(requestedNameOnlyWithRemapView.summary.remapCandidateMappings, 1)

const sameBridgeDifferentCidrModel = buildNetworkReadinessModel({
  nodes: [{ node_id: 'node-a' }, { node_id: 'node-b' }],
  networks: [
    { node_id: 'node-a', bridge_id: 'vmbr0', active: true, cidr: '10.10.0.0/24', gateway: '10.10.0.1' },
    { node_id: 'node-b', bridge_id: 'vmbr0', active: true, cidr: '10.20.0.0/24', gateway: '10.20.0.1' },
  ],
})
const sameBridgeDifferentCidrPair = sameBridgeDifferentCidrModel.nodePairReadiness.find((pair) => pair.id === 'node-a->node-b')
assert.equal(sameBridgeDifferentCidrPair.status, 'blocked')
assert.equal(sameBridgeDifferentCidrPair.reason, 'bridge_id_subnet_mismatch')
assert.deepEqual(sameBridgeDifferentCidrPair.mismatchedBridgeIds, ['vmbr0'])
const sameBridgeDifferentCidrView = buildSourceMigrationReadinessView(sameBridgeDifferentCidrModel, 'node-a')
const sameBridgeDifferentCidrTarget = sameBridgeDifferentCidrView.targetRows.find((row) => row.targetNodeId === 'node-b')
assert.equal(sameBridgeDifferentCidrTarget.status, 'blocked')
assert.deepEqual(sameBridgeDifferentCidrTarget.networkComparisons.map((comparison) => ({
  sourceBridgeId: comparison.sourceBridgeId,
  status: comparison.status,
  targetBridgeIds: comparison.targetBridgeIds,
  reason: comparison.reason,
  subnetStatus: comparison.subnetStatus,
})), [
  {
    sourceBridgeId: 'vmbr0',
    status: 'bridge_id_subnet_mismatch',
    targetBridgeIds: ['vmbr0'],
    reason: 'bridge_id_subnet_mismatch',
    subnetStatus: 'subnet_mismatch',
  },
])
assert.equal(sameBridgeDifferentCidrView.summary.ready, 0)
assert.equal(sameBridgeDifferentCidrView.summary.blocked, 1)
assert.equal(sameBridgeDifferentCidrView.summary.exactTargets, 0)
assert.equal(sameBridgeDifferentCidrView.summary.bridgeIdSubnetMismatchMappings, 1)

const exactWithMismatchPriorityModel = buildNetworkReadinessModel({
  nodes: [{ node_id: 'node-a' }, { node_id: 'node-b' }],
  networks: [
    { node_id: 'node-a', bridge_id: 'vmbr0', active: true, cidr: '10.0.0.0/24', gateway: '10.0.0.1' },
    { node_id: 'node-a', bridge_id: 'vmbr1', active: true, cidr: '10.1.0.0/24', gateway: '10.1.0.1' },
    { node_id: 'node-b', bridge_id: 'vmbr0', active: true, cidr: '10.0.0.0/24', gateway: '10.0.0.1' },
    { node_id: 'node-b', bridge_id: 'vmbr1', active: true, cidr: '10.2.0.0/24', gateway: '10.2.0.1' },
  ],
})
const exactWithMismatchPriorityPair = exactWithMismatchPriorityModel.nodePairReadiness.find((pair) => pair.id === 'node-a->node-b')
assert.equal(exactWithMismatchPriorityPair.status, 'blocked')
assert.equal(exactWithMismatchPriorityPair.reason, 'bridge_id_subnet_mismatch')
const exactWithMismatchPriorityView = buildSourceMigrationReadinessView(exactWithMismatchPriorityModel, 'node-a')
const exactWithMismatchPriorityTarget = exactWithMismatchPriorityView.targetRows.find((row) => row.targetNodeId === 'node-b')
assert.equal(exactWithMismatchPriorityTarget.status, 'blocked')
assert.equal(exactWithMismatchPriorityTarget.reason, 'bridge_id_subnet_mismatch')
assert.deepEqual(exactWithMismatchPriorityTarget.networkComparisons.map((comparison) => ({
  sourceBridgeId: comparison.sourceBridgeId,
  status: comparison.status,
  targetBridgeIds: comparison.targetBridgeIds,
})), [
  {
    sourceBridgeId: 'vmbr0',
    status: 'exact',
    targetBridgeIds: ['vmbr0'],
  },
  {
    sourceBridgeId: 'vmbr1',
    status: 'bridge_id_subnet_mismatch',
    targetBridgeIds: ['vmbr1'],
  },
])
assert.equal(exactWithMismatchPriorityView.summary.ready, 0)
assert.equal(exactWithMismatchPriorityView.summary.blocked, 1)
assert.equal(exactWithMismatchPriorityView.summary.bridgeIdSubnetMismatchMappings, 1)

const bothCidrMissingNameOnlyModel = buildNetworkReadinessModel({
  nodes: [{ node_id: 'node-a' }, { node_id: 'node-b' }],
  networks: [
    { node_id: 'node-a', bridge_id: 'vmbr0', active: true },
    { node_id: 'node-b', bridge_id: 'vmbr0', active: true },
  ],
})
const bothCidrMissingNameOnlyPair = bothCidrMissingNameOnlyModel.nodePairReadiness.find((pair) => pair.id === 'node-a->node-b')
assert.equal(bothCidrMissingNameOnlyPair.status, 'needs_review')
assert.equal(bothCidrMissingNameOnlyPair.reason, 'bridge_name_cidr_unverified')
const bothCidrMissingNameOnlyView = buildSourceMigrationReadinessView(bothCidrMissingNameOnlyModel, 'node-a')
const bothCidrMissingNameOnlyTarget = bothCidrMissingNameOnlyView.targetRows.find((row) => row.targetNodeId === 'node-b')
assert.equal(bothCidrMissingNameOnlyTarget.status, 'needs_review')
assert.deepEqual(bothCidrMissingNameOnlyTarget.networkComparisons.map((comparison) => ({
  sourceBridgeId: comparison.sourceBridgeId,
  status: comparison.status,
  targetBridgeIds: comparison.targetBridgeIds,
  subnetStatus: comparison.subnetStatus,
})), [
  {
    sourceBridgeId: 'vmbr0',
    status: 'bridge_name_unverified',
    targetBridgeIds: ['vmbr0'],
    subnetStatus: 'unverified',
  },
])

const sameCidrSameBridgeSetModel = buildNetworkReadinessModel({
  nodes: [{ node_id: 'node-a' }, { node_id: 'node-b' }],
  networks: [
    { node_id: 'node-a', bridge_id: 'vmbr0', active: true, cidr: '10.30.0.0/24', gateway: '10.30.0.1' },
    { node_id: 'node-a', bridge_id: 'vmbr1', active: true, cidr: '10.30.0.0/24', gateway: '10.30.0.1' },
    { node_id: 'node-b', bridge_id: 'vmbr1', active: true, cidr: '10.30.0.0/24', gateway: '10.30.0.1' },
    { node_id: 'node-b', bridge_id: 'vmbr0', active: true, cidr: '10.30.0.0/24', gateway: '10.30.0.1' },
  ],
})
const sameCidrSameBridgeSetPair = sameCidrSameBridgeSetModel.nodePairReadiness.find((pair) => pair.id === 'node-a->node-b')
assert.equal(sameCidrSameBridgeSetPair.status, 'ready')
assert.deepEqual(sameCidrSameBridgeSetPair.sharedActiveBridges, ['vmbr0', 'vmbr1'])
assert.deepEqual(sameCidrSameBridgeSetPair.subnetMappings, [])
const sameCidrSameBridgeSetView = buildSourceMigrationReadinessView(sameCidrSameBridgeSetModel, 'node-a')
const sameCidrSameBridgeSetTarget = sameCidrSameBridgeSetView.targetRows.find((row) => row.targetNodeId === 'node-b')
assert.equal(sameCidrSameBridgeSetTarget.status, 'ready')
assert.equal(sameCidrSameBridgeSetTarget.reason, 'cidr_verified_exact_bridge_match')
assert.deepEqual(sameCidrSameBridgeSetTarget.networkComparisons.map((comparison) => ({
  sourceBridgeId: comparison.sourceBridgeId,
  status: comparison.status,
  targetBridgeIds: comparison.targetBridgeIds,
})), [
  {
    sourceBridgeId: 'vmbr0',
    status: 'exact',
    targetBridgeIds: ['vmbr0'],
  },
  {
    sourceBridgeId: 'vmbr1',
    status: 'exact',
    targetBridgeIds: ['vmbr1'],
  },
])

const richerNetworksMergeModel = buildNetworkReadinessModel({
  nodes: [
    {
      node_id: 'node-a',
      networks: [
        { bridge_id: 'vmbr0' },
      ],
    },
  ],
  networks: [
    { node_id: 'node-a', bridge_id: 'vmbr0', active: false, cidr: '10.10.10.0/24', gateway: '10.10.10.1' },
  ],
})
const mergedBridge = richerNetworksMergeModel.bridges.find((bridge) => bridge.id === 'node-a:vmbr0')
assert.equal(mergedBridge.active, false)
assert.equal(mergedBridge.cidr, '10.10.10.0/24')
assert.equal(mergedBridge.gateway, '10.10.10.1')
assert.equal(richerNetworksMergeModel.bridgeMatrix[0].bridges[0].status, 'inactive')
assert.deepEqual(richerNetworksMergeModel.subnetCoverageSummary[0].gateways, ['10.10.10.1'])

const nodesUnavailableWithNetworksModel = buildNetworkReadinessModel({
  networks: [
    { node_id: 'node-a', bridge_id: 'vmbr0', active: true, cidr: '10.20.0.0/24' },
    { node_id: 'node-b', bridge_id: 'vmbr0', active: true, cidr: '10.20.0.0/24' },
  ],
  evidence: {
    nodesAvailable: false,
    networksAvailable: true,
  },
})
const nodesUnavailablePair = nodesUnavailableWithNetworksModel.nodePairReadiness.find((pair) => pair.id === 'node-a->node-b')
assert.equal(nodesUnavailablePair.status, 'unknown')
assert.equal(nodesUnavailablePair.reason, 'bridge_evidence_missing')
assert.deepEqual(nodesUnavailablePair.sharedActiveBridges, [])
assert.deepEqual(nodesUnavailablePair.subnetMappings, [])
const nodesUnavailableView = buildSourceMigrationReadinessView(nodesUnavailableWithNetworksModel, 'node-a')
assert.equal(nodesUnavailableView.targetRows.find((row) => row.targetNodeId === 'node-b').status, 'unknown')
assert.deepEqual(nodesUnavailableView.targetRows.find((row) => row.targetNodeId === 'node-b').networkComparisons.map((comparison) => ({
  sourceBridgeId: comparison.sourceBridgeId,
  status: comparison.status,
  reason: comparison.reason,
})), [
  {
    sourceBridgeId: 'vmbr0',
    status: 'unknown',
    reason: 'bridge_evidence_missing',
  },
])

const screenSource = readFileSync(new URL('../src/components/NetworkReadinessScreen.jsx', import.meta.url), 'utf8')
assert.match(screenSource, /네트워크 준비도/)
assert.match(screenSource, /마이그레이션 전 네트워크 근거/)
assert.match(screenSource, /Proxmox 네트워크 설정을 변경/)
assert.match(screenSource, /migration 실행 권한/)
assert.match(screenSource, /마이그레이션 원본/)
assert.match(screenSource, /대상 네트워크 비교/)
assert.match(screenSource, /대상 노드/)
assert.match(screenSource, /결과/)
assert.match(screenSource, /네트워크 매핑/)
assert.match(screenSource, /준비됨/)
assert.match(screenSource, /검토 필요/)
assert.match(screenSource, /차단/)
assert.match(screenSource, /정보 부족/)
assert.match(screenSource, /일치/)
assert.match(screenSource, /이름만 같음/)
assert.match(screenSource, /CIDR 불일치/)
assert.match(screenSource, /remap 필요/)
assert.match(screenSource, /매핑 없음/)
assert.match(screenSource, /비활성/)
assert.match(screenSource, /CIDR 근거 부족/)
assert.match(screenSource, /같은 CIDR/)
assert.match(screenSource, /bridge 이름 다름/)
assert.doesNotMatch(screenSource, /Bridge readiness/)
assert.doesNotMatch(screenSource, /Source-to-target network map/)
assert.doesNotMatch(screenSource, /<th className="px-4 py-3">Evidence<\/th>/)
assert.doesNotMatch(screenSource, /Exact bridge match/)
assert.doesNotMatch(screenSource, /Bridge name only/)
assert.doesNotMatch(screenSource, /Subnet mismatch/)
assert.doesNotMatch(screenSource, /Needs review/)
assert.doesNotMatch(screenSource, /CIDR remap candidate/)
assert.doesNotMatch(screenSource, /Same CIDR, different bridge IDs/)
assert.doesNotMatch(screenSource, /Subnet mapping by node/)
assert.doesNotMatch(screenSource, /Observed subnet mapping/)
assert.doesNotMatch(screenSource, /Bridge ID matrix/)
assert.doesNotMatch(screenSource, /Shared active bridges/)
assert.match(screenSource, /노드별 VM/)
assert.doesNotMatch(screenSource, /영향 VM/)
assert.match(screenSource, /NodeVmTable/)
assert.match(screenSource, /view\.nodeVms/)
assert.match(screenSource, /view\.nodeVmGroups/)
assert.match(screenSource, /colSpan=\{6\}/)
assert.match(screenSource, /group\.displayName/)
assert.match(screenSource, /<th className="px-4 py-3 whitespace-nowrap">연결 vmbr<\/th>/)
assert.doesNotMatch(screenSource, /<th className="px-4 py-3">준비도<\/th>/)
assert.match(screenSource, /VmBridgeCell/)
assert.match(screenSource, /vm\.nicBridgeEvidence/)
assert.match(screenSource, />X<\/span>/)
assert.match(screenSource, /<th className="px-4 py-3 whitespace-nowrap">관찰 IP<\/th>/)
assert.match(screenSource, /buildVmIpEvidenceDisplay/)
assert.match(screenSource, /aria-expanded=\{expanded\}/)
assert.match(screenSource, /aria-label=\{toggleLabel\}/)
assert.match(screenSource, /\+\{hiddenCount\}/)
assert.match(screenSource, /vm_nic_bridge_evidence_missing/)
assert.match(screenSource, /vm\.warnings/)
assert.match(screenSource, /warningLabel/)
assert.match(screenSource, /apiV1Client\.listNodes\(\)/)
assert.match(screenSource, /apiV1Client\.listVms\(\)/)
assert.match(screenSource, /apiV1Client\.listNetworks\(\)/)
assert.match(screenSource, /buildSourceMigrationReadinessView/)
assert.doesNotMatch(screenSource, /Source-target pre-check evidence/)
assert.doesNotMatch(screenSource, /VM-level network evidence/)
assert.doesNotMatch(screenSource, /NodePairReadiness/)
assert.doesNotMatch(screenSource, /BridgeCoverageSummary/)
assert.ok(!screenSource.includes(['IaC', '에 저장'].join('')))
assert.ok(!screenSource.includes(['저장', ' 위치'].join('')))
assert.doesNotMatch(screenSource, /network-profiles\.yaml/)
assert.doesNotMatch(screenSource, /same network confirmed/i)
assert.ok(!screenSource.includes(['getNetwork', 'Policy'].join('')))
assert.ok(!screenSource.includes(['saveNetwork', 'Policy'].join('')))

const clientSource = readFileSync(new URL('../src/services/apiV1.js', import.meta.url), 'utf8')
assert.ok(!clientSource.includes(['network', 'Policy'].join('')))
assert.ok(!clientSource.includes(['getNetwork', 'Policy'].join('')))
assert.ok(!clientSource.includes(['saveNetwork', 'Policy'].join('')))
assert.ok(!clientSource.includes(['networks', 'policy'].join('/')))

console.log('network readiness contract exercised')
