import { apiV1Client } from '../services/apiV1.js'

const READ_ONLY_ACTIONS = Object.freeze([])
const WARNING_ACK_BLOCKER = 'warnings_not_acknowledged'

function asArray(value) {
  return Array.isArray(value) ? value : []
}

function asObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function asText(value, fallback = '-') {
  const text = String(value ?? '').trim()
  return text || fallback
}

function asNumber(value, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function pickModel(payload) {
  const model = asObject(payload)
  return {
    summary: asObject(model.summary),
    recommendations: asArray(model.recommendations),
    thresholds: asObject(model.thresholds),
    execution: asObject(model.execution),
    evidence: asObject(model.evidence),
    readOnly: model.read_only !== false,
    executable: model.executable === true,
  }
}

function pickRecommendations(payload) {
  if (Array.isArray(payload)) return payload
  return asArray(asObject(payload).recommendations)
}

function normalizeExecution(source = {}) {
  return {
    available: source.available === true,
    allowedActions: asArray(source.allowed_actions ?? source.allowedActions),
    reason: asText(source.reason, 'Frontend DRS recommendation/check output is read-only; backend execution is a separate approval/job route.'),
  }
}

function normalizeBlockers(source = {}) {
  return asArray(source.blockers).map((blocker) => asText(blocker)).filter((blocker) => blocker !== '-')
}

function readinessBool(source = {}, snakeKey, camelKey) {
  const readiness = asObject(source)
  return readiness[snakeKey] === true || readiness[camelKey] === true
}

export function isDrsApprovalWarningAckGate(approvalReadiness = {}) {
  const readiness = asObject(approvalReadiness)
  const blockers = normalizeBlockers(readiness)
  return readinessBool(readiness, 'warnings_ack_required', 'warningsAckRequired') &&
    readinessBool(readiness, 'final_precheck_passed', 'finalPrecheckPassed') &&
    !readinessBool(readiness, 'approval_packet_creatable', 'approvalPacketCreatable') &&
    blockers.length === 1 &&
    blockers[0] === WARNING_ACK_BLOCKER
}

export function canOfferDrsApprovalPacket(approvalReadiness = {}) {
  return readinessBool(approvalReadiness, 'approval_packet_creatable', 'approvalPacketCreatable') ||
    isDrsApprovalWarningAckGate(approvalReadiness)
}

export function canSubmitDrsApprovalPacket(approvalReadiness = {}, { warningAcknowledged = false } = {}) {
  if (readinessBool(approvalReadiness, 'approval_packet_creatable', 'approvalPacketCreatable')) return true
  return warningAcknowledged === true && isDrsApprovalWarningAckGate(approvalReadiness)
}

function normalizeBlockerDetails(value = []) {
  return asArray(value).map((detail) => {
    if (typeof detail === 'string') {
      return {
        code: detail,
        message: formatDrsBlocker(detail),
        authority: 'gjallar_operational_gate',
        category: 'hard_gate',
        severity: 'blocking',
        evidenceState: 'observed',
        actionBlocked: 'approval',
        blocking: true,
        raw: detail,
      }
    }
    const source = asObject(detail)
    const code = asText(source.code ?? source.blocker, '')
    return {
      code,
      message: asText(source.message ?? source.reason, code ? formatDrsBlocker(code) : '-'),
      authority: asText(source.authority, 'gjallar_operational_gate'),
      category: asText(source.category, 'hard_gate'),
      severity: asText(source.severity, 'blocker'),
      evidenceState: asText(source.evidence_state ?? source.evidenceState, 'observed'),
      actionBlocked: asText(source.action_blocked ?? source.actionBlocked, 'approval'),
      blocking: source.blocking !== false,
      raw: detail,
    }
  }).filter((detail) => detail.code || detail.message !== '-')
}

function normalizeCriteriaDetail(value = {}) {
  if (typeof value === 'string') {
    return {
      code: value,
      message: formatDrsBlocker(value),
      authority: 'gjallar_operational_gate',
      category: 'hard_gate',
      severity: 'blocking',
      evidenceState: 'observed',
      actionBlocked: 'approval',
      blocking: true,
      status: 'blocked',
      evidence: {},
      raw: value,
    }
  }
  const source = asObject(value)
  const code = asText(source.code ?? source.blocker, '')
  return {
    code,
    message: asText(source.message ?? source.reason, code ? formatDrsBlocker(code) : '-'),
    authority: asText(source.authority, 'gjallar_operational_gate'),
    category: asText(source.category, 'hard_gate'),
    severity: asText(source.severity, 'blocking'),
    evidenceState: asText(source.evidence_state ?? source.evidenceState, 'observed'),
    actionBlocked: asText(source.action_blocked ?? source.actionBlocked, 'approval'),
    blocking: source.blocking === true,
    status: asText(source.status, ''),
    evidence: asObject(source.evidence),
    raw: value,
  }
}

function normalizeCriteriaDetails(value = []) {
  return asArray(value).map(normalizeCriteriaDetail).filter((detail) => detail.code || detail.message !== '-')
}

function normalizeAdvisorySignals(value = []) {
  return normalizeCriteriaDetails(value).filter((detail) => detail.authority === 'advisor_prefilter_signal')
}

function normalizeTechnicalGateStatus(value = {}) {
  const source = asObject(value)
  return {
    authority: asText(source.authority, 'proxmox_final_technical_gate'),
    category: asText(source.category, 'technical_gate'),
    status: asText(source.status, 'unknown'),
    evidenceState: asText(source.evidence_state ?? source.evidenceState, 'unknown'),
    actionBlocked: asText(source.action_blocked ?? source.actionBlocked, 'execute'),
    criteria: asArray(source.criteria).map((item) => asText(item)).filter((item) => item !== '-'),
    raw: source,
  }
}

function normalizeCriteriaSummary(source = {}) {
  const criteria = asObject(source)
  return {
    hardGateBlockers: normalizeBlockers({ blockers: criteria.hard_gate_blockers ?? criteria.hardGateBlockers }),
    advisorySignalCodes: normalizeBlockers({ blockers: criteria.advisory_signal_codes ?? criteria.advisorySignalCodes }),
    technicalGateStatus: asText(criteria.technical_gate_status ?? criteria.technicalGateStatus, 'unknown'),
    authorities: asArray(criteria.authorities).map((item) => asText(item)).filter((item) => item !== '-'),
    raw: criteria,
  }
}

function normalizeCheckItem(id, source = {}) {
  const item = asObject(source)
  const evidence = asObject(item.evidence)
  const criterion = item.criterion ? normalizeCriteriaDetail(item.criterion) : null
  return {
    id: asText(id, 'check'),
    label: formatDrsBlocker(id),
    status: asText(item.status, 'unknown'),
    blocker: asText(item.blocker, ''),
    evidence,
    criterion,
    raw: item,
  }
}

function normalizeCheckItems(checks = {}) {
  return Object.entries(asObject(checks)).map(([id, item]) => normalizeCheckItem(id, item))
}

function normalizeOperationLockEvidence(evidence = {}, item = {}) {
  const source = asObject(evidence)
  const matchingLocks = asArray(source.matching_locks ?? source.matchingLocks)
  const matchingLockIds = asArray(source.matching_lock_ids ?? source.matchingLockIds)
  const derivedMatchingLockIds = matchingLockIds.length
    ? matchingLockIds
    : matchingLocks
      .map((lock) => asObject(lock).operation_lock_id ?? asObject(lock).operationLockId)
      .filter(Boolean)
  const reconciliationLocks = matchingLocks.filter((lock) => asText(asObject(lock).status, '') === 'reconciliation_required')
  return {
    status: asText(item.status ?? source.status, 'unknown'),
    blocker: asText(item.blocker, ''),
    operationType: asText(source.operation_type ?? source.operationType, ''),
    clusterId: asText(source.cluster_id ?? source.clusterId, ''),
    blocking: source.blocking === true || matchingLocks.length > 0,
    checkedScopes: asArray(source.checked_scopes ?? source.checkedScopes),
    matchingLocks,
    matchingLockIds: derivedMatchingLockIds,
    matchingStatuses: asArray(source.matching_statuses ?? source.matchingStatuses),
    reconciliationRequired: reconciliationLocks.length > 0,
    reconciliationLockIds: reconciliationLocks
      .map((lock) => asObject(lock).operation_lock_id ?? asObject(lock).operationLockId)
      .filter(Boolean),
    raw: source,
  }
}

function normalizeProxmoxConflictEvidence(checks = {}) {
  const checkMap = asObject(checks)
  const conflicts = asObject(checkMap.proxmox_conflicts)
  const explicitEvidence = asObject(conflicts.evidence)
  const evidence = Object.keys(explicitEvidence).length ? explicitEvidence : conflicts
  const items = [
    normalizeCheckItem('proxmox_config_lock', checkMap.proxmox_config_lock),
    normalizeCheckItem('proxmox_active_task', checkMap.proxmox_active_task),
    normalizeCheckItem('proxmox_ha_state', checkMap.proxmox_ha_state),
    normalizeCheckItem('proxmox_cluster_quorum', checkMap.proxmox_cluster_quorum),
    normalizeCheckItem('proxmox_conflicts', conflicts),
  ]
  return {
    status: asText(conflicts.status, 'unknown'),
    blocker: asText(conflicts.blocker, ''),
    configLock: asObject(evidence.config_lock ?? evidence.configLock),
    activeTask: asObject(evidence.active_task ?? evidence.activeTask),
    haState: asObject(evidence.ha_state ?? evidence.haState),
    clusterQuorum: asObject(evidence.cluster_quorum ?? evidence.clusterQuorum),
    notCollected: items.filter((item) => item.status === 'not_collected' || item.status === 'not_implemented'),
    items,
    raw: evidence,
  }
}

function normalizeFinalPrecheck(source = {}) {
  const check = asObject(source)
  const baseChecks = asObject(check.checks ?? check.check_statuses ?? check.checkStatuses)
  const checks = {
    ...baseChecks,
    ...(check.operation_lock ? {
      operation_lock: {
        ...asObject(baseChecks.operation_lock),
        status: asObject(baseChecks.operation_lock).status ?? (check.operation_lock.blocking ? 'failed' : 'pass'),
        evidence: check.operation_lock,
      },
    } : {}),
    ...(check.proxmox_conflicts ? {
      proxmox_conflicts: {
        ...asObject(baseChecks.proxmox_conflicts),
        ...asObject(check.proxmox_conflicts),
        evidence: check.proxmox_conflicts,
      },
    } : {}),
  }
  const operationLockItem = asObject(checks.operation_lock)
  const operationLock = normalizeOperationLockEvidence(operationLockItem.evidence, operationLockItem)
  const proxmoxConflicts = normalizeProxmoxConflictEvidence(checks)
  return {
    status: asText(check.status, 'not run'),
    referenceOnly: check.reference_only === true || check.referenceOnly === true,
    recalculated: check.recalculated === true,
    wouldBeExecutable: check.would_be_executable === true || check.wouldBeExecutable === true,
    blockers: normalizeBlockers(check),
    checks: normalizeCheckItems(checks),
    checksById: checks,
    criteria: normalizeCriteriaSummary(check.criteria),
    criteriaDetails: normalizeCriteriaDetails(check.criteria_details ?? check.criteriaDetails),
    advisorySignals: normalizeAdvisorySignals(check.advisory_signals ?? check.advisorySignals),
    technicalGateStatus: normalizeTechnicalGateStatus(check.technical_gate_status ?? check.technicalGateStatus),
    checkedAt: asText(check.checked_at ?? check.checkedAt, ''),
    observedAt: asText(check.observed_at ?? check.observedAt, ''),
    reason: asText(check.reason, ''),
    operationLock,
    proxmoxConflicts,
    raw: check,
  }
}

function normalizeApprovalReadiness(source = {}) {
  const readiness = asObject(source)
  const finalPrecheckSummary = normalizeFinalPrecheck(readiness.final_precheck_summary ?? readiness.finalPrecheckSummary)
  const lockEvidence = asObject(readiness.lock_evidence ?? readiness.lockEvidence ?? finalPrecheckSummary.operationLock.raw)
  const reconciliation = asObject(readiness.reconciliation)
  return {
    recommendationId: asText(readiness.recommendation_id ?? readiness.recommendationId, ''),
    vmIdentityId: asText(readiness.vm_identity_id ?? readiness.vmIdentityId, ''),
    sourceNodeId: asText(readiness.source_node_id ?? readiness.sourceNodeId, ''),
    targetNodeId: asText(readiness.target_node_id ?? readiness.targetNodeId, ''),
    finalPrecheckPassed: readiness.final_precheck_passed === true || readiness.finalPrecheckPassed === true,
    finalPrecheckSummary,
    lockEvidence,
    reconciliation: {
      required: reconciliation.required === true,
      matchingLockIds: asArray(reconciliation.matching_lock_ids ?? reconciliation.matchingLockIds),
      reasons: asArray(reconciliation.reasons),
      raw: reconciliation,
    },
    approvalPacketCreatable: readiness.approval_packet_creatable === true || readiness.approvalPacketCreatable === true,
    jobIntentCreatable: readiness.job_intent_creatable === true || readiness.jobIntentCreatable === true,
    runnable: readiness.runnable === true,
    proxmoxMutationEnabled: readiness.proxmox_mutation_enabled === true || readiness.proxmoxMutationEnabled === true,
    allowedActions: asArray(readiness.allowed_actions ?? readiness.allowedActions),
    sideEffects: asArray(readiness.side_effects ?? readiness.sideEffects),
    warningAcknowledged: readiness.warning_acknowledged === true || readiness.warningAcknowledged === true,
    warningsAckRequired: readiness.warnings_ack_required === true || readiness.warningsAckRequired === true,
    warningCodes: asArray(readiness.warning_codes ?? readiness.warningCodes),
    warnings: asArray(readiness.warnings),
    blockers: normalizeBlockers(readiness),
    runnableBlockers: asArray(readiness.runnable_blockers ?? readiness.runnableBlockers).map((blocker) => asText(blocker)).filter((blocker) => blocker !== '-'),
    evidenceBinding: asObject(readiness.evidence_binding ?? readiness.evidenceBinding),
    raw: readiness,
  }
}

function normalizeApprovalPacketResponse(source = {}) {
  const response = asObject(source)
  const approvalPacket = asObject(response.approval_packet ?? response.approvalPacket)
  const jobIntent = asObject(response.job_intent ?? response.jobIntent)
  const jobRun = asObject(response.job_run ?? response.jobRun)
  return {
    approvalPacket,
    jobIntent,
    jobRun,
    approvalReadiness: normalizeApprovalReadiness(response.approval_readiness ?? response.approvalReadiness),
    artifacts: asArray(response.artifacts),
    readOnly: response.read_only !== false,
    executable: response.executable === true,
    allowedActions: asArray(response.allowed_actions ?? response.allowedActions),
    runnable: response.runnable === true,
    proxmoxMutationEnabled: response.proxmox_mutation_enabled === true || response.proxmoxMutationEnabled === true,
    sideEffects: asArray(response.side_effects ?? response.sideEffects),
    jobId: asText(jobIntent.job_id ?? jobIntent.jobId ?? jobRun.job_id ?? jobRun.id, ''),
    approvalPacketId: asText(approvalPacket.approval_packet_id ?? approvalPacket.approvalPacketId, ''),
    raw: response,
  }
}

function normalizeRecommendation(source = {}) {
  const effect = asObject(source.estimated_effect ?? source.estimatedEffect)
  const evidence = asObject(source.evidence)
  const identityEvidence = asObject(source.identity_evidence ?? source.identityEvidence ?? evidence.identity)
  const policyEvidence = asObject(source.policy_evidence ?? source.policyEvidence ?? evidence.policy)
  const criteriaDetails = normalizeCriteriaDetails(source.criteria_details ?? source.criteriaDetails)
  const advisorySignals = normalizeAdvisorySignals(source.advisory_signals ?? source.advisorySignals)
  return {
    id: asText(source.id, 'unknown'),
    status: asText(source.status, 'blocked'),
    riskLevel: asText(source.risk_level ?? source.riskLevel, 'yellow'),
    vmid: source.vmid ?? null,
    vmName: asText(source.vm_name ?? source.vmName, 'unknown VM'),
    sourceNodeId: asText(source.source_node_id ?? source.sourceNodeId, 'unknown'),
    sourceNodeName: asText(source.source_node_name ?? source.sourceNodeName, source.source_node_id ?? source.sourceNodeId ?? 'unknown'),
    targetNodeId: asText(source.target_node_id ?? source.targetNodeId, 'unknown'),
    targetNodeName: asText(source.target_node_name ?? source.targetNodeName, source.target_node_id ?? source.targetNodeId ?? 'unknown'),
    reason: asText(source.reason, 'Review current DRS evidence'),
    blockers: normalizeBlockers(source),
    blockerDetails: asArray(source.blocker_details ?? source.blockerDetails),
    criteria: normalizeCriteriaSummary(source.criteria),
    criteriaDetails,
    advisorySignals,
    technicalGateStatus: normalizeTechnicalGateStatus(source.technical_gate_status ?? source.technicalGateStatus),
    thresholds: asObject(source.thresholds),
    estimatedEffect: {
      sourcePressureBefore: asNumber(effect.source_pressure_before ?? effect.sourcePressureBefore),
      sourcePressureAfter: asNumber(effect.source_pressure_after ?? effect.sourcePressureAfter),
      targetPressureBefore: asNumber(effect.target_pressure_before ?? effect.targetPressureBefore),
      targetPressureAfter: asNumber(effect.target_pressure_after ?? effect.targetPressureAfter),
      sourceTargetDelta: asNumber(effect.source_target_delta ?? effect.sourceTargetDelta),
    },
    evidence,
    identityEvidence,
    policyEvidence,
    readOnly: source.read_only !== false,
    executable: source.executable === true,
    allowedActions: asArray(source.allowed_actions ?? source.allowedActions),
    execution: normalizeExecution(source.execution),
    raw: source,
  }
}

function normalizePolicyValue(source = {}) {
  const policy = asObject(source)
  return {
    policyId: asText(policy.policy_id ?? policy.policyId, ''),
    value: asText(policy.value ?? policy.policy, 'unknown'),
    reason: asText(policy.reason, ''),
    source: asText(policy.source, 'default'),
    updatedBy: asText(policy.updated_by ?? policy.updatedBy, ''),
    updatedAt: asText(policy.updated_at ?? policy.updatedAt, ''),
    raw: policy,
  }
}

function normalizeExpectedObservation(source = {}) {
  const observation = asObject(source)
  return {
    observationId: asText(observation.observation_id ?? observation.observationId, ''),
    clusterId: asText(observation.cluster_id ?? observation.clusterId, ''),
    nodeId: asText(observation.node_id ?? observation.nodeId, ''),
    vmid: observation.vmid ?? null,
    fingerprintHash: asText(observation.fingerprint_hash ?? observation.fingerprintHash, ''),
    observedAt: asText(observation.observed_at ?? observation.observedAt, ''),
    matchConfidence: asText(observation.match_confidence ?? observation.matchConfidence, ''),
    raw: observation,
  }
}

function compactExpectedObservation(source = {}) {
  const observation = normalizeExpectedObservation(source)
  return {
    cluster_id: observation.clusterId,
    node_id: observation.nodeId,
    vmid: observation.vmid,
    fingerprint_hash: observation.fingerprintHash,
    observed_at: observation.observedAt,
  }
}

export function normalizeDrsPolicyItem(source = {}) {
  const item = asObject(source)
  const locator = asObject(item.current_locator ?? item.currentLocator)
  const latestObservation = asObject(item.latest_observation ?? item.latestObservation)
  const expectedObservation = item.expected_observation ?? item.expectedObservation ?? latestObservation
  const fingerprint = asObject(item.fingerprint)
  const impact = asObject(item.drs_blocker_impact ?? item.drsBlockerImpact)
  const policy = normalizePolicyValue(item.policy ?? item.policy_evidence ?? item.policyEvidence)
  return {
    vmIdentityId: asText(item.vm_identity_id ?? item.vmIdentityId, ''),
    identityConfidence: asText(item.identity_confidence ?? item.identityConfidence, 'unknown'),
    identityStatus: asText(item.identity_status ?? item.identityStatus, 'unknown'),
    currentLocator: {
      clusterId: asText(locator.cluster_id ?? locator.clusterId, ''),
      nodeId: asText(locator.node_id ?? locator.nodeId, ''),
      vmid: locator.vmid ?? null,
      name: asText(locator.name, 'unknown VM'),
      powerState: asText(locator.power_state ?? locator.powerState, 'unknown'),
    },
    latestObservation: {
      observationId: asText(latestObservation.observation_id ?? latestObservation.observationId, ''),
      observedAt: asText(latestObservation.observed_at ?? latestObservation.observedAt, ''),
      ageSeconds: latestObservation.age_seconds ?? latestObservation.ageSeconds ?? null,
      matchConfidence: asText(latestObservation.match_confidence ?? latestObservation.matchConfidence, ''),
      source: asText(latestObservation.source, ''),
    },
    expectedObservation: normalizeExpectedObservation(expectedObservation),
    expectedObservationPayload: compactExpectedObservation(expectedObservation),
    fingerprint: {
      fingerprintHash: asText(fingerprint.fingerprint_hash ?? fingerprint.fingerprintHash, ''),
      stableFingerprint: asText(fingerprint.stable_fingerprint ?? fingerprint.stableFingerprint, ''),
      smbios1UuidPresent: fingerprint.smbios1_uuid_present === true || fingerprint.smbios1UuidPresent === true,
      vmgenidPresent: fingerprint.vmgenid_present === true || fingerprint.vmgenidPresent === true,
      macAddressCount: asNumber(fingerprint.mac_address_count ?? fingerprint.macAddressCount),
      diskVolumeIdCount: asNumber(fingerprint.disk_volume_id_count ?? fingerprint.diskVolumeIdCount),
    },
    policy,
    currentDrsCandidate: item.current_drs_candidate === true || item.currentDrsCandidate === true,
    recommendationId: asText(item.recommendation_id ?? item.recommendationId, ''),
    drsBlockerImpact: {
      policyBlockers: normalizeBlockers({ blockers: impact.policy_blockers ?? impact.policyBlockers }),
      recommendationBlockers: normalizeBlockers({ blockers: impact.recommendation_blockers ?? impact.recommendationBlockers }),
      blocksRecommendation: impact.blocks_recommendation === true || impact.blocksRecommendation === true,
      blocksFinalCheck: impact.blocks_final_check === true || impact.blocksFinalCheck === true,
      allowedIsPrerequisiteOnly: impact.allowed_is_prerequisite_only !== false && impact.allowedIsPrerequisiteOnly !== false,
    },
    policyWriteAllowed: item.policy_write_allowed === true || item.policyWriteAllowed === true,
    policyWriteBlockers: normalizeBlockers({ blockers: item.policy_write_blockers ?? item.policyWriteBlockers }),
    raw: item,
  }
}

export function buildDrsPolicyCoverageModel(payload = {}) {
  const model = asObject(payload)
  const items = asArray(model.items).map(normalizeDrsPolicyItem)
  const coverage = asObject(model.coverage)
  return {
    items,
    coverage: {
      totalNonTemplateVms: asNumber(coverage.total_non_template_vms ?? coverage.totalNonTemplateVms, items.length),
      writeAllowedCount: asNumber(coverage.write_allowed_count ?? coverage.writeAllowedCount),
      unknownCount: asNumber(coverage.unknown_count ?? coverage.unknownCount),
      allowedCount: asNumber(coverage.allowed_count ?? coverage.allowedCount),
      restrictedCount: asNumber(coverage.restricted_count ?? coverage.restrictedCount),
      blockedCount: asNumber(coverage.blocked_count ?? coverage.blockedCount),
      identityUncertainCount: asNumber(coverage.identity_uncertain_count ?? coverage.identityUncertainCount),
    },
    evidence: asObject(model.evidence),
    readOnly: model.read_only !== false,
    executable: model.executable === true,
    allowedActions: asArray(model.allowed_actions ?? model.allowedActions),
  }
}

export async function loadDrsPolicyCoverage(client = apiV1Client) {
  if (!client || typeof client.drsPolicies !== 'function') {
    throw new Error('DRS Advisor requires an /api/v1 client with drsPolicies()')
  }
  return buildDrsPolicyCoverageModel(await client.drsPolicies())
}

export async function submitDrsPolicyUpdate(
  client = apiV1Client,
  vmIdentityId,
  { policy, reason = '', expectedObservation, policyChangeAcknowledged = false } = {},
) {
  if (!client || typeof client.updateDrsPolicy !== 'function') {
    throw new Error('DRS Advisor requires an /api/v1 client with updateDrsPolicy()')
  }
  const result = asObject(await client.updateDrsPolicy(vmIdentityId, {
    policy,
    reason,
    policy_change_acknowledged: policyChangeAcknowledged === true,
    expected_observation: compactExpectedObservation(expectedObservation),
  }))
  return {
    vmIdentityId: asText(result.vm_identity_id ?? result.vmIdentityId, vmIdentityId),
    auditEventId: asText(result.audit_event_id ?? result.auditEventId, ''),
    auditEventCreated: result.audit_event_created === true || result.auditEventCreated === true,
    idempotent: result.idempotent === true,
    previousPolicy: normalizePolicyValue(result.previous_policy ?? result.previousPolicy),
    newPolicy: normalizePolicyValue(result.new_policy ?? result.newPolicy),
    validationResult: asObject(result.validation_result ?? result.validationResult),
    policyItem: normalizeDrsPolicyItem(result.policy_item ?? result.policyItem),
    recommendationImpact: result.recommendation_impact || result.recommendationImpact
      ? normalizeRecommendation(result.recommendation_impact ?? result.recommendationImpact)
      : null,
    checkImpact: asObject(result.check_impact ?? result.checkImpact),
    executable: result.executable === true,
    allowedActions: asArray(result.allowed_actions ?? result.allowedActions),
    proxmoxMutationEnabled: result.proxmox_mutation_enabled === true || result.proxmoxMutationEnabled === true,
    sideEffects: asArray(result.side_effects ?? result.sideEffects),
    raw: result,
  }
}

function normalizeSummary(source = {}) {
  const execution = normalizeExecution(source.execution)
  return {
    clusterState: asText(source.cluster_state ?? source.clusterState, 'unknown'),
    totalNodes: asNumber(source.total_nodes ?? source.totalNodes),
    onlineNodes: asNumber(source.online_nodes ?? source.onlineNodes),
    totalVms: asNumber(source.total_vms ?? source.totalVms),
    runningCandidateVms: asNumber(source.running_candidate_vms ?? source.runningCandidateVms),
    excludedRedRiskVms: asNumber(source.excluded_red_risk_vms ?? source.excludedRedRiskVms),
    recommendationCount: asNumber(source.recommendation_count ?? source.recommendationCount),
    hotNodeCount: asNumber(source.hot_node_count ?? source.hotNodeCount),
    criticalNodeCount: asNumber(source.critical_node_count ?? source.criticalNodeCount),
    sourceTargetDelta: asNumber(source.source_target_delta ?? source.sourceTargetDelta),
    thresholds: asObject(source.thresholds),
    readOnly: source.read_only !== false,
    executable: source.executable === true,
    execution,
  }
}

function statusTone(status) {
  const normalized = String(status ?? '').toLowerCase()
  if (normalized === 'critical') return 'red'
  if (normalized === 'hot' || normalized === 'blocked' || normalized === 'yellow') return 'yellow'
  if (normalized === 'balanced' || normalized === 'green') return 'green'
  return 'slate'
}

export function buildDrsAdvisorViewModel({ summaryPayload = {}, recommendationsPayload = {} } = {}) {
  const summaryModel = pickModel(summaryPayload)
  const recommendationModel = pickModel(recommendationsPayload)
  const rawRecommendations = pickRecommendations(recommendationsPayload).length
    ? pickRecommendations(recommendationsPayload)
    : summaryModel.recommendations
  const recommendations = rawRecommendations.map(normalizeRecommendation)
  const summary = normalizeSummary(
    Object.keys(recommendationModel.summary).length ? recommendationModel.summary : summaryModel.summary,
  )
  const thresholds = Object.keys(recommendationModel.thresholds).length
    ? recommendationModel.thresholds
    : summaryModel.thresholds
  const execution = normalizeExecution(
    Object.keys(recommendationModel.execution).length ? recommendationModel.execution : summaryModel.execution,
  )
  return {
    summary,
    recommendations,
    thresholds,
    execution,
    evidence: Object.keys(recommendationModel.evidence).length ? recommendationModel.evidence : summaryModel.evidence,
    status: summary.clusterState,
    tone: statusTone(summary.clusterState),
    readOnly: true,
    executable: false,
    allowedActions: READ_ONLY_ACTIONS,
  }
}

export async function loadDrsAdvisorModel(client = apiV1Client) {
  for (const method of ['getDrsSummary', 'listDrsRecommendations']) {
    if (!client || typeof client[method] !== 'function') {
      throw new Error(`DRS Advisor requires an /api/v1 client with ${method}()`)
    }
  }
  const [summaryPayload, recommendationsPayload] = await Promise.all([
    client.getDrsSummary(),
    client.listDrsRecommendations(),
  ])
  return buildDrsAdvisorViewModel({ summaryPayload, recommendationsPayload })
}

export async function loadDrsRecommendationDetail(client = apiV1Client, recommendationId) {
  if (!client || typeof client.getDrsRecommendation !== 'function') {
    throw new Error('DRS Advisor requires an /api/v1 client with getDrsRecommendation()')
  }
  return normalizeRecommendation(await client.getDrsRecommendation(recommendationId))
}

export async function checkDrsRecommendation(client = apiV1Client, recommendationId, payload = {}) {
  if (!client || typeof client.checkDrsRecommendation !== 'function') {
    throw new Error('DRS Advisor requires an /api/v1 client with checkDrsRecommendation()')
  }
  const result = asObject(await client.checkDrsRecommendation(recommendationId, payload))
  const finalPrecheck = normalizeFinalPrecheck(result.check)
  return {
    recommendationId: asText(result.recommendation_id ?? result.recommendationId, recommendationId),
    readOnly: result.read_only !== false,
    executable: result.executable === true,
    wouldBeExecutable: result.would_be_executable === true || result.wouldBeExecutable === true,
    allowedActions: asArray(result.allowed_actions ?? result.allowedActions),
    execution: normalizeExecution(result.execution),
    blockers: normalizeBlockers(result),
    blockerDetails: normalizeBlockerDetails(result.blocker_details ?? result.blockerDetails),
    criteria: normalizeCriteriaSummary(result.criteria),
    criteriaDetails: normalizeCriteriaDetails(result.criteria_details ?? result.criteriaDetails),
    advisorySignals: normalizeAdvisorySignals(result.advisory_signals ?? result.advisorySignals),
    technicalGateStatus: normalizeTechnicalGateStatus(result.technical_gate_status ?? result.technicalGateStatus),
    identityEvidence: asObject(result.identity_evidence ?? result.identityEvidence),
    policyEvidence: asObject(result.policy_evidence ?? result.policyEvidence),
    checkedAt: asText(result.checked_at ?? result.checkedAt, ''),
    check: asObject(result.check),
    finalPrecheck,
    operationLock: finalPrecheck.operationLock,
    proxmoxConflicts: finalPrecheck.proxmoxConflicts,
    approvalReadiness: normalizeApprovalReadiness(result.approval_readiness ?? result.approvalReadiness),
    recommendation: normalizeRecommendation(result.recommendation),
  }
}

export async function createDrsApprovalPacket(client = apiV1Client, recommendationId, { warningAcknowledged = false } = {}) {
  if (!client || typeof client.createDrsApprovalPacket !== 'function') {
    throw new Error('DRS Advisor requires an /api/v1 client with createDrsApprovalPacket()')
  }
  const result = await client.createDrsApprovalPacket(recommendationId, {
    warning_acknowledged: warningAcknowledged === true,
  })
  return normalizeApprovalPacketResponse(result)
}

export function drsToneClass(tone) {
  const normalized = String(tone ?? '').toLowerCase()
  if (normalized === 'green' || normalized === 'balanced') return 'border-emerald-200 bg-emerald-50 text-emerald-800'
  if (normalized === 'yellow' || normalized === 'hot' || normalized === 'blocked') return 'border-amber-200 bg-amber-50 text-amber-800'
  if (normalized === 'red' || normalized === 'critical') return 'border-red-200 bg-red-50 text-red-800'
  return 'border-slate-200 bg-slate-50 text-slate-800'
}

export function formatDrsBlocker(code) {
  return asText(code).replaceAll('_', ' ')
}
