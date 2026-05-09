const LIVE_RUN_DISABLED_REASON = 'execute requires explicit live approval outside this MVP UI slice'

function present(value) {
  return value !== undefined && value !== null && String(value).trim() !== ''
}

function pickDefined(entries) {
  return Object.fromEntries(entries.filter(([, value]) => value !== undefined && value !== null && String(value).trim?.() !== ''))
}

function toCamelHardware(hardware = {}) {
  return {
    cpu: hardware.cpu,
    memoryMb: hardware.memory_mb ?? hardware.memoryMb,
    diskGb: hardware.disk_gb ?? hardware.diskGb,
  }
}

function normalizeArtifacts(artifacts = []) {
  return Array.isArray(artifacts)
    ? artifacts.map((artifact) => ({
      id: artifact.artifact_id || artifact.id || artifact.path || 'artifact',
      type: artifact.type || artifact.kind || 'artifact',
      path: artifact.path || '',
      checksum: artifact.checksum || '',
      readOnly: true,
      allowedActions: [],
    }))
    : []
}

function summarizeSmokeTimeouts(summary = {}) {
  if (!summary || typeof summary !== 'object') return ''
  return Object.entries(summary)
    .map(([key, value]) => `${key.replace(/_/g, ' ')}: ${value}m`)
    .join(', ')
}

function risksFromPlan(plan = {}) {
  const riskSummary = plan.risk_summary || {}
  const red = Array.isArray(riskSummary.red) ? riskSummary.red : []
  const yellow = Array.isArray(riskSummary.yellow) ? riskSummary.yellow : []
  return [...red, ...yellow]
}

export function buildCreateVmPayload(input = {}) {
  return pickDefined([
    ['operator_id', input.operatorId ?? input.operator_id],
    ['job_id', input.jobId ?? input.job_id],
    ['target_node_id', input.targetNodeId ?? input.target_node_id],
    ['static_ip', input.staticIp ?? input.static_ip],
    ['ip_mode', input.ipMode ?? input.ip_mode ?? input.network?.ipMode],
  ])
}

export function buildCreateVmInputFromConfig(config = {}, fallback = {}) {
  return {
    operatorId: config.operatorId || fallback.operatorId || 'ui-operator',
    jobId: config.jobId || fallback.jobId || `ui-${Date.now()}`,
    targetNodeId: config.targetNodeId || config.selectedServerId || fallback.targetNodeId || 'yoonmanserver2',
    staticIp: config.staticIp || config.network?.staticIp || fallback.staticIp || '',
    ipMode: config.ipMode || config.network?.ipMode || fallback.ipMode || 'static',
  }
}

export async function loadCreateVmReviewModel(client, input = {}) {
  const payload = buildCreateVmPayload(input)
  const draft = await client.createVmDraft(payload)
  const draftId = draft.draft_id || draft.id
  const preflight = await client.preflightVmDraft(draftId, payload)
  const plan = await client.planVmDraft(draftId, payload)
  const review = plan.review_confirm || {}
  const artifacts = normalizeArtifacts(plan.artifacts)
  const planArtifact = artifacts.find((artifact) => artifact.type === 'plan') || artifacts[0] || null
  const risks = risksFromPlan(plan)
  const hasReviewMetadata = present(review.plan_artifact_id) && present(review.review_summary_checksum)
  const canApprove = hasReviewMetadata && (plan.risk_summary?.level || preflight.risk_level) !== 'red'

  return {
    payload,
    draft: {
      id: draftId,
      jobId: draft.job_id || payload.job_id,
      operatorId: draft.operator_id || payload.operator_id,
      vmName: draft.vm_name || review.vm_name || plan.vm_name,
      vmid: draft.proposed_vmid ?? plan.vmid,
      targetNodeId: draft.target_node_id || plan.target_node_id || payload.target_node_id,
      sideEffects: Array.isArray(draft.side_effects) ? draft.side_effects : [],
    },
    preflight: {
      level: preflight.risk_level || 'unknown',
      checks: Array.isArray(preflight.checks) ? preflight.checks : [],
      risks: Array.isArray(preflight.risks) ? preflight.risks : [],
      sideEffects: Array.isArray(preflight.side_effects) ? preflight.side_effects : [],
    },
    plan: {
      executionIntent: plan.execution_intent || 'dry_run_plan_only',
      raw: plan,
    },
    review: {
      vmName: review.vm_name || plan.vm_name || draft.vm_name,
      vmid: review.vmid ?? plan.vmid ?? draft.proposed_vmid,
      targetNode: review.target_node_id || plan.target_node_id || draft.target_node_id,
      storage: review.storage_id || plan.storage_id,
      template: review.template_id || plan.template_id,
      hardware: toCamelHardware(review.hardware || plan.hardware || draft.hardware),
      network: review.network || plan.network || draft.network || {},
      terraformStatePath: review.terraform_state_path || plan.terraform_state_path || draft.terraform_state_path,
      firstPowerOnIncluded: Boolean(review.first_power_on_included ?? plan.first_power_on_included ?? draft.first_power_on_included),
      smokeTimeoutSummary: summarizeSmokeTimeouts(review.smoke_timeout_summary || plan.smoke_timeout_summary),
      risks,
      riskLevel: plan.risk_summary?.level || preflight.risk_level || 'unknown',
      planArtifactId: review.plan_artifact_id || planArtifact?.id || '',
      planArtifactLink: planArtifact?.path || '',
      plannedGitDiffSummary: review.planned_git_diff_summary || '',
      reviewSummaryChecksum: review.review_summary_checksum || '',
      canApprove,
      canExecute: false,
      executeDisabledReason: LIVE_RUN_DISABLED_REASON,
    },
    artifacts,
    sideEffects: [
      ...(Array.isArray(draft.side_effects) ? draft.side_effects : []),
      ...(Array.isArray(preflight.side_effects) ? preflight.side_effects : []),
      ...(Array.isArray(plan.side_effects) ? plan.side_effects : []),
    ],
    readOnlyUntilApproval: true,
  }
}

export async function approveCreateVmReview(client, model, options = {}) {
  const payload = {
    ...(model.payload || {}),
    plan_artifact_id: model.review?.planArtifactId || '',
    review_summary_checksum: model.review?.reviewSummaryChecksum || '',
    yellow_risk_acknowledged: options.yellowRiskAcknowledged === true,
  }
  const response = await client.approveVmDraft(model.draft.id, payload)
  const canApprove = response.can_approve === true
  const requiresYellowAck = response.requires_yellow_ack === true
  const reason = response.reason || response.approval_record?.decision || 'approval validation completed'
  const status = canApprove ? 'approved' : 'blocked'
  const tone = canApprove ? 'green' : (requiresYellowAck ? 'yellow' : 'red')
  const operatorMessage = canApprove
    ? `Approval validated: ${reason}`
    : `Approval not approved: ${reason}`

  return {
    canApprove,
    canExecute: false,
    requiresYellowAck,
    reason,
    status,
    tone,
    operatorMessage,
    approvalRecord: response.approval_record || null,
    sideEffects: Array.isArray(response.side_effects) ? response.side_effects : [],
    executeDisabledReason: LIVE_RUN_DISABLED_REASON,
  }
}

export { LIVE_RUN_DISABLED_REASON }
