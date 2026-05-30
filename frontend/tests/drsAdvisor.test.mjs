import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

async function importExpected(path, description) {
  try {
    return await import(path)
  } catch (error) {
    assert.fail(`Expected ${description} at ${path}, but it is missing or invalid: ${error.message}`)
  }
}

const {
  buildDrsAdvisorViewModel,
  canOfferDrsApprovalPacket,
  canSubmitDrsApprovalPacket,
  checkDrsRecommendation,
  createDrsApprovalPacket,
  buildDrsPolicyCoverageModel,
  drsToneClass,
  formatDrsBlocker,
  isDrsApprovalWarningAckGate,
  loadDrsAdvisorModel,
  loadDrsPolicyCoverage,
  loadDrsRecommendationDetail,
  normalizeDrsPolicyItem,
  submitDrsPolicyUpdate,
} = await importExpected('../src/utils/drsAdvisor.js', 'DRS Advisor view model utility')

const recommendation = {
  id: 'drs-rec-vm-101-node-a-node-b',
  status: 'blocked',
  risk_level: 'yellow',
  vmid: 101,
  vm_name: 'app-01',
  source_node_id: 'node-a',
  source_node_name: 'node-a',
  target_node_id: 'node-b',
  target_node_name: 'node-b',
  reason: 'Source node is hot and target pressure is lower by 42%.',
  blockers: ['migration_policy_unknown', 'policy_unknown', 'final_precheck_not_run', 'local_storage_dependency'],
  identity_evidence: {
    vm_identity_id: 'vmid-1',
    stable_fingerprint: 'sha256:abcdef0123456789',
    match_confidence: 'high',
    identity_status: 'active',
  },
  policy_evidence: {
    policy: 'unknown',
    source: 'default',
    reason: 'No DRS migration policy has been recorded',
  },
  thresholds: { hot: 70, critical: 85, source_target_delta: 25 },
  estimated_effect: {
    source_pressure_before: 82,
    source_pressure_after: 74,
    target_pressure_before: 40,
    target_pressure_after: 48,
    source_target_delta: 42,
  },
  evidence: {
    route: {
      matching_target_bridge_ids: ['vmbr0'],
      network_evidence_sufficient: true,
      storage_evidence_sufficient: true,
    },
  },
  read_only: true,
  executable: false,
  allowed_actions: [],
  execution: {
    available: false,
    allowed_actions: [],
    reason: 'DRS Phase 1 is advisory only',
  },
}

const drsModel = {
  summary: {
    cluster_state: 'hot',
    total_nodes: 2,
    online_nodes: 2,
    total_vms: 4,
    running_candidate_vms: 3,
    excluded_red_risk_vms: 1,
    recommendation_count: 1,
    hot_node_count: 1,
    critical_node_count: 0,
    source_target_delta: 42,
    thresholds: { hot: 70, critical: 85, source_target_delta: 25 },
    read_only: true,
    executable: false,
    execution: { available: false, allowed_actions: [], reason: 'advisory only' },
  },
  recommendations: [recommendation],
  thresholds: { hot: 70, critical: 85, source_target_delta: 25 },
  read_only: true,
  executable: false,
  allowed_actions: [],
  execution: { available: false, allowed_actions: [], reason: 'advisory only' },
}

const policyItem = {
  vm_identity_id: 'vmid-1',
  identity_confidence: 'high',
  identity_status: 'active',
  current_locator: {
    cluster_id: 'cluster-a',
    node_id: 'node-a',
    vmid: 101,
    name: 'app-01',
    power_state: 'running',
  },
  latest_observation: {
    observation_id: 'obs-1',
    observed_at: '2026-05-31T00:00:00Z',
    age_seconds: 30,
    match_confidence: 'high',
  },
  expected_observation: {
    observation_id: 'obs-1',
    cluster_id: 'cluster-a',
    node_id: 'node-a',
    vmid: 101,
    fingerprint_hash: 'sha256:abcdef0123456789',
    observed_at: '2026-05-31T00:00:00Z',
    match_confidence: 'high',
  },
  fingerprint: {
    fingerprint_hash: 'sha256:abcdef0123456789',
    smbios1_uuid_present: true,
    vmgenid_present: true,
    mac_address_count: 1,
    disk_volume_id_count: 1,
  },
  policy: {
    policy_id: null,
    value: 'unknown',
    reason: 'No DRS migration policy has been recorded',
    source: 'default',
    updated_by: null,
    updated_at: null,
  },
  current_drs_candidate: true,
  recommendation_id: recommendation.id,
  drs_blocker_impact: {
    policy_blockers: ['migration_policy_unknown', 'policy_unknown'],
    recommendation_blockers: ['migration_policy_unknown', 'policy_unknown', 'final_precheck_not_run'],
    blocks_recommendation: true,
    blocks_final_check: true,
    allowed_is_prerequisite_only: true,
  },
  policy_write_allowed: true,
  policy_write_blockers: [],
}

const policyCoveragePayload = {
  items: [
    policyItem,
    {
      ...policyItem,
      vm_identity_id: null,
      identity_confidence: 'medium',
      current_locator: { ...policyItem.current_locator, vmid: 102, name: 'medium-identity' },
      policy_write_allowed: false,
      policy_write_blockers: ['policy_write_identity_uncertain'],
    },
  ],
  coverage: {
    total_non_template_vms: 2,
    write_allowed_count: 1,
    unknown_count: 2,
    allowed_count: 0,
    restricted_count: 0,
    blocked_count: 0,
    identity_uncertain_count: 1,
  },
  read_only: true,
  executable: false,
  allowed_actions: [],
}

const viewModel = buildDrsAdvisorViewModel({
  summaryPayload: drsModel,
  recommendationsPayload: drsModel,
})
assert.equal(viewModel.readOnly, true)
assert.equal(viewModel.executable, false)
assert.equal(viewModel.summary.clusterState, 'hot')
assert.equal(viewModel.summary.recommendationCount, 1)
assert.equal(viewModel.summary.runningCandidateVms, 3)
assert.equal(viewModel.summary.excludedRedRiskVms, 1)
assert.equal(viewModel.thresholds.hot, 70)
assert.equal(viewModel.thresholds.critical, 85)
assert.equal(viewModel.thresholds.source_target_delta, 25)
assert.equal(viewModel.execution.available, false)
assert.equal(viewModel.recommendations[0].id, recommendation.id)
assert.equal(viewModel.recommendations[0].vmName, 'app-01')
assert.deepEqual(viewModel.recommendations[0].blockers, recommendation.blockers)
assert.equal(viewModel.recommendations[0].identityEvidence.match_confidence, 'high')
assert.equal(viewModel.recommendations[0].policyEvidence.policy, 'unknown')
assert.equal(viewModel.recommendations[0].estimatedEffect.sourceTargetDelta, 42)
assert.equal(drsToneClass('critical').includes('red'), true)
assert.equal(drsToneClass('hot').includes('amber'), true)
assert.equal(formatDrsBlocker('identity_unknown'), 'identity unknown')
const normalizedPolicyItem = normalizeDrsPolicyItem(policyItem)
assert.equal(normalizedPolicyItem.vmIdentityId, 'vmid-1')
assert.equal(normalizedPolicyItem.policy.value, 'unknown')
assert.equal(normalizedPolicyItem.policyWriteAllowed, true)
assert.deepEqual(normalizedPolicyItem.expectedObservationPayload, {
  cluster_id: 'cluster-a',
  node_id: 'node-a',
  vmid: 101,
  fingerprint_hash: 'sha256:abcdef0123456789',
  observed_at: '2026-05-31T00:00:00Z',
})
const policyCoverage = buildDrsPolicyCoverageModel(policyCoveragePayload)
assert.equal(policyCoverage.coverage.totalNonTemplateVms, 2)
assert.equal(policyCoverage.coverage.identityUncertainCount, 1)
assert.equal(policyCoverage.items[1].policyWriteBlockers[0], 'policy_write_identity_uncertain')

const calls = []
const fakeClient = {
  async getDrsSummary() {
    calls.push('getDrsSummary')
    return drsModel
  },
  async listDrsRecommendations() {
    calls.push('listDrsRecommendations')
    return drsModel
  },
  async getDrsRecommendation(id) {
    calls.push(`getDrsRecommendation:${id}`)
    return recommendation
  },
  async drsPolicies() {
    calls.push('drsPolicies')
    return policyCoveragePayload
  },
  async updateDrsPolicy(id, payload) {
    calls.push(`updateDrsPolicy:${id}:${JSON.stringify(payload)}`)
    return {
      vm_identity_id: id,
      previous_policy: { policy: 'unknown', reason: '', source: 'default' },
      new_policy: { policy: payload.policy, reason: payload.reason, source: 'manual', updated_by: 'operator' },
      audit_event_id: 'vmpolevt-1',
      audit_event_created: true,
      idempotent: false,
      validation_result: { status: 'pass' },
      policy_item: {
        ...policyItem,
        policy: { policy_id: 'policy-1', value: payload.policy, reason: payload.reason, source: 'manual', updated_by: 'operator' },
      },
      recommendation_impact: {
        ...recommendation,
        policy_evidence: { policy: payload.policy, source: 'manual', reason: payload.reason },
        blockers: ['final_precheck_not_run'],
      },
      check_impact: {
        executable: false,
        allowed_actions: [],
        would_be_executable: payload.policy === 'allowed',
      },
      executable: false,
      allowed_actions: [],
      proxmox_mutation_enabled: false,
      side_effects: ['gjallar_local_policy_update'],
    }
  },
  async checkDrsRecommendation(id, payload) {
    calls.push(`checkDrsRecommendation:${id}:${payload.reference_only === true}`)
    return {
      recommendation_id: id,
      read_only: true,
      executable: false,
      would_be_executable: false,
      execution: { available: false, allowed_actions: [], reason: 'advisory only' },
      allowed_actions: [],
      blockers: ['operation_lock_reconciliation_required', 'vm_config_lock', 'drs_final_precheck_failed'],
      blocker_details: [
        { code: 'operation_lock_reconciliation_required', message: 'A DRS operation lock requires reconciliation before execution.' },
        { code: 'vm_config_lock', message: 'Proxmox config lock is present.' },
      ],
      identity_evidence: recommendation.identity_evidence,
      policy_evidence: recommendation.policy_evidence,
      check: {
        status: 'blocked',
        reference_only: true,
        recalculated: true,
        would_be_executable: false,
        blockers: ['operation_lock_reconciliation_required', 'vm_config_lock', 'drs_final_precheck_failed'],
        checks: {
          operation_lock: {
            status: 'failed',
            blocker: 'operation_lock_reconciliation_required',
            evidence: {
              operation_type: 'drs_migration',
              cluster_id: 'cluster-a',
              checked_scopes: [{ scope_type: 'vm_identity', scope_key: 'cluster-a:vmid-1' }],
              matching_locks: [
                {
                  operation_lock_id: 'lock-reconcile',
                  status: 'reconciliation_required',
                  scope_type: 'vm_identity',
                  reason: 'post_check_mismatch',
                },
              ],
              matching_statuses: ['reconciliation_required'],
              blocking: true,
            },
          },
          proxmox_config_lock: {
            status: 'failed',
            blocker: 'vm_config_lock',
            evidence: { status: 'locked', blocking: true, source: 'config.lock', lock: 'backup' },
          },
          proxmox_active_task: { status: 'not_collected', evidence: { status: 'not_collected', blocking: null } },
          proxmox_ha_state: { status: 'not_collected', evidence: { status: 'not_collected', blocking: null } },
          proxmox_cluster_quorum: { status: 'not_collected', evidence: { status: 'not_collected', blocking: null } },
          proxmox_conflicts: {
            status: 'failed',
            blocker: 'vm_config_lock',
            evidence: {
              config_lock: { status: 'locked', blocking: true, source: 'config.lock', lock: 'backup' },
              active_task: { status: 'not_collected', blocking: null },
              ha_state: { status: 'not_collected', blocking: null },
              cluster_quorum: { status: 'not_collected', blocking: null },
            },
          },
        },
        checked_at: '2026-05-30T01:00:00Z',
        observed_at: '2026-05-30T00:59:00Z',
        reason: 'Read-only final pre-check completed; recommendation/check output remains execution-closed.',
      },
      approval_readiness: {
        recommendation_id: id,
        vm_identity_id: 'vmid-1',
        source_node_id: 'node-a',
        target_node_id: 'node-b',
        final_precheck_passed: false,
        final_precheck_summary: {
          status: 'blocked',
          would_be_executable: false,
          checked_at: '2026-05-30T01:00:00Z',
          observed_at: '2026-05-30T00:59:00Z',
          blockers: ['operation_lock_reconciliation_required', 'vm_config_lock', 'drs_final_precheck_failed'],
          check_statuses: {
            operation_lock: { status: 'failed', blocker: 'operation_lock_reconciliation_required' },
            proxmox_active_task: { status: 'not_collected' },
          },
          operation_lock: {
            operation_type: 'drs_migration',
            cluster_id: 'cluster-a',
            matching_locks: [{ operation_lock_id: 'lock-reconcile', status: 'reconciliation_required', reason: 'post_check_mismatch' }],
            matching_lock_ids: ['lock-reconcile'],
            blocking: true,
          },
          proxmox_conflicts: {
            status: 'failed',
            blocker: 'vm_config_lock',
            config_lock: { status: 'locked', blocking: true },
            active_task: { status: 'not_collected', blocking: null },
          },
        },
        lock_evidence: {
          operation_type: 'drs_migration',
          cluster_id: 'cluster-a',
          matching_locks: [{ operation_lock_id: 'lock-reconcile', status: 'reconciliation_required', reason: 'post_check_mismatch' }],
          matching_lock_ids: ['lock-reconcile'],
          blocking: true,
        },
        reconciliation: { required: true, matching_lock_ids: ['lock-reconcile'], reasons: ['post_check_mismatch'] },
        approval_packet_creatable: false,
        job_intent_creatable: false,
        runnable: false,
        proxmox_mutation_enabled: false,
        allowed_actions: [],
        side_effects: [],
        warnings_ack_required: false,
        blockers: ['operation_lock_reconciliation_required', 'vm_config_lock', 'drs_final_precheck_failed'],
        runnable_blockers: ['proxmox_active_task_not_collected'],
      },
      recommendation,
    }
  },
  async createDrsApprovalPacket(id, payload) {
    calls.push(`createDrsApprovalPacket:${id}:${JSON.stringify(payload)}`)
    return {
      approval_packet: { approval_packet_id: 'drsap-1', recommendation_id: id },
      job_intent: {
        job_id: 'drs-mig-1',
        approval_packet_id: 'drsap-1',
        recommendation_id: id,
        runnable: false,
        proxmox_mutation_enabled: false,
        side_effects: [],
      },
      job_run: { job_id: 'drs-mig-1', job_type: 'drs_migration', status: 'pending' },
      approval_readiness: {
        recommendation_id: id,
        approval_packet_creatable: true,
        job_intent_creatable: true,
        runnable: false,
        proxmox_mutation_enabled: false,
        allowed_actions: [],
        side_effects: [],
      },
      read_only: false,
      executable: false,
      allowed_actions: [],
      runnable: false,
      proxmox_mutation_enabled: false,
      side_effects: [],
    }
  },
}

const loaded = await loadDrsAdvisorModel(fakeClient)
assert.equal(loaded.summary.clusterState, 'hot')
assert.equal(loaded.recommendations.length, 1)
assert.deepEqual(calls, ['getDrsSummary', 'listDrsRecommendations'])

const loadedPolicyCoverage = await loadDrsPolicyCoverage(fakeClient)
assert.equal(loadedPolicyCoverage.items.length, 2)
assert.equal(loadedPolicyCoverage.items[0].expectedObservation.fingerprintHash, 'sha256:abcdef0123456789')

const detail = await loadDrsRecommendationDetail(fakeClient, recommendation.id)
assert.equal(detail.id, recommendation.id)
const checkResult = await checkDrsRecommendation(fakeClient, recommendation.id, { reference_only: true })
assert.equal(checkResult.recommendationId, recommendation.id)
assert.equal(checkResult.readOnly, true)
assert.equal(checkResult.executable, false)
assert.equal(checkResult.wouldBeExecutable, false)
assert.deepEqual(checkResult.allowedActions, [])
assert.equal(checkResult.check.reference_only, true)
assert.equal(checkResult.execution.available, false)
assert.equal(checkResult.identityEvidence.match_confidence, 'high')
assert.equal(checkResult.policyEvidence.policy, 'unknown')
assert.equal(checkResult.blockerDetails[0].code, 'operation_lock_reconciliation_required')
assert.equal(checkResult.finalPrecheck.status, 'blocked')
assert.ok(checkResult.finalPrecheck.checks.some((check) => check.id === 'proxmox_active_task' && check.status === 'not_collected'))
assert.equal(checkResult.operationLock.matchingLockIds[0], 'lock-reconcile')
assert.equal(checkResult.operationLock.reconciliationRequired, true)
assert.equal(checkResult.proxmoxConflicts.configLock.status, 'locked')
assert.equal(checkResult.proxmoxConflicts.notCollected.length, 3)
assert.equal(checkResult.approvalReadiness.approvalPacketCreatable, false)
assert.equal(checkResult.approvalReadiness.reconciliation.required, true)
assert.deepEqual(checkResult.approvalReadiness.allowedActions, [])
assert.equal(checkResult.approvalReadiness.runnable, false)
assert.equal(checkResult.approvalReadiness.proxmoxMutationEnabled, false)

const warningAckReadiness = {
  finalPrecheckPassed: true,
  approvalPacketCreatable: false,
  warningsAckRequired: true,
  blockers: ['warnings_not_acknowledged'],
}
assert.equal(isDrsApprovalWarningAckGate(warningAckReadiness), true)
assert.equal(canOfferDrsApprovalPacket(warningAckReadiness), true)
assert.equal(canSubmitDrsApprovalPacket(warningAckReadiness), false)
assert.equal(canSubmitDrsApprovalPacket(warningAckReadiness, { warningAcknowledged: true }), true)
assert.equal(canSubmitDrsApprovalPacket({ approvalPacketCreatable: true }, { warningAcknowledged: false }), true)
assert.equal(canSubmitDrsApprovalPacket({
  ...warningAckReadiness,
  blockers: ['warnings_not_acknowledged', 'operation_lock_reconciliation_required'],
}, { warningAcknowledged: true }), false)
assert.equal(canSubmitDrsApprovalPacket({
  ...warningAckReadiness,
  finalPrecheckPassed: false,
  finalPrecheckSummary: { wouldBeExecutable: true },
}, { warningAcknowledged: true }), false)
assert.equal(canSubmitDrsApprovalPacket({
  final_precheck_passed: true,
  approval_packet_creatable: false,
  warnings_ack_required: true,
  blockers: ['warnings_not_acknowledged'],
}, { warningAcknowledged: true }), true)

const approvalPacket = await createDrsApprovalPacket(fakeClient, recommendation.id, { warningAcknowledged: true })
assert.equal(approvalPacket.approvalPacketId, 'drsap-1')
assert.equal(approvalPacket.jobId, 'drs-mig-1')
assert.equal(approvalPacket.readOnly, false)
assert.equal(approvalPacket.executable, false)
assert.deepEqual(approvalPacket.allowedActions, [])
assert.equal(approvalPacket.runnable, false)
assert.equal(approvalPacket.proxmoxMutationEnabled, false)
assert.deepEqual(approvalPacket.sideEffects, [])
assert.equal(approvalPacket.approvalReadiness.approvalPacketCreatable, true)
assert.ok(calls.includes(`createDrsApprovalPacket:${recommendation.id}:{"warning_acknowledged":true}`))

const policyUpdate = await submitDrsPolicyUpdate(fakeClient, 'vmid-1', {
  policy: 'allowed',
  reason: 'manual classification',
  policyChangeAcknowledged: true,
  expectedObservation: normalizedPolicyItem.expectedObservationPayload,
})
assert.equal(policyUpdate.auditEventId, 'vmpolevt-1')
assert.equal(policyUpdate.newPolicy.value, 'allowed')
assert.equal(policyUpdate.policyItem.policy.source, 'manual')
assert.equal(policyUpdate.recommendationImpact.executable, false)
assert.deepEqual(policyUpdate.allowedActions, [])
assert.ok(calls.includes('drsPolicies'))
const updateCall = calls.find((call) => call.startsWith('updateDrsPolicy:vmid-1:'))
assert.ok(updateCall)
assert.match(updateCall, /"policy_change_acknowledged":true/)
assert.match(updateCall, /"expected_observation":/)
assert.doesNotMatch(updateCall, /actor|updated_by|source|role|operator_id/)

const utilitySource = readFileSync(new URL('../src/utils/drsAdvisor.js', import.meta.url), 'utf8')
for (const forbidden of ['loadPlacementModel', 'buildPlacementViewModel', 'listNodes', 'listVms', 'listStorage', 'listNetworks']) {
  assert.ok(!utilitySource.includes(forbidden), `DRS Advisor utility must not use frontend-only Placement calculation or inventory endpoint ${forbidden}`)
}
assert.match(utilitySource, /getDrsSummary/)
assert.match(utilitySource, /listDrsRecommendations/)
assert.match(utilitySource, /getDrsRecommendation/)
assert.match(utilitySource, /checkDrsRecommendation/)
assert.match(utilitySource, /createDrsApprovalPacket/)
assert.match(utilitySource, /loadDrsPolicyCoverage/)
assert.match(utilitySource, /submitDrsPolicyUpdate/)
assert.match(utilitySource, /policy_change_acknowledged/)
assert.match(utilitySource, /expected_observation/)
assert.match(utilitySource, /canSubmitDrsApprovalPacket/)
assert.match(utilitySource, /warnings_not_acknowledged/)
assert.match(utilitySource, /warning_acknowledged/)
assert.doesNotMatch(utilitySource, /executeDrsMigrationJob|drsMigrationJobExecute/)

const screenSource = readFileSync(new URL('../src/components/DrsAdvisorScreen.jsx', import.meta.url), 'utf8')
assert.match(screenSource, /loadDrsAdvisorModel/)
assert.match(screenSource, /loadDrsRecommendationDetail/)
assert.match(screenSource, /checkDrsRecommendation/)
assert.match(screenSource, /Balance Overview/)
assert.match(screenSource, /RecommendationQueue/)
assert.match(screenSource, /Recommendation Queue/)
assert.match(screenSource, /PressureBar/)
assert.match(screenSource, /Source Pressure/)
assert.match(screenSource, /Target Pressure/)
assert.match(screenSource, /Projected Target/)
assert.match(screenSource, /Route Status/)
assert.match(screenSource, /Network evidence/)
assert.match(screenSource, /Storage evidence/)
assert.match(screenSource, /CompactBlockerList/)
assert.match(screenSource, /Detail/)
assert.match(screenSource, /Check/)
assert.match(screenSource, /Route Evidence/)
assert.match(screenSource, /Storage Evidence/)
assert.match(screenSource, /Passthrough Evidence/)
assert.match(screenSource, /Target Threshold/)
assert.match(screenSource, /Identity \/ Metadata \/ Policy/)
assert.match(screenSource, /Execution Boundary/)
assert.match(screenSource, /Final Pre-check/)
assert.match(screenSource, /Operation Lock Evidence/)
assert.match(screenSource, /Proxmox Conflict Evidence/)
assert.match(screenSource, /Approval Readiness/)
assert.match(screenSource, /VM Policy Configuration/)
assert.match(screenSource, /PolicyCoveragePanel/)
assert.match(screenSource, /PolicyReviewModal/)
assert.match(screenSource, /policyWriteBlockers/)
assert.match(screenSource, /policy_change_acknowledged|policyChangeAcknowledged/)
assert.match(screenSource, /Policy changes do not start migration/)
assert.match(screenSource, /migration approval remains separate/)
assert.match(screenSource, /Create approval packet/)
assert.match(screenSource, /canSubmitDrsApprovalPacket/)
assert.match(screenSource, /Jobs\/Runs/)
assert.match(screenSource, /executable false/)
assert.match(screenSource, /allowed actions: none/)
assert.match(screenSource, /allowed actions none/)
assert.doesNotMatch(screenSource, /Approve & Migrate/)
assert.doesNotMatch(screenSource, /executeDrsMigrationJob|drsMigrationJobExecute|\/execute/)
assert.doesNotMatch(screenSource, /actor:|updated_by:|operator_id|source:/)
assert.doesNotMatch(screenSource, /Recommendation Impact|RecommendationImpactList|RecommendationTable|<table|overflow-x-auto/)
assert.doesNotMatch(screenSource, /PlacementScreen|loadPlacementModel|placementToneClass/)

console.log('drsAdvisor RED contract exercised')
