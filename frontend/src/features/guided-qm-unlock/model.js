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

export function guidedQmActionState(operation = {}, nowMs = Date.now()) {
  if (operation.type !== GUIDED_QM_UNLOCK_OPERATION_TYPE) {
    return { guided: false, canAttest: false, canVerify: false, lateAttestation: false }
  }
  const attested = operation.details?.operator_attestation?.command_executed === true
  const expiresMs = operation.expiresAt ? Date.parse(operation.expiresAt) : Number.NaN
  const expiredByTime = operation.status === 'awaiting_operator'
    && Number.isFinite(expiresMs)
    && Number(nowMs) >= expiresMs
  const lateAttestation = expiredByTime || ['expired', 'needs_reconciliation'].includes(operation.status)
  return {
    guided: true,
    canAttest: ['awaiting_operator', 'expired'].includes(operation.status)
      || (operation.status === 'needs_reconciliation' && !attested),
    canVerify: ['awaiting_verification', 'verifying'].includes(operation.status)
      || (operation.status === 'needs_reconciliation' && attested),
    lateAttestation,
  }
}
