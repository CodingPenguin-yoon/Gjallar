import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const {
  createOperationRequestGuard,
  GUIDED_QM_UNLOCK_OPERATION_TYPE,
  normalizeOperation,
  normalizeOperationDetail,
  OPERATION_POLL_MAX_ATTEMPTS,
  operationTypeLabel,
  operationStatusTone,
  shouldPollOperation,
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
assert.equal(operationTypeLabel('vm_create'), 'Create VM')
assert.equal(operationTypeLabel('vm_shutdown'), 'VM Shutdown')
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
  operation: {
    operation_id: 'guided-1',
    operation_type: GUIDED_QM_UNLOCK_OPERATION_TYPE,
    intent_digest: 'sha256:intent',
    last_event_checksum: 'sha256:event-2',
  },
  events: [
    {
      event_id: 'event-2',
      sequence: 2,
      event_type: 'verification_started',
      payload: { authority: 'proxmox_api' },
      previous_checksum: 'sha256:event-1',
      checksum: 'sha256:event-2',
    },
    {
      event_id: 'event-1',
      sequence: 1,
      event_type: 'operation_created',
      payload: { target: { vmid: 306 } },
      previous_checksum: '',
      checksum: 'sha256:event-1',
    },
  ],
  instruction_bundle: { command: { display: 'qm unlock 306' } },
  recovery: {
    recovery_kind: 'vm_start_observation',
    status: 'retry_wait',
    lease_owner: null,
    lease_generation: 3,
    attempt_count: 4,
    last_error_code: 'OPERATION_RECOVERY_OBSERVATION_FAILED',
  },
  target_lock: {
    owner_id: 'guided-1',
    durable: { operation_type: 'vm_start', status: 'active' },
  },
})
assert.deepEqual(detail.events.map((event) => event.sequence), [1, 2])
assert.equal(detail.operation.intentDigest, 'sha256:intent')
assert.equal(detail.operation.lastEventChecksum, 'sha256:event-2')
assert.deepEqual(detail.events[0].payload, { target: { vmid: 306 } })
assert.equal(detail.events[1].previousChecksum, 'sha256:event-1')
assert.equal(detail.events[1].checksum, 'sha256:event-2')
assert.equal(detail.instructionBundle.command.display, 'qm unlock 306')
assert.equal(detail.recovery.status, 'retry_wait')
assert.equal(detail.recovery.leaseGeneration, 3)
assert.equal(detail.targetLock.operationType, 'vm_start')
assert.equal(shouldPollOperation('running', 0), true)
assert.equal(shouldPollOperation('needs_reconciliation', 0), true)
assert.equal(shouldPollOperation('succeeded', 0), false)
assert.equal(shouldPollOperation('unknown', 0), false)
assert.equal(shouldPollOperation('running', OPERATION_POLL_MAX_ATTEMPTS), false)

const requestGuard = createOperationRequestGuard()
const olderRequest = requestGuard.next()
const newerRequest = requestGuard.next()
assert.equal(requestGuard.isCurrent(olderRequest), false, 'An out-of-order older response must not replace current evidence')
assert.equal(requestGuard.isCurrent(newerRequest), true)
requestGuard.invalidate()
assert.equal(requestGuard.isCurrent(newerRequest), false, 'Unmount or local mutation must invalidate in-flight reads')

const apiSource = readFileSync(new URL('../src/shared/api/apiV1.js', import.meta.url), 'utf8')
const planPage = readFileSync(new URL('../src/pages/operations/GuidedQmUnlockPage.jsx', import.meta.url), 'utf8')
const actionSource = readFileSync(new URL('../src/features/guided-qm-unlock/GuidedQmOperationActions.jsx', import.meta.url), 'utf8')
const detailPage = readFileSync(new URL('../src/pages/operations/OperationDetailPage.jsx', import.meta.url), 'utf8')
const listPage = readFileSync(new URL('../src/pages/operations/OperationsListPage.jsx', import.meta.url), 'utf8')
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
assert.match(detailPage, /Intent digest/)
assert.match(detailPage, /Last event checksum/)
assert.match(detailPage, /Event payload/)
assert.match(detailPage, /setTimeout/)
assert.match(detailPage, /clearTimeout/)
assert.match(detailPage, /requestGuardRef\.current\.isCurrent\(requestGeneration\)/)
assert.match(detailPage, /vmDetailPathFromTarget/)
assert.match(detailPage, /Recovery coordination/)
assert.doesNotMatch(detailPage, /leaseToken|lease_token/, 'Private recovery lease token must not be rendered')
for (const operationType of ['vm_create', 'vm_start', 'vm_shutdown', 'guided_qm_vm_unlock']) {
  assert.match(listPage, new RegExp(`value=["']${operationType}["']`), `Operations filter must expose ${operationType}`)
}
assert.match(inventory, /operations\/guided-qm\/vm-unlock\?node_id=/, 'Workload row must link to a typed Guided qm plan')

console.log('operations UI contract exercised')
