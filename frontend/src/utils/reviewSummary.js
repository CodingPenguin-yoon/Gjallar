import { evaluateRiskApprovalPolicy } from './riskPolicy.js'

const REQUIRED_ITEM_BUILDERS = [
  ['vm_name', 'VM name', (input) => input.vmName],
  ['vmid', 'VMID', (input) => input.vmid],
  ['target_node', 'Target node', (input) => input.targetNode],
  ['storage', 'Storage', (input) => input.storage],
  ['template', 'Template', (input) => input.template],
  ['hardware', 'Hardware', (input) => {
    const hardware = input.hardware || {}
    if ([hardware.cpu, hardware.memoryMb, hardware.diskGb].some(isMissingRequiredValue)) return undefined
    return `${hardware.cpu} CPU / ${hardware.memoryMb} MB / ${hardware.diskGb} GB`
  }],
  ['network_ip', 'Network/IP', (input) => {
    const network = input.network || {}
    const mode = network.mode || network.ipMode
    const bridgeOrNetwork = network.bridge || network.networkId
    if ([mode, bridgeOrNetwork].some(isMissingRequiredValue)) return undefined
    return `${mode} / ${bridgeOrNetwork}`
  }],
  ['terraform_state_path', 'Terraform state path', (input) => input.terraformStatePath],
  ['first_power_on', 'First power-on', (input) => (
    typeof input.firstPowerOnIncluded === 'boolean'
      ? (input.firstPowerOnIncluded ? 'included' : 'not included')
      : undefined
  )],
  ['smoke_timeout_summary', 'Smoke timeout summary', (input) => input.smokeTimeoutSummary],
  ['risk_summary', 'Risk summary', (input) => summarizeRisks(input.risks)],
  ['plan_artifact_link', 'Plan artifact', (input) => input.planArtifactLink],
  ['planned_git_diff_summary', 'Planned Git diff', (input) => input.plannedGitDiffSummary],
]

function summarizeRisks(risks = []) {
  if (!Array.isArray(risks)) return 'malformed risk payload'
  if (risks.length === 0) return 'green / no blocking risks'
  return risks.map((risk) => `${risk?.level || 'unknown'}:${risk?.code || 'unknown'}`).join(', ')
}

function isMissingRequiredValue(value) {
  return value === undefined || value === null || String(value).trim() === ''
}

function hasOwnInputValue(input, key) {
  return Object.prototype.hasOwnProperty.call(input, key)
}

export function buildReviewConfirmSummary(input = {}) {
  const requiredItems = REQUIRED_ITEM_BUILDERS.map(([id, label, buildValue]) => ({
    id,
    label,
    value: buildValue(input),
  }))
  const missingRequiredItemIds = requiredItems
    .filter((item) => isMissingRequiredValue(item.value))
    .map((item) => item.id)

  const risksForDecision = hasOwnInputValue(input, 'risks') ? input.risks : []
  const decision = evaluateRiskApprovalPolicy({
    risks: risksForDecision,
    yellowRiskAcknowledged: Boolean(input.yellowRiskAcknowledged),
  })
  const hasMissingRequiredItems = missingRequiredItemIds.length > 0
  const canApprove = decision.canApprove && !hasMissingRequiredItems
  const canExecute = decision.canExecute && !hasMissingRequiredItems

  return {
    requiredItems,
    missingRequiredItemIds,
    risks: Array.isArray(risksForDecision) ? risksForDecision : [],
    canApprove,
    canExecute,
    requiresYellowAck: decision.requiresYellowAck,
    decisionReason: hasMissingRequiredItems
      ? `missing required review items: ${missingRequiredItemIds.join(', ')}`
      : decision.reason,
  }
}
