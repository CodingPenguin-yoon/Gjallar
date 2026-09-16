import { GUIDED_QM_UNLOCK_OPERATION_TYPE } from '../../entities/operation/model.js'

export function newGuidedQmIdempotencyKey(nodeId = '', vmid = '') {
  const nonce = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `guided-qm:unlock:${String(nodeId).trim()}:${String(vmid).trim()}:${nonce}`
}

export function buildGuidedQmUnlockPayload({ nodeId, vmid, idempotencyKey, acknowledged }) {
  const normalizedNode = String(nodeId || '').trim()
  const normalizedVmid = Number(vmid)
  const normalizedKey = String(idempotencyKey || '').trim()
  if (!normalizedNode) throw new Error('Node ID가 필요합니다.')
  if (!Number.isInteger(normalizedVmid) || normalizedVmid <= 0) throw new Error('VMID는 양의 정수여야 합니다.')
  if (!normalizedKey) throw new Error('Idempotency key가 필요합니다.')
  if (acknowledged !== true) throw new Error('qm unlock 위험 확인이 필요합니다.')
  return {
    node_id: normalizedNode,
    vmid: normalizedVmid,
    idempotency_key: normalizedKey,
    qm_unlock_risk_acknowledged: true,
  }
}

const OPEN_GUIDED_LOCK_STATUSES = new Set(['active', 'stale', 'reconciliation_required'])

export function guidedQmActionState(
  operation = {},
  nowMs = Date.now(),
  instructionState = null,
  coordination = {},
) {
  if (operation.type !== GUIDED_QM_UNLOCK_OPERATION_TYPE) {
    return {
      guided: false,
      canAttest: false,
      canVerify: false,
      lateAttestation: false,
      instructionActive: false,
      instructionHistorical: false,
      doNotExecute: false,
      instructionReason: '',
    }
  }
  const attested = operation.details?.operator_attestation?.command_executed === true
  const expiresMs = operation.expiresAt ? Date.parse(operation.expiresAt) : Number.NaN
  const hasValidExpiry = Number.isFinite(expiresMs)
  const expiredByTime = operation.status === 'awaiting_operator'
    && hasValidExpiry
    && Number(nowMs) >= expiresMs
  const suppliedState = instructionState && typeof instructionState === 'object'
    ? instructionState
    : operation.details?.instruction_state || {}
  const suppliedActive = suppliedState.active
  const suppliedHistorical = suppliedState.historical === true
  const suppliedDoNotExecute = suppliedState.doNotExecute === true || suppliedState.do_not_execute === true
  const lateAttestation = expiredByTime
    || suppliedHistorical
    || suppliedDoNotExecute
    || ['expired', 'needs_reconciliation'].includes(operation.status)
  const hasSuppliedAuthority = typeof suppliedActive === 'boolean'
    || suppliedHistorical
    || suppliedDoNotExecute
  const targetLock = coordination?.targetLock && typeof coordination.targetLock === 'object'
    ? coordination.targetLock
    : null
  const recordedLock = operation.details?.target_operation_lock
    && typeof operation.details.target_operation_lock === 'object'
    ? operation.details.target_operation_lock
    : null
  const recordedDurable = recordedLock?.durable && typeof recordedLock.durable === 'object'
    ? recordedLock.durable
    : null
  const exactTargetLockOwned = Boolean(
    targetLock
    && recordedLock
    && recordedDurable
    && String(targetLock.ownerId || '') === String(operation.id || '')
    && String(targetLock.operationType || '') === GUIDED_QM_UNLOCK_OPERATION_TYPE
    && String(targetLock.targetType || '') === String(operation.targetType || '')
    && String(targetLock.targetId || '') === String(operation.targetId || '')
    && String(targetLock.lockId || '') !== ''
    && String(targetLock.lockId || '') === String(recordedDurable.operation_lock_id || '')
    && String(targetLock.clusterId || '') !== ''
    && String(targetLock.clusterId || '') === String(recordedDurable.cluster_id || '')
    && String(recordedLock.owner_id || '') === String(operation.id || '')
    && String(recordedLock.target_type || '') === String(operation.targetType || '')
    && String(recordedLock.target_id || '') === String(operation.targetId || '')
    && String(recordedDurable.operation_type || '') === GUIDED_QM_UNLOCK_OPERATION_TYPE
    && String(recordedDurable.scope_type || '') === 'proxmox_locator'
    && OPEN_GUIDED_LOCK_STATUSES.has(String(targetLock.status || '')),
  )
  const statusAllowsExecution = operation.status === 'awaiting_operator'
    && hasValidExpiry
    && !expiredByTime
  const suppliedAllowsExecution = !hasSuppliedAuthority
    || (suppliedActive === true && !suppliedHistorical && !suppliedDoNotExecute)
  const instructionActive = statusAllowsExecution
    && suppliedAllowsExecution
    && exactTargetLockOwned
    && String(targetLock?.status || '') === 'active'
  const activeTargetLockOwned = exactTargetLockOwned && String(targetLock?.status || '') === 'active'
  const recoveryError = String(coordination?.recovery?.lastErrorCode || '')
  const targetLockKnownLost = recoveryError === 'GUIDED_QM_TARGET_LOCK_LOST'
  const stateAllowsAttestation = ['awaiting_operator', 'expired'].includes(operation.status)
    || (operation.status === 'needs_reconciliation' && !attested)
  const stateAllowsVerification = ['awaiting_verification', 'verifying'].includes(operation.status)
    || (operation.status === 'needs_reconciliation' && attested)
  return {
    guided: true,
    canAttest: stateAllowsAttestation && (
      operation.status !== 'awaiting_operator' || exactTargetLockOwned
    ),
    canVerify: stateAllowsVerification && activeTargetLockOwned && !targetLockKnownLost,
    lateAttestation,
    instructionActive,
    instructionHistorical: !instructionActive,
    doNotExecute: !instructionActive || suppliedDoNotExecute,
    instructionReason: String(suppliedState.reason || ''),
  }
}
