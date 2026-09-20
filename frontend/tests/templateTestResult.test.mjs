import assert from 'node:assert/strict'
import { assertAccessEvidence, assertRecordedAccess, assertTemplateTestReport } from '../src/features/workloads/templateTestResult.js'

const operationId = 'create-test'
const target = {node_id:'node1', vmid:40001, name:'test'}
const check = {name:'access', status:'passed', observed_at:'2026-09-19T14:00:00Z'}
const artifact = {artifact_id:'access-evidence', checksum:'sha256:fixture'}
const report = {operation_id:operationId, target, historical:true, live_checks_performed:false, checks:[{...check, artifact}]}
const response = {operation:{operation_id:operationId}, create_operation_id:operationId, operation_linked:true,
  target:{node_id:'node1', vmid:40001}, checks:[check], artifact}
assert.equal(assertTemplateTestReport(report,operationId),report)
assert.deepEqual(assertAccessEvidence(response,operationId,target,check),{artifact,check,replayed:false})
assert.equal(assertRecordedAccess(report,operationId,target,check,artifact),report)
for (const patch of [{operation_id:'other'}, {historical:false}, {live_checks_performed:true},
  {target:{...target,vmid:true}}, {target:{...target,vmid:99}}, {target:{...target,node_id:'../node1'}}]) {
  assert.throws(()=>assertTemplateTestReport({...report,...patch},operationId))
}
assert.throws(()=>assertRecordedAccess({...report,target:{...target,vmid:40002}},operationId,target,check,artifact))
for (const patch of [{operation:{operation_id:'other'}}, {create_operation_id:'other'}, {operation_linked:false},
  {target:{...target,vmid:40002}}, {checks:[{...check,status:'not_run'}]}, {checks:[{...check,observed_at:'old'}]},
  {checks:[check,check]}, {artifact:{artifact_id:'access-evidence'}}]) {
  assert.throws(()=>assertAccessEvidence({...response,...patch},operationId,target,check))
}
for (const checks of [[], [check], [{...check,status:'not_run',artifact}], [{...check,observed_at:'old',artifact}],
  [{...check,artifact:{...artifact,artifact_id:'other'}}], [{...check,artifact:{...artifact,checksum:'other'}}],
  [{...check,artifact},{...check,artifact}]]) {
  assert.throws(()=>assertRecordedAccess({...report,checks},operationId,target,check,artifact))
}
for (const status of ['failed','not_run','unavailable']) {
  const selected={...check,status}
  const saved={...report,checks:[{...selected,artifact}]}
  assert.deepEqual(assertAccessEvidence({...response,checks:[selected]},operationId,target,selected),{artifact,check:selected,replayed:false})
  assert.equal(assertRecordedAccess(saved,operationId,target,selected,artifact),saved)
}
console.log('template reports and recorded access bind exact create target, check, and artifact')

const originalCheck={...check,status:'failed',observed_at:'2026-09-18T00:00:00Z'}
const replay=assertAccessEvidence({...response,idempotent_replay:true,checks:[originalCheck]},operationId,target,check)
assert.deepEqual(replay,{artifact,check:originalCheck,replayed:true})
const originalReport={...report,checks:[{...originalCheck,artifact}]}
assert.equal(assertRecordedAccess(originalReport,operationId,target,replay.check,replay.artifact),originalReport)
assert.throws(()=>assertRecordedAccess(report,operationId,target,replay.check,replay.artifact))
