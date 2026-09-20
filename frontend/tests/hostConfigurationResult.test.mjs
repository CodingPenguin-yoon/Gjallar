import assert from 'node:assert/strict'
import { assertStorageResult, assertBridgeResult, normalizeVlanIds, sameConfiguration } from '../src/features/hostConfiguration/result.js'
const target = {node_id:'node1', storage_id:'test-dir'}
const requested = {mode:'update', path:null, content:['images','iso'], enabled:true, idempotency_key:'test'}
const good = {operation:{operation_id:'test-operation', operation_type:'host_storage', target_type:'proxmox_storage', target_id:'storage:test-dir', status:'succeeded', details:{target, requested}}}
assert.deepEqual(assertStorageResult(good,'test-operation',target,requested), {...good.operation, verified:true})
assert.equal(sameConfiguration({a:1,b:[2,3]},{b:[2,3],a:1}),true)
for (const patch of [{operation_id:'other'}, {operation_type:'host_network'}, {target_id:'storage:other'}, {target_type:'proxmox_vm'},
  {details:{target:{...target,node_id:'other'},requested}}, {details:{target,requested:{...requested,content:['images']}}},
  {details:{target,requested:{...requested,enabled:false}}}, {details:{target,requested:{...requested,delete:'path'}}}]) {
  assert.throws(() => assertStorageResult({operation:{...good.operation,...patch}},'test-operation',target,requested))
}
console.log('host storage canonical result matches exact target and complete submitted payload')

const bridgeTarget = {node_id:'node1', bridge_id:'vmbr40'}
const bridgeRequested = {mode:'create', autostart:true, vlan_aware:true, vlan_ids:'10 20-30', acknowledge_node_reload:true}
const bridgeOperation = {operation_id:'bridge-op', operation_type:'host_network', target_type:'proxmox_network', target_id:'node:node1/bridge:vmbr40', status:'succeeded', details:{target:bridgeTarget, requested:bridgeRequested}}
assert.deepEqual(assertBridgeResult({operation:bridgeOperation}, 'bridge-op', bridgeTarget, bridgeRequested), {...bridgeOperation, verified:true})
for (const patch of [{operation_id:'other'}, {operation_type:'host_storage'}, {target_type:'proxmox_vm'}, {target_id:'node:node2/bridge:vmbr40'},
  {details:{target:{...bridgeTarget,node_id:'node2'},requested:bridgeRequested}},
  {details:{target:bridgeTarget,requested:{...bridgeRequested,vlan_ids:'1-4094'}}},
  {details:{target:bridgeTarget,requested:{...bridgeRequested,acknowledge_node_reload:false}}}]) {
  assert.throws(() => assertBridgeResult({operation:{...bridgeOperation,...patch}}, 'bridge-op', bridgeTarget, bridgeRequested))
}
assert.equal(normalizeVlanIds('20-30 10 11-19 25'), '10-30')
assert.equal(normalizeVlanIds('4094 1'), '1 4094')
for (const invalid of ['', '0', '4095', '20-10', '1,2', '10;id', '01']) assert.throws(() => normalizeVlanIds(invalid))
console.log('host bridge canonical identity, full request, and strict VLAN normalization verified')

// Canonical success still requires completed recovery/target-lock coordination.
for (const [check, operation, target, requested] of [
  [assertStorageResult, good.operation, good.operation.details.target, good.operation.details.requested],
  [assertBridgeResult, bridgeOperation, bridgeTarget, bridgeRequested],
]) {
  for (const status of ['succeeded', 'running', 'verifying', 'failed', 'unknown']) {
    for (const outerIncomplete of [false, true]) {
      for (const innerIncomplete of [false, true]) {
        const detail = {coordination_incomplete:outerIncomplete,
          operation:{...operation, status, coordination_incomplete:innerIncomplete}}
        const result = check(detail, operation.operation_id, target, requested)
        assert.equal(result.status, status)
        assert.equal(result.verified, status === 'succeeded' && !outerIncomplete && !innerIncomplete)
        assert.equal(result.details, operation.details)
      }
    }
  }
}
console.log('host completion requires canonical success and completed coordination at both response levels')
