export const OPERATION_STATUSES = Object.freeze([
  'draft',
  'planned',
  'awaiting_approval',
  'approved',
  'dispatching',
  'running',
  'awaiting_operator',
  'awaiting_verification',
  'verifying',
  'succeeded',
  'blocked',
  'rejected',
  'expired',
  'failed',
  'needs_reconciliation',
  'cancelled',
])

export const GUIDED_QM_UNLOCK_OPERATION_TYPE = 'guided_qm_vm_unlock'

export function normalizeOperation(value = {}) {
  const actor = value?.actor && typeof value.actor === 'object' ? value.actor : {}
  return {
    id: String(value?.operation_id || ''),
    type: String(value?.operation_type || 'unknown'),
    executionMode: String(value?.execution_mode || 'unknown'),
    status: String(value?.status || 'unknown'),
    targetType: String(value?.target_type || 'unknown'),
    targetId: String(value?.target_id || 'unknown'),
    idempotencyKey: String(value?.idempotency_key || ''),
    planDigest: String(value?.plan_digest || ''),
    stage: String(value?.current_stage || 'unknown'),
    actor: {
      userId: String(actor.user_id || ''),
      username: String(actor.username || 'system'),
      role: String(actor.role || ''),
    },
    details: value?.details && typeof value.details === 'object' ? value.details : {},
    expiresAt: value?.expires_at || null,
    version: Number(value?.version || 0),
    createdAt: value?.created_at || null,
    updatedAt: value?.updated_at || null,
  }
}

export function normalizeOperationDetail(value = {}) {
  const events = Array.isArray(value?.events) ? value.events : []
  return {
    operation: normalizeOperation(value?.operation),
    events: events
      .map((event) => ({
        id: String(event?.event_id || ''),
        sequence: Number(event?.sequence || 0),
        type: String(event?.event_type || 'unknown'),
        fromStatus: event?.from_status ? String(event.from_status) : null,
        toStatus: String(event?.to_status || 'unknown'),
        stage: String(event?.stage || 'unknown'),
        actor: event?.actor && typeof event.actor === 'object' ? event.actor : {},
        createdAt: event?.created_at || null,
      }))
      .sort((left, right) => left.sequence - right.sequence),
    instructionBundle: value?.instruction_bundle && typeof value.instruction_bundle === 'object'
      ? value.instruction_bundle
      : value?.operation?.details?.instruction_bundle || null,
    idempotentReplay: value?.idempotent_replay === true,
  }
}

export function operationTypeLabel(type) {
  const labels = {
    vm_start: 'VM Start',
    [GUIDED_QM_UNLOCK_OPERATION_TYPE]: 'Guided qm unlock',
  }
  return labels[type] || String(type || 'Unknown operation').replaceAll('_', ' ')
}

export function operationStatusLabel(status) {
  return String(status || 'unknown').replaceAll('_', ' ')
}

export function operationStatusTone(status) {
  if (status === 'succeeded') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (['failed', 'blocked', 'rejected'].includes(status)) return 'border-red-200 bg-red-50 text-red-700'
  if (['needs_reconciliation', 'expired'].includes(status)) return 'border-amber-200 bg-amber-50 text-amber-800'
  if (['running', 'dispatching', 'verifying'].includes(status)) return 'border-blue-200 bg-blue-50 text-blue-700'
  return 'border-slate-200 bg-slate-50 text-slate-700'
}

export function formatOperationTime(value) {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return String(value)
  return parsed.toLocaleString()
}
