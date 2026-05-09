const KNOWN_RISK_LEVELS = new Set(['green', 'yellow', 'red'])

function normalizeRiskLevel(level) {
  return typeof level === 'string' ? level.trim().toLowerCase() : ''
}

function normalizeRisks(risks) {
  return risks.map((risk) => ({
    ...risk,
    rawLevel: risk?.level,
    normalizedLevel: normalizeRiskLevel(risk?.level),
  }))
}

function hasRiskLevel(risks, level) {
  return risks.some((risk) => risk.normalizedLevel === level)
}

function findUnknownRisk(risks) {
  return risks.find(
    (risk) => typeof risk.rawLevel !== 'string' || !KNOWN_RISK_LEVELS.has(risk.normalizedLevel),
  )
}

function hasOwnInputValue(input, key) {
  return Object.prototype.hasOwnProperty.call(input, key)
}

export function evaluateRiskApprovalPolicy(input = {}) {
  const { yellowRiskAcknowledged = false } = input
  const risksInput = hasOwnInputValue(input, 'risks') ? input.risks : []

  if (!Array.isArray(risksInput)) {
    return {
      canApprove: false,
      canExecute: false,
      requiresYellowAck: false,
      reason: 'malformed risk payload: risks must be an array',
    }
  }

  const normalizedRisks = normalizeRisks(risksInput)

  if (hasRiskLevel(normalizedRisks, 'red')) {
    return {
      canApprove: false,
      canExecute: false,
      requiresYellowAck: false,
      reason: 'red risk blocks approval and execution in the MVP policy',
    }
  }

  const unknownRisk = findUnknownRisk(normalizedRisks)
  if (unknownRisk) {
    return {
      canApprove: false,
      canExecute: false,
      requiresYellowAck: false,
      reason: `unknown or malformed risk level blocks approval: ${unknownRisk.rawLevel ?? 'missing'}`,
    }
  }

  if (hasRiskLevel(normalizedRisks, 'yellow') && !yellowRiskAcknowledged) {
    return {
      canApprove: false,
      canExecute: false,
      requiresYellowAck: true,
      reason: 'yellow risk requires explicit acknowledgement before approval',
    }
  }

  return {
    canApprove: true,
    canExecute: true,
    requiresYellowAck: false,
    reason: 'risk policy allows approval',
  }
}
