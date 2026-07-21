import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const {
  GUIDED_QM_UNLOCK_OPERATION_TYPE,
  normalizeOperation,
  normalizeOperationDetail,
  operationStatusTone,
} = await import('../src/entities/operation/model.js')
const {
  buildGuidedQmUnlockPayload,
  guidedQmActionState,
} = await import('../src/features/guided-qm-unlock/model.js')

const operation = normalizeOperation({
  operation_id: 'guided-1',
  operation_type: GUIDED_QM_UNLOCK_OPERATION_TYPE,
  execution_mode: 'guided_manual',
  status: 'awaiting_operator',
  target_type: 'proxmox_vm',
  target_id: 'vmid:306',
  plan_digest: 'sha256:plan',
  actor: { username: 'operator', role: 'operator' },
  details: { target: { node_id: 'node-a', vmid: 306 } },
})
assert.equal(operation.id, 'guided-1')
assert.equal(operation.actor.username, 'operator')
assert.deepEqual(guidedQmActionState(operation), { guided: true, canAttest: true, canVerify: false, lateAttestation: false })
assert.equal(guidedQmActionState({ ...operation, status: 'awaiting_verification' }).canVerify, true)
assert.equal(guidedQmActionState({
  ...operation,
  status: 'needs_reconciliation',
  details: { operator_attestation: { command_executed: true } },
}).canVerify, true)
assert.equal(guidedQmActionState({
  ...operation,
  expiresAt: '2026-07-21T00:00:00Z',
}, Date.parse('2026-07-21T00:00:01Z')).lateAttestation, true)
assert.match(operationStatusTone('needs_reconciliation'), /amber/)

assert.deepEqual(
  buildGuidedQmUnlockPayload({
    nodeId: ' node-a ',
    vmid: '306',
    idempotencyKey: 'guided-1',
    acknowledged: true,
  }),
  {
    node_id: 'node-a',
    vmid: 306,
    idempotency_key: 'guided-1',
    qm_unlock_risk_acknowledged: true,
  },
)
assert.throws(() => buildGuidedQmUnlockPayload({ nodeId: '', vmid: 306, idempotencyKey: 'x', acknowledged: true }), /Node ID/)
assert.throws(() => buildGuidedQmUnlockPayload({ nodeId: 'node-a', vmid: 0, idempotencyKey: 'x', acknowledged: true }), /VMID/)
assert.throws(() => buildGuidedQmUnlockPayload({ nodeId: 'node-a', vmid: 306, idempotencyKey: 'x', acknowledged: false }), /위험 확인/)

const detail = normalizeOperationDetail({
  operation: { operation_id: 'guided-1', operation_type: GUIDED_QM_UNLOCK_OPERATION_TYPE },
  events: [
    { event_id: 'event-2', sequence: 2, event_type: 'verification_started' },
    { event_id: 'event-1', sequence: 1, event_type: 'operation_created' },
  ],
  instruction_bundle: { command: { display: 'qm unlock 306' } },
})
assert.deepEqual(detail.events.map((event) => event.sequence), [1, 2])
assert.equal(detail.instructionBundle.command.display, 'qm unlock 306')

const apiSource = readFileSync(new URL('../src/shared/api/apiV1.js', import.meta.url), 'utf8')
const planPage = readFileSync(new URL('../src/pages/operations/GuidedQmUnlockPage.jsx', import.meta.url), 'utf8')
const actionSource = readFileSync(new URL('../src/features/guided-qm-unlock/GuidedQmOperationActions.jsx', import.meta.url), 'utf8')
const detailPage = readFileSync(new URL('../src/pages/operations/OperationDetailPage.jsx', import.meta.url), 'utf8')
const inventory = readFileSync(new URL('../src/features/workloads/inventory/WorkloadInventory.jsx', import.meta.url), 'utf8')

assert.match(apiSource, /listOperations/)
assert.match(apiSource, /planGuidedQmVmUnlock/)
assert.match(apiSource, /attestOperation/)
assert.match(apiSource, /verifyOperation/)
assert.match(planPage, /buildGuidedQmUnlockPayload/)
assert.doesNotMatch(planPage, /name=["']command|update\(['"]command|command:/, 'Browser must not submit an arbitrary command field')
assert.match(actionSource, /command_executed: true/)
assert.match(actionSource, /plan_digest: operation\.planDigest/)
assert.match(actionSource, /Gjallar는 이 명령을 실행하지 않습니다/)
assert.match(actionSource, /이 화면의 명령을 지금 실행하지 마세요/)
assert.match(detailPage, /Evidence timeline/)
assert.match(inventory, /operations\/guided-qm\/vm-unlock\?node_id=/, 'Workload row must link to a typed Guided qm plan')

console.log('operations UI contract exercised')
