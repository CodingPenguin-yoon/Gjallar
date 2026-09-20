import assert from 'node:assert/strict'
import { assertChangeResult } from '../src/features/workloads/detail/changeResult.js'
const expected = {type:'vm_backup',node:'node1',vmid:40000,requested:{idempotency_key:'backup-one',storage_id:'store1'}}
const good = {operation:{operation_id:'op-one',operation_type:'vm_backup',target_type:'proxmox_vm',target_id:'vmid:40000',
  details:{target:{node_id:'node1',vmid:40000},requested:{...expected.requested}}}}
assert.equal(assertChangeResult(good,'op-one',expected),good.operation)
for (const patch of [{operation_id:'other'},{operation_type:'vm_delete'},{target_id:'vmid:40001'},
  {details:{target:{node_id:'other'},requested:expected.requested}},
  {details:{target:{node_id:'node1'},requested:{...expected.requested,idempotency_key:'old-success'}}}]) {
  assert.throws(()=>assertChangeResult({operation:{...good.operation,...patch}},'op-one',expected))
}
assert.throws(()=>assertChangeResult({},'op-one'))
console.log('canonical mutation operation identity and submitted intent verified')

for (const type of ['vm_compute', 'vm_disk_resize', 'vm_network', 'vm_clone', 'vm_delete', 'vm_template', 'vm_image_build', 'vm_image_cleanup']) {
  const requested = {idempotency_key: 'current-request', expected_review_digest: 'current-review', confirmation: '40004/template', image_build_acknowledged: true}
  const expectedBuild = {type, node: 'node1', vmid: 40004, requested}
  const result = {operation: {operation_id: 'current-operation', operation_type: type, target_type: 'proxmox_vm', target_id: 'vmid:40004',
    details: {target: {node_id: 'node1', vmid: 40004}, requested}}}
  assert.equal(assertChangeResult(result, 'current-operation', expectedBuild), result.operation)
  for (const [key, value] of Object.entries(requested)) {
    const changed = {...result.operation, details: {...result.operation.details, requested: {...requested, [key]: typeof value === 'boolean' ? false : 'earlier-request'}}}
    assert.throws(() => assertChangeResult({operation: changed}, 'current-operation', expectedBuild))
  }
  assert.throws(() => assertChangeResult({operation: {...result.operation, details: {...result.operation.details, target: {node_id: 'node1', vmid: 40005}}}}, 'current-operation', expectedBuild))
}
