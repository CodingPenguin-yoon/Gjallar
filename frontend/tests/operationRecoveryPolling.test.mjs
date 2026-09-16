import assert from 'node:assert/strict'

const {
  buildRecoveryObservationPayload,
  normalizeOperationDetail,
  OPERATION_POLL_MAX_ATTEMPTS,
  recoveryObserveAction,
  shouldPollOperation,
} = await import('../src/entities/operation/model.js')

assert.equal(shouldPollOperation('running', 0), true)
assert.equal(shouldPollOperation('succeeded', 0), false)
assert.equal(shouldPollOperation('running', OPERATION_POLL_MAX_ATTEMPTS), false)

assert.equal(
  shouldPollOperation('succeeded', 0, {
    recovery: { status: 'leased' },
    targetLock: { status: 'active' },
  }),
  true,
  'A terminal Operation with incomplete recovery and an open lock must keep bounded polling',
)
assert.equal(
  shouldPollOperation('needs_reconciliation', 0, {
    recovery: { status: 'paused' },
    targetLock: { status: 'reconciliation_required' },
  }),
  false,
  'Paused recovery requires manual authority and must stop automatic polling',
)
assert.equal(
  shouldPollOperation('succeeded', 0, {
    recovery: { status: 'completed' },
    targetLock: { status: 'released' },
  }),
  false,
)
assert.equal(
  shouldPollOperation('succeeded', 0, {
    recovery: { status: 'completed', incomplete: true },
    targetLock: null,
  }),
  true,
  'The additive incomplete flag must keep terminal coordination visible while it closes',
)
assert.equal(
  shouldPollOperation('succeeded', 0, normalizeOperationDetail({
    operation: { status: 'succeeded' },
    target_lock: { owner_id: 'file-guard-owner' },
  })),
  true,
  'A compatibility file guard without durable status is still an open lock',
)
assert.equal(
  shouldPollOperation('succeeded', OPERATION_POLL_MAX_ATTEMPTS, {
    recovery: { status: 'leased' },
    targetLock: { status: 'active' },
  }),
  false,
  'Coordination-aware polling must remain bounded',
)

const detail = normalizeOperationDetail({
  operation: {
    operation_id: 'operation-recovery-1',
    operation_type: 'vm_start',
    status: 'needs_reconciliation',
    version: 7,
    last_event_checksum: 'sha256:event-7',
  },
  recovery: {
    recovery_kind: 'vm_start_observation',
    status: 'paused',
    details: {
      recovery_reason: 'task_state_mismatch',
      phase: 'post_check',
      task: { status: 'stopped', exitstatus: 'OK' },
      observed_after: { status: 'stopped' },
    },
    available_actions: [
      { action: 'observe', label: '다시 관찰', description: 'GET-only evidence observation' },
      { action: 'manual_review', enabled: false },
    ],
  },
  target_lock: {
    owner_id: 'operation-recovery-1',
    durable: { operation_type: 'vm_start', status: 'reconciliation_required' },
  },
})
assert.equal(detail.recovery.reason, 'task_state_mismatch')
assert.equal(detail.recovery.phase, 'post_check')
assert.equal(detail.recovery.manualActionRequired, true)
assert.equal(detail.recovery.latestObservation.phase, 'post_check')
assert.equal(detail.recovery.latestObservation.task.exitstatus, 'OK')
assert.equal(detail.recovery.availableActions[1].enabled, false)
assert.equal(recoveryObserveAction(detail).id, 'observe')

const preDispatchDetail = normalizeOperationDetail({
  operation: {
    operation_id: 'operation-pre-dispatch-1',
    operation_type: 'vm_start',
    status: 'succeeded',
    version: 2,
    last_event_checksum: 'sha256:event-2',
  },
  recovery: null,
  recovery_available_actions: ['observe'],
  coordination_incomplete: true,
})
assert.equal(preDispatchDetail.recovery, null, 'The compatibility no-item meaning must be preserved')
assert.equal(preDispatchDetail.coordinationIncomplete, true)
assert.equal(recoveryObserveAction(preDispatchDetail).id, 'observe')
assert.equal(shouldPollOperation('succeeded', 0, preDispatchDetail), true)

const payload = buildRecoveryObservationPayload(detail.operation)
assert.deepEqual(payload, buildRecoveryObservationPayload(detail.operation), 'The same evidence version must reuse one idempotency key')
assert.equal(payload.expected_version, 7)
assert.equal(payload.expected_checksum, 'sha256:event-7')
assert.match(payload.idempotency_key, /^recovery-observe:7:[a-f0-9]{16}$/)
assert.notEqual(
  payload.idempotency_key,
  buildRecoveryObservationPayload({ ...detail.operation, version: 8 }).idempotency_key,
)

console.log('operation recovery polling contract exercised')
