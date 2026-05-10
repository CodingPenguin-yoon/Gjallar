import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const {
  buildNetworkPolicyModel,
  formFromBridge,
  upsertNetworkPolicyBinding,
} = await import('../src/utils/networkPolicy.js')

const model = buildNetworkPolicyModel({
  iac_root: '/Users/yoon/mnt/nfs/IaC',
  policy_path: '/Users/yoon/mnt/nfs/IaC/manifests/networks/network-profiles.yaml',
  policy_relative_path: 'manifests/networks/network-profiles.yaml',
  policy_exists: true,
  policy: {
    networks: [
      {
        network_id: 'server-net',
        display_name: '서버망',
        nodes: [
          {
            node_id: 'yoonmanserver2',
            bridge_id: 'vmbr0',
            subnet: '192.168.2.0/24',
            gateway: '192.168.2.1',
            dns: ['192.168.2.1'],
            static_ip_ranges: [{ start: '192.168.2.140', end: '192.168.2.150' }],
          },
        ],
      },
    ],
  },
  bridges: [
    {
      node_id: 'yoonmanserver2',
      bridge_id: 'vmbr0',
      type: 'bridge',
      active: true,
      registered: true,
      policy: {
        network_id: 'server-net',
        display_name: '서버망',
        subnet: '192.168.2.0/24',
        gateway: '192.168.2.1',
        dns: ['192.168.2.1'],
        static_ip_ranges: [{ start: '192.168.2.140', end: '192.168.2.150' }],
      },
    },
    { node_id: 'yoonmanserver2', bridge_id: 'vmbr1', type: 'bridge', active: true, registered: false },
    { node_id: 'yoonserver3', bridge_id: 'vmbr0', type: 'bridge', active: true, registered: false },
  ],
})

assert.equal(model.summary.total, 3)
assert.equal(model.summary.registered, 1)
assert.equal(model.summary.unregistered, 2)
assert.deepEqual(model.nodes, ['yoonmanserver2', 'yoonserver3'])
assert.equal(model.bridgesByNode.yoonmanserver2.length, 2)
assert.equal(model.bridges[0].displayName, '서버망')
assert.deepEqual(model.bridges[0].staticIpRanges, [{ start: '192.168.2.140', end: '192.168.2.150' }])

const form = formFromBridge(model.bridges[1])
assert.equal(form.nodeId, 'yoonmanserver2')
assert.equal(form.bridgeId, 'vmbr1')
assert.equal(form.networkId, 'server-net')

const updated = upsertNetworkPolicyBinding(model.policy, {
  ...form,
  displayName: '내부망',
  networkId: 'internal-net',
  subnet: '10.10.0.0/24',
  gateway: '10.10.0.1',
  dns: '10.10.0.1, 1.1.1.1',
  staticIpRanges: [
    { start: '10.10.0.20', end: '10.10.0.30' },
    { start: '10.10.0.40', end: '10.10.0.45' },
  ],
})

assert.equal(updated.networks.length, 2)
assert.equal(updated.networks[1].network_id, 'internal-net')
assert.equal(updated.networks[1].nodes[0].bridge_id, 'vmbr1')
assert.deepEqual(updated.networks[1].nodes[0].dns, ['10.10.0.1', '1.1.1.1'])
assert.deepEqual(updated.networks[1].nodes[0].static_ip_ranges, [
  { start: '10.10.0.20', end: '10.10.0.30' },
  { start: '10.10.0.40', end: '10.10.0.45' },
])
assert.equal(updated.networks[1].nodes[0].ip_range, undefined)

const source = readFileSync(new URL('../src/components/NetworkPolicyScreen.jsx', import.meta.url), 'utf8')
assert.match(source, /네트워크 정책/)
assert.match(source, /vmbr 등록/)
assert.match(source, /IaC에 저장/)
assert.match(source, /고정 IP 범위/)
assert.match(source, /범위 추가/)
assert.match(source, /manifests\/networks\/network-profiles\.yaml|policyPath/)

console.log('networkPolicy RED contract exercised')
