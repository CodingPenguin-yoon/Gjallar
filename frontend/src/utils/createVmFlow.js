const LIVE_RUN_DISABLED_REASON = '실제 VM 생성은 별도 승인 단계에서만 실행됩니다.'

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

function normalizeReadiness(readiness = {}) {
  return {
    sharedRoot: readiness.shared_root || '',
    iacRoot: readiness.iac_root || '',
    terraformStateRoot: readiness.terraform_state_root || '',
    riskLevel: readiness.risk_level || 'unknown',
    readyForPlan: readiness.ready_for_plan === true,
    readyForExecute: readiness.ready_for_execute === true,
    checks: Array.isArray(readiness.checks) ? readiness.checks : [],
    risks: Array.isArray(readiness.risks) ? readiness.risks : [],
    sideEffects: Array.isArray(readiness.side_effects) ? readiness.side_effects : [],
  }
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
    ['storage_id', input.storageId ?? input.storage_id],
    ['network_id', input.networkId ?? input.network_id ?? input.network?.networkId ?? input.network?.network_id],
    ['bridge_id', input.bridgeId ?? input.bridge_id ?? input.network?.bridgeId ?? input.network?.bridge_id],
    ['static_ip', input.staticIp ?? input.static_ip],
    ['ip_mode', input.ipMode ?? input.ip_mode ?? input.network?.ipMode],
    ['template_id', input.templateId ?? input.template_id ?? input.template?.templateId ?? input.template?.template_id],
    ['template_vmid', input.templateVmid ?? input.template_vmid ?? input.template?.vmid],
    ['template_node_id', input.templateNodeId ?? input.template_node_id ?? input.template?.nodeId ?? input.template?.node_id],
  ])
}

export function buildCreateVmInputFromConfig(config = {}, fallback = {}) {
  return {
    operatorId: config.operatorId || fallback.operatorId || 'ui-operator',
    jobId: config.jobId || fallback.jobId || `ui-${Date.now()}`,
    targetNodeId: config.targetNodeId || config.selectedServerId || fallback.targetNodeId || 'yoonmanserver2',
    storageId: config.storageId || config.storage_id || fallback.storageId || '',
    networkId: config.networkId || config.network?.networkId || fallback.networkId || 'server-net',
    bridgeId: config.bridgeId || config.network?.bridgeId || fallback.bridgeId || '',
    staticIp: config.staticIp || config.network?.staticIp || fallback.staticIp || '',
    ipMode: config.ipMode || config.network?.ipMode || fallback.ipMode || 'static',
    templateId: config.templateId || config.template?.templateId || fallback.templateId || '',
    templateVmid: config.templateVmid || config.template?.vmid || fallback.templateVmid || '',
    templateNodeId: config.templateNodeId || config.template?.nodeId || fallback.templateNodeId || '',
    templateKey: config.templateKey || fallback.templateKey || '',
  }
}

export async function loadCreateVmReviewModel(client, input = {}) {
  const payload = buildCreateVmPayload(input)
  const readiness = typeof client.getVmCreateReadiness === 'function'
    ? normalizeReadiness(await client.getVmCreateReadiness())
    : normalizeReadiness()
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
      storageId: draft.storage_id || plan.storage_id || payload.storage_id,
      templateId: draft.template_id || plan.template_id || payload.template_id,
      templateVmid: draft.template_vmid ?? plan.template_vmid ?? payload.template_vmid,
      templateNodeId: draft.template_node_id || plan.template_node_id || payload.template_node_id,
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
      iacRoot: review.iac_root || plan.iac_root || preflight.iac_root || readiness.iacRoot,
      terraformStateRoot: review.terraform_state_root || plan.terraform_state_root || preflight.terraform_state_root || readiness.terraformStateRoot,
      iacReadyForPlan: review.iac_ready_for_plan ?? plan.iac_ready_for_plan ?? preflight.iac_ready_for_plan ?? readiness.readyForPlan,
      iacReadyForExecute: review.iac_ready_for_execute ?? plan.iac_ready_for_execute ?? preflight.iac_ready_for_execute ?? readiness.readyForExecute,
      firstPowerOnIncluded: Boolean(review.first_power_on_included ?? plan.first_power_on_included ?? draft.first_power_on_included),
      smokeTimeoutSummary: summarizeSmokeTimeouts(review.smoke_timeout_summary || plan.smoke_timeout_summary),
      risks,
      riskLevel: plan.risk_summary?.level || preflight.risk_level || 'unknown',
      planArtifactId: review.plan_artifact_id || planArtifact?.id || '',
      planArtifactLink: planArtifact?.path || '',
      plannedGitDiffSummary: review.planned_git_diff_summary || '',
      reviewSummaryChecksum: review.review_summary_checksum || '',
      canApprove,
      canPrepareTerraformPlan: canApprove && Boolean(review.iac_ready_for_plan ?? plan.iac_ready_for_plan ?? preflight.iac_ready_for_plan ?? readiness.readyForPlan),
      canCommitManifest: canApprove && Boolean(review.iac_ready_for_execute ?? plan.iac_ready_for_execute ?? preflight.iac_ready_for_execute ?? readiness.readyForExecute),
      canApplyTerraform: canApprove && Boolean(review.iac_ready_for_plan ?? plan.iac_ready_for_plan ?? preflight.iac_ready_for_plan ?? readiness.readyForPlan) && Boolean(review.iac_ready_for_execute ?? plan.iac_ready_for_execute ?? preflight.iac_ready_for_execute ?? readiness.readyForExecute),
      canExecute: false,
      executeDisabledReason: LIVE_RUN_DISABLED_REASON,
    },
    artifacts,
    readiness,
    sideEffects: [
      ...readiness.sideEffects,
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
    ? '승인되었습니다.'
    : `승인할 수 없습니다: ${reason}`

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

export async function commitCreateVmManifest(client, model, options = {}) {
  const payload = {
    ...(model.payload || {}),
    plan_artifact_id: model.review?.planArtifactId || '',
    review_summary_checksum: model.review?.reviewSummaryChecksum || '',
    yellow_risk_acknowledged: options.yellowRiskAcknowledged === true,
  }
  const response = await client.commitVmDraftManifest(model.draft.id, payload)
  return {
    status: 'committed',
    tone: 'green',
    commitSha: response.commit_sha || '',
    manifestPath: response.manifest_path || '',
    manifestStatus: response.manifest_status || {},
    applyEnabled: response.terraform_apply_enabled === true,
    proxmoxMutationEnabled: response.proxmox_mutation_enabled === true,
    sideEffects: Array.isArray(response.side_effects) ? response.side_effects : [],
    operatorMessage: `생성 요청이 저장되었습니다: ${response.manifest_path || response.commit_sha || 'commit created'}`,
    raw: response,
  }
}

export async function prepareCreateVmTerraformPlan(client, model, options = {}) {
  const payload = {
    ...(model.payload || {}),
    plan_artifact_id: model.review?.planArtifactId || '',
    review_summary_checksum: model.review?.reviewSummaryChecksum || '',
    yellow_risk_acknowledged: options.yellowRiskAcknowledged === true,
    run_terraform_plan: options.runTerraformPlan === true,
    terraform_plan_acknowledged: options.terraformPlanAcknowledged === true,
  }
  const response = await client.prepareVmDraftTerraformPlan(model.draft.id, payload)
  const commands = Array.isArray(response.commands) ? response.commands : []
  const commandText = commands.map((command) => Array.isArray(command) ? command.join(' ') : String(command)).join('\n')
  return {
    status: response.terraform_plan_ran ? 'planned' : 'prepared',
    tone: 'blue',
    workspaceDir: response.workspace_dir || '',
    terraformDir: response.terraform_dir || '',
    tfvarsPath: response.tfvars_path || '',
    statePath: response.state_path || '',
    planPath: response.plan_path || '',
    commandText,
    planRan: response.terraform_plan_ran === true,
    planResults: Array.isArray(response.terraform_plan_results) ? response.terraform_plan_results : [],
    applyEnabled: response.terraform_apply_enabled === true,
    proxmoxMutationEnabled: response.proxmox_mutation_enabled === true,
    sideEffects: Array.isArray(response.side_effects) ? response.side_effects : [],
    operatorMessage: response.terraform_plan_ran
      ? 'Terraform 검토가 완료되었습니다.'
      : 'Terraform 파일이 준비되었습니다.',
    raw: response,
  }
}

export async function applyCreateVmTerraformPlan(client, model, options = {}) {
  const payload = {
    ...(model.payload || {}),
    plan_artifact_id: model.review?.planArtifactId || '',
    review_summary_checksum: model.review?.reviewSummaryChecksum || '',
    yellow_risk_acknowledged: options.yellowRiskAcknowledged === true,
    manifest_commit_sha: options.manifestCommitSha || '',
    expected_plan_path: options.expectedPlanPath || '',
    terraform_plan_acknowledged: options.terraformPlanAcknowledged === true,
    terraform_apply_acknowledged: options.terraformApplyAcknowledged === true,
    proxmox_mutation_acknowledged: options.proxmoxMutationAcknowledged === true,
  }
  const response = await client.applyVmDraftTerraformPlan(model.draft.id, payload)
  const results = Array.isArray(response.terraform_apply_results) ? response.terraform_apply_results : []
  return {
    status: response.terraform_apply_ran ? 'applied' : 'blocked',
    tone: response.terraform_apply_ran ? 'green' : 'red',
    workspaceDir: response.workspace_dir || '',
    terraformDir: response.terraform_dir || '',
    statePath: response.state_path || '',
    manifestPath: response.manifest_path || '',
    manifestCommitSha: response.manifest_commit_sha || '',
    manifestStatus: response.manifest_status || {},
    manifestStatusCommitSha: response.manifest_status_commit_sha || '',
    applyEnabled: response.terraform_apply_enabled === true,
    proxmoxMutationEnabled: response.proxmox_mutation_enabled === true,
    sideEffects: Array.isArray(response.side_effects) ? response.side_effects : [],
    results,
    stdout: results.map((item) => item.stdout || '').filter(Boolean).join('\n'),
    operatorMessage: response.terraform_apply_ran
      ? 'VM 생성 apply가 실행되었습니다.'
      : 'VM 생성 apply가 실행되지 않았습니다.',
    raw: response,
  }
}

export { LIVE_RUN_DISABLED_REASON }
