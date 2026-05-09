import { buildRisksViewModel } from './apiV1ViewModels.js'

const READ_ONLY_ACTIONS = Object.freeze([])
const LEVEL_RANK = Object.freeze({ red: 0, yellow: 1, unknown: 2, green: 3 })

function rankRisk(risk) {
  return LEVEL_RANK[risk.level] ?? LEVEL_RANK.unknown
}

export async function loadRisksScreenModel(client) {
  if (!client || typeof client.listRisks !== 'function') {
    throw new Error('Risks screen requires an /api/v1 client with listRisks()')
  }
  const risks = await client.listRisks()
  const model = buildRisksViewModel(risks)
  const items = [...model.items].sort((left, right) => {
    const rankDelta = rankRisk(left) - rankRisk(right)
    if (rankDelta !== 0) return rankDelta
    return String(left.code).localeCompare(String(right.code), undefined, { sensitivity: 'base' })
  })
  return {
    readOnly: true,
    allowedActions: READ_ONLY_ACTIONS,
    summary: model.summary,
    items,
  }
}

export function riskLevelLabel(level) {
  const normalized = String(level ?? '').toLowerCase()
  if (normalized === 'red') return 'Red'
  if (normalized === 'yellow') return 'Yellow'
  if (normalized === 'green') return 'Green'
  return 'Unknown'
}

export function riskToneClass(level) {
  const normalized = String(level ?? '').toLowerCase()
  if (normalized === 'red') return 'border-red-200 bg-red-50 text-red-800'
  if (normalized === 'yellow') return 'border-amber-200 bg-amber-50 text-amber-800'
  if (normalized === 'green') return 'border-green-200 bg-green-50 text-green-800'
  return 'border-slate-200 bg-slate-50 text-slate-800'
}
