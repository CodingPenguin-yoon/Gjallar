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

export const TERMINAL_OPERATION_STATUSES = Object.freeze([
  'succeeded',
  'blocked',
  'rejected',
  'expired',
  'failed',
  'cancelled',
])

export const OPERATION_POLL_INTERVAL_MS = 5000
export const OPERATION_POLL_MAX_ATTEMPTS = 60
export const OPEN_TARGET_LOCK_STATUSES = Object.freeze(['active', 'stale', 'reconciliation_required'])

export const GUIDED_QM_UNLOCK_OPERATION_TYPE = 'guided_qm_vm_unlock'

const RECOVERY_OBSERVE_ACTIONS = new Set(['observe', 'reobserve', 're_observe', 'observe_recovery', 'recovery_observe'])

function asRecord(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function normalizeRecoveryActions(value) {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => {
      if (typeof item === 'string') {
        const id = item.trim()
        return id ? { id, label: id.replaceAll('_', ' '), description: '', enabled: true } : null
      }
      const action = asRecord(item)
      const id = String(action.id || action.action || action.type || '').trim()
      if (!id) return null
      return {
        id,
        label: String(action.label || id.replaceAll('_', ' ')),
        description: String(action.description || action.reason || ''),
        enabled: action.enabled !== false && action.available !== false,
      }
    })
    .filter(Boolean)
}

function latestRecoveryObservation(recovery, details) {
  const explicit = asRecord(recovery.latest_observation)
  if (Object.keys(explicit).length > 0) return explicit
  const fromDetails = asRecord(details.latest_observation)
  if (Object.keys(fromDetails).length > 0) return fromDetails
  const observation = {}
  if (details.phase) observation.phase = details.phase
  if (details.last_task_status) observation.last_task_status = details.last_task_status
  if (Object.keys(asRecord(details.task)).length > 0) observation.task = asRecord(details.task)
  if (Object.keys(asRecord(details.observed_after)).length > 0) observation.observed_after = asRecord(details.observed_after)
  return observation
}

function stableRecoveryObservationKey(operation) {
  const source = `${operation.id}|${operation.version}|${operation.lastEventChecksum}`
  let hash = 14695981039346656037n
  for (let index = 0; index < source.length; index += 1) {
    hash ^= BigInt(source.charCodeAt(index))
    hash = BigInt.asUintN(64, hash * 1099511628211n)
  }
  return `recovery-observe:${operation.version}:${hash.toString(16).padStart(16, '0')}`
}

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
    intentDigest: String(value?.intent_digest || ''),
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
    lastEventChecksum: String(value?.last_event_checksum || ''),
    createdAt: value?.created_at || null,
    updatedAt: value?.updated_at || null,
  }
}

export function normalizeOperationDetail(value = {}) {
  const events = Array.isArray(value?.events) ? value.events : []
  const recovery = value?.recovery && typeof value.recovery === 'object' ? value.recovery : null
  const targetLock = value?.target_lock && typeof value.target_lock === 'object' ? value.target_lock : null
  const recoveryDetails = asRecord(recovery?.details)
  const instructionState = asRecord(value?.instruction_state)
  const createReadiness = asRecord(value?.create_readiness)
  const readiness = asRecord(createReadiness.readiness)
  const readinessChecks = asRecord(readiness.checks)
  const readinessArtifact = asRecord(createReadiness.artifact)
  const readinessWorkload = asRecord(createReadiness.workload)
  const readinessTarget = asRecord(createReadiness.workload_target)
  const recoveryAvailableActions = normalizeRecoveryActions(value?.recovery_available_actions)
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
        payload: event?.payload && typeof event.payload === 'object' && !Array.isArray(event.payload)
          ? event.payload
          : {},
        previousChecksum: String(event?.previous_checksum || ''),
        checksum: String(event?.checksum || ''),
        createdAt: event?.created_at || null,
      }))
      .sort((left, right) => left.sequence - right.sequence),
    instructionBundle: value?.instruction_bundle && typeof value.instruction_bundle === 'object'
      ? value.instruction_bundle
      : value?.operation?.details?.instruction_bundle || null,
    instructionState: Object.keys(instructionState).length > 0
      ? {
          active: instructionState.active === true,
          historical: instructionState.historical === true,
          doNotExecute: instructionState.do_not_execute === true,
          reason: String(instructionState.reason || ''),
        }
      : null,
    createReadiness: Object.keys(createReadiness).length > 0
      ? {
          status: String(createReadiness.status || ''),
          exists: createReadiness.exists === true,
          fingerprintHash: String(createReadiness.fingerprint_hash || ''),
          readiness: {
            postCheckStatus: String(readiness.post_check_status || ''),
            message: String(readiness.message || ''),
            powerPolicy: String(readiness.power_policy || ''),
            guestAgentAvailable: readiness.guest_agent_available === true,
            cloudInitCompleted: readiness.cloud_init_completed === true,
            bootVerificationSuccess: readiness.boot_verification_success === true,
            checks: Object.fromEntries(
              Object.entries(readinessChecks).map(([key, enabled]) => [String(key), enabled === true]),
            ),
          },
          artifact: {
            id: String(readinessArtifact.artifact_id || ''),
            checksum: String(readinessArtifact.checksum || ''),
          },
          workload: {
            id: String(readinessWorkload.vm_instance_id || ''),
            nodeId: String(readinessWorkload.node_id || ''),
            vmid: Number(readinessWorkload.vmid || 0),
            status: String(readinessWorkload.status || ''),
          },
          workloadTarget: {
            type: String(readinessTarget.target_type || ''),
            id: String(readinessTarget.target_id || ''),
          },
        }
      : null,
    idempotentReplay: value?.idempotent_replay === true,
    coordinationIncomplete: value?.coordination_incomplete === true,
    recoveryAvailableActions,
    recovery: recovery
      ? {
          kind: String(recovery.recovery_kind || 'unknown'),
          status: String(recovery.status || 'unknown'),
          availableAt: recovery.available_at || null,
          leaseOwner: recovery.lease_owner ? String(recovery.lease_owner) : null,
          leaseGeneration: Number(recovery.lease_generation || 0),
          leaseExpiresAt: recovery.lease_expires_at || null,
          attemptCount: Number(recovery.attempt_count || 0),
          lastErrorCode: recovery.last_error_code ? String(recovery.last_error_code) : null,
          phase: String(recovery.phase || recoveryDetails.phase || ''),
          incomplete: recovery.incomplete === true,
          manualActionRequired: recovery.manual_action_required === true || recovery.status === 'paused',
          reason: String(
            recovery.reason
              || recoveryDetails.reason
              || recoveryDetails.recovery_reason
              || recoveryDetails.reconciliation_reason
              || recovery.last_error_code
              || '',
          ),
          details: recoveryDetails,
          latestObservation: latestRecoveryObservation(recovery, recoveryDetails),
          availableActions: normalizeRecoveryActions(recovery.available_actions),
          completedAt: recovery.completed_at || null,
        }
      : null,
    targetLock: targetLock
      ? {
          status: String(targetLock?.durable?.status || targetLock.status || 'active'),
          ownerId: String(targetLock.owner_id || targetLock?.durable?.owner_id || ''),
          operationType: String(targetLock?.durable?.operation_type || 'unknown'),
          targetType: String(targetLock.target_type || ''),
          targetId: String(targetLock.target_id || ''),
          lockId: String(targetLock?.durable?.operation_lock_id || ''),
          clusterId: String(targetLock?.durable?.cluster_id || ''),
          acquiredAt: targetLock.acquired_at || targetLock?.durable?.created_at || null,
        }
      : null,
  }
}

export function isTargetLockOpen(targetLock) {
  return OPEN_TARGET_LOCK_STATUSES.includes(String(targetLock?.status || ''))
}

export function isRecoveryIncomplete(recovery) {
  const status = String(recovery?.status || '')
  return Boolean(recovery)
    && (recovery.incomplete === true || !['completed', 'paused'].includes(status))
}

export function shouldPollOperation(status, attemptCount = 0, coordination = {}) {
  const normalizedAttempts = Number.isFinite(Number(attemptCount)) ? Number(attemptCount) : 0
  if (!OPERATION_STATUSES.includes(status) || normalizedAttempts >= OPERATION_POLL_MAX_ATTEMPTS) return false
  if (coordination?.recovery?.status === 'paused' || coordination?.recovery?.manualActionRequired === true) return false
  if (!TERMINAL_OPERATION_STATUSES.includes(status)) return true
  return coordination?.coordinationIncomplete === true
    || isRecoveryIncomplete(coordination?.recovery)
    || isTargetLockOpen(coordination?.targetLock)
}

export function recoveryObserveAction(detail = {}) {
  const actions = detail?.recovery?.availableActions?.length > 0
    ? detail.recovery.availableActions
    : detail?.recoveryAvailableActions || []
  return actions.find(
    (action) => action.enabled && RECOVERY_OBSERVE_ACTIONS.has(action.id),
  ) || null
}

export function buildRecoveryObservationPayload(operation = {}) {
  const normalized = {
    id: String(operation.id || '').trim(),
    version: Number(operation.version || 0),
    lastEventChecksum: String(operation.lastEventChecksum || '').trim(),
  }
  if (!normalized.id || !Number.isInteger(normalized.version) || normalized.version <= 0 || !normalized.lastEventChecksum) {
    throw new Error('Operation version과 checksum이 있어야 recovery를 다시 관찰할 수 있습니다.')
  }
  return {
    expected_version: normalized.version,
    expected_checksum: normalized.lastEventChecksum,
    idempotency_key: stableRecoveryObservationKey(normalized),
  }
}

export function createOperationRequestGuard() {
  let generation = 0
  return {
    next() {
      generation += 1
      return generation
    },
    invalidate() {
      generation += 1
    },
    isCurrent(candidate) {
      return candidate === generation
    },
  }
}

export function operationTypeLabel(type) {
  const labels = {
    vm_start: 'VM Start',
    vm_shutdown: 'VM Shutdown',
    vm_create: 'Create VM',
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
