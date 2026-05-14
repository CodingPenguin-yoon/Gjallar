const LIVE_RUN_DISABLED_REASON = '실제 VM 생성은 요청 저장 후 Proxmox native create에서만 실행됩니다.'

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

function toSnakeHardware(hardware = {}) {
  const payload = pickDefined([
    ['cpu', hardware.cpu],
    ['memory_mb', hardware.memory_mb ?? hardware.memoryMb],
    ['disk_gb', hardware.disk_gb ?? hardware.diskGb],
  ])
  return Object.keys(payload).length ? payload : undefined
}

function toSnakeAccess(input = {}) {
  const access = input.access || {}
  const payload = pickDefined([
    ['cloud_init_user', input.cloudInitUser ?? input.cloud_init_user ?? input.username ?? access.cloudInitUser ?? access.cloud_init_user ?? access.username],
    ['ssh_public_key', input.sshPublicKey ?? input.ssh_public_key ?? access.sshPublicKey ?? access.ssh_public_key],
    ['password_login', false],
  ])
  return Object.keys(payload).length ? payload : undefined
}

function normalizeAccessEvidence(access = {}) {
  const username = access.username || access.cloud_init_user || access.cloudInitUser || ''
  const fingerprint = access.fingerprint || access.ssh_key_fingerprint || access.sshKeyFingerprint || ''
  return {
    username,
    cloudInitUser: username,
    passwordLogin: access.password_login ?? access.passwordLogin ?? false,
    sshKeyPresent: access.ssh_key_present ?? access.sshKeyPresent ?? Boolean(fingerprint),
    sshKeyValid: access.ssh_key_valid ?? access.sshKeyValid ?? Boolean(fingerprint),
    fingerprint,
    source: access.source || access.ssh_key_source || access.sshKeySource || '',
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

function readinessReady(value) {
  return value === true
}

function normalizeTemplateRequirements(profile = {}) {
  const requirements = profile.template_requirements || profile.templateRequirements || {}
  return {
    requireCloudInit: requirements.require_cloud_init ?? requirements.requireCloudInit ?? true,
    requireQemuGuestAgent: requirements.require_qemu_guest_agent ?? requirements.requireQemuGuestAgent ?? true,
  }
}

export function normalizeTemplateOptions(templates = []) {
  return Array.isArray(templates)
    ? templates
      .map((template) => {
        const vmid = template.vmid ?? template.template_vmid
        const nodeId = template.node_id || template.nodeId || ''
        const templateId = template.template_id || template.templateId || template.name || ''
        const cloudInitReady = readinessReady(template.cloud_init_ready ?? template.cloudInitReady)
        const guestAgentReady = readinessReady(template.guest_agent_ready ?? template.guestAgentReady)
        return {
          key: nodeId && vmid ? `${nodeId}/${vmid}` : templateId,
          templateId,
          vmid,
          nodeId,
          name: template.name || templateId,
          family: template.family || '',
          cpu: Number(template.cpu ?? 0),
          memoryMb: Number(template.memory_mb ?? template.memoryMb ?? 0),
          diskGb: Number(template.disk_gb ?? template.diskGb ?? 0),
          cloudInitReady,
          guestAgentReady,
          ready: cloudInitReady && guestAgentReady,
        }
      })
      .filter((template) => template.key)
      .sort((left, right) => `${left.nodeId}/${left.vmid}`.localeCompare(`${right.nodeId}/${right.vmid}`, undefined, { numeric: true }))
    : []
}

export function templateRequirementFailures(template, profile = {}) {
  const requirements = normalizeTemplateRequirements(profile)
  const failures = []
  if (requirements.requireCloudInit && template?.cloudInitReady !== true) {
    failures.push({ code: 'cloud_init_required', label: 'cloud-init 필요' })
  }
  if (requirements.requireQemuGuestAgent && template?.guestAgentReady !== true) {
    failures.push({ code: 'guest_agent_required', label: 'guest-agent 필요' })
  }
  return failures
}

export function templateRequirementStatus(template, profile = {}) {
  const failures = templateRequirementFailures(template, profile)
  return {
    disabled: failures.length > 0,
    passes: failures.length === 0,
    failures,
    reason: failures.map((failure) => failure.label).join(', '),
  }
}

export function decorateTemplateOptionsForProfile(templates = [], profile = {}) {
  return (Array.isArray(templates) ? templates : []).map((template) => {
    const status = templateRequirementStatus(template, profile)
    return {
      ...template,
      disabled: status.disabled,
      disabledReason: status.reason,
      requirementFailures: status.failures,
    }
  })
}

export function selectPreferredTemplate(templates = [], profile = {}, currentKey = '') {
  const decorated = decorateTemplateOptionsForProfile(templates, profile)
  const current = decorated.find((template) => template.key === currentKey)
  if (current && !current.disabled) return current
  return decorated.find((template) => !template.disabled) || null
}

export function validateTemplateSelection(templates = [], profile = {}, selectedKey = '') {
  const decorated = decorateTemplateOptionsForProfile(templates, profile)
  const passing = decorated.filter((template) => !template.disabled)
  const selected = decorated.find((template) => template.key === selectedKey) || null
  if (!decorated.length) {
    return { ok: false, reason: '템플릿 인벤토리가 비어 있습니다.', selected: null, options: decorated }
  }
  if (!passing.length) {
    return { ok: false, reason: '선택한 프로필 요구사항을 만족하는 템플릿이 없습니다.', selected: null, options: decorated }
  }
  if (!selected) {
    return { ok: false, reason: '요구사항을 만족하는 템플릿을 선택하세요.', selected: null, options: decorated }
  }
  if (selected.disabled) {
    return { ok: false, reason: `선택한 템플릿은 ${selected.disabledReason} 조건을 만족하지 않습니다.`, selected, options: decorated }
  }
  return { ok: true, reason: '', selected, options: decorated }
}

export function buildCreateVmPayload(input = {}) {
  return pickDefined([
    ['operator_id', input.operatorId ?? input.operator_id],
    ['job_id', input.jobId ?? input.job_id],
    ['profile_id', input.profileId ?? input.profile_id],
    ['target_node_id', input.targetNodeId ?? input.target_node_id],
    ['storage_id', input.storageId ?? input.storage_id],
    ['bridge_id', input.bridgeId ?? input.bridge_id ?? input.network?.bridgeId ?? input.network?.bridge_id],
    ['static_ip', input.staticIp ?? input.static_ip ?? input.network?.staticIp ?? input.network?.static_ip],
    ['prefix', input.prefix ?? input.network?.prefix],
    ['gateway', input.gateway ?? input.network?.gateway],
    ['ip_mode', input.ipMode ?? input.ip_mode ?? input.network?.ipMode ?? input.network?.ip_mode],
    ['template_id', input.templateId ?? input.template_id ?? input.template?.templateId ?? input.template?.template_id],
    ['template_vmid', input.templateVmid ?? input.template_vmid ?? input.template?.vmid],
    ['template_node_id', input.templateNodeId ?? input.template_node_id ?? input.template?.nodeId ?? input.template?.node_id],
    ['hardware_overrides', toSnakeHardware(input.hardware || input.hardware_overrides || {})],
    ['access', toSnakeAccess(input)],
  ])
}

export function buildCreateVmInputFromConfig(config = {}, fallback = {}) {
  return {
    operatorId: config.operatorId || fallback.operatorId || 'ui-operator',
    jobId: config.jobId || fallback.jobId || `ui-${Date.now()}`,
    profileId: config.profileId || config.profile_id || fallback.profileId || 'general-vm',
    targetNodeId: config.targetNodeId || config.selectedServerId || fallback.targetNodeId || 'yoonmanserver2',
    storageId: config.storageId || config.storage_id || fallback.storageId || '',
    bridgeId: config.bridgeId || config.bridge_id || config.network?.bridgeId || config.network?.bridge_id || fallback.bridgeId || '',
    staticIp: config.staticIp || config.static_ip || config.network?.staticIp || config.network?.static_ip || fallback.staticIp || '',
    prefix: config.prefix || config.network?.prefix || fallback.prefix || '',
    gateway: config.gateway || config.network?.gateway || fallback.gateway || '',
    ipMode: config.ipMode || config.ip_mode || config.network?.ipMode || config.network?.ip_mode || fallback.ipMode || 'static',
    templateId: config.templateId || config.template?.templateId || fallback.templateId || '',
    templateVmid: config.templateVmid || config.template?.vmid || fallback.templateVmid || '',
    templateNodeId: config.templateNodeId || config.template?.nodeId || fallback.templateNodeId || '',
    templateKey: config.templateKey || fallback.templateKey || '',
    cloudInitUser: config.cloudInitUser || config.cloud_init_user || config.username || config.access?.cloudInitUser || config.access?.cloud_init_user || config.access?.username || fallback.cloudInitUser || 'yoon',
    sshPublicKey: config.sshPublicKey || config.ssh_public_key || config.access?.sshPublicKey || config.access?.ssh_public_key || fallback.sshPublicKey || '',
    passwordLogin: false,
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
  const accessEvidence = normalizeAccessEvidence(review.access || plan.access || preflight.access || draft.access || {})
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
      profileId: draft.profile_id || payload.profile_id,
      vmName: draft.vm_name || review.vm_name || plan.vm_name,
      vmid: draft.proposed_vmid ?? plan.vmid,
      targetNodeId: draft.target_node_id || plan.target_node_id || payload.target_node_id,
      storageId: draft.storage_id || plan.storage_id || payload.storage_id,
      templateId: draft.template_id || plan.template_id || payload.template_id,
      templateVmid: draft.template_vmid ?? plan.template_vmid ?? payload.template_vmid,
      templateNodeId: draft.template_node_id || plan.template_node_id || payload.template_node_id,
      access: normalizeAccessEvidence(draft.access || {}),
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
      profileId: review.profile_id || plan.profile_id || draft.profile_id || payload.profile_id,
      vmName: review.vm_name || plan.vm_name || draft.vm_name,
      vmid: review.vmid ?? plan.vmid ?? draft.proposed_vmid,
      targetNode: review.target_node_id || plan.target_node_id || draft.target_node_id,
      storage: review.storage_id || plan.storage_id,
      template: review.template_id || plan.template_id,
      hardware: toCamelHardware(review.hardware || plan.hardware || draft.hardware),
      profileHardwareLimits: review.profile_hardware_limits || plan.profile_hardware_limits || {},
      network: review.network || plan.network || draft.network || {},
      access: accessEvidence,
      iacRoot: review.iac_root || plan.iac_root || preflight.iac_root || readiness.iacRoot,
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
      canPreviewProxmox: canApprove,
      canCommitManifest: canApprove && Boolean(review.iac_ready_for_execute ?? plan.iac_ready_for_execute ?? preflight.iac_ready_for_execute ?? readiness.readyForExecute),
      canCreateProxmox: canApprove && Boolean(review.iac_ready_for_execute ?? plan.iac_ready_for_execute ?? preflight.iac_ready_for_execute ?? readiness.readyForExecute),
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
    createEnabled: response.proxmox_create_enabled === true,
    proxmoxMutationEnabled: response.proxmox_mutation_enabled === true,
    sideEffects: Array.isArray(response.side_effects) ? response.side_effects : [],
    operatorMessage: `생성 요청이 저장되었습니다: ${response.manifest_path || response.commit_sha || 'commit created'}`,
    raw: response,
  }
}

export async function previewCreateVmProxmox(client, model, options = {}) {
  const payload = {
    ...(model.payload || {}),
    plan_artifact_id: model.review?.planArtifactId || '',
    review_summary_checksum: model.review?.reviewSummaryChecksum || '',
    yellow_risk_acknowledged: options.yellowRiskAcknowledged === true,
  }
  const response = await client.previewVmDraftProxmox(model.draft.id, payload)
  return {
    status: 'previewed',
    tone: 'blue',
    clone: response.clone || {},
    config: response.config || {},
    postCheck: response.post_check || {},
    artifacts: Array.isArray(response.artifacts) ? response.artifacts : [],
    createEnabled: response.proxmox_create_enabled === true,
    proxmoxMutationEnabled: response.proxmox_mutation_enabled === true,
    sideEffects: Array.isArray(response.side_effects) ? response.side_effects : [],
    operatorMessage: 'Proxmox native 생성 미리보기가 준비되었습니다.',
    raw: response,
  }
}

export async function createVmWithProxmox(client, model, options = {}) {
  const payload = {
    ...(model.payload || {}),
    plan_artifact_id: model.review?.planArtifactId || '',
    review_summary_checksum: model.review?.reviewSummaryChecksum || '',
    yellow_risk_acknowledged: options.yellowRiskAcknowledged === true,
    manifest_commit_sha: options.manifestCommitSha || '',
    proxmox_mutation_acknowledged: options.proxmoxMutationAcknowledged === true,
  }
  const response = await client.createVmDraftProxmox(model.draft.id, payload)
  const created = response.proxmox_create_ran === true && response.proxmox_create_status === 'applied'
  const observedAfterArtifact = response.observed_after_artifact || null
  return {
    status: created ? 'applied' : (response.status || 'blocked'),
    tone: created ? 'green' : 'red',
    manifestPath: response.manifest_path || '',
    manifestCommitSha: response.manifest_commit_sha || '',
    manifestStatus: response.manifest_status || {},
    manifestStatusCommitSha: response.manifest_status_commit_sha || '',
    createEnabled: response.proxmox_create_enabled === true,
    proxmoxMutationEnabled: response.proxmox_mutation_enabled === true,
    observedAfter: response.observed_after || null,
    observedAfterArtifact,
    observedAfterPath: observedAfterArtifact?.path || '',
    fingerprintHash: response.observed_after?.fingerprint?.hash || '',
    sideEffects: Array.isArray(response.side_effects) ? response.side_effects : [],
    operatorMessage: created
      ? 'VM이 꺼진 상태로 생성되고 확인되었습니다.'
      : 'VM 생성 확인이 완료되지 않았습니다.',
    raw: response,
  }
}

export { LIVE_RUN_DISABLED_REASON }
