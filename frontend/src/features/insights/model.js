import { normalizeInsightsSnapshot } from '../../entities/insight/model.js'

export async function loadInsightsModel(client) {
  return normalizeInsightsSnapshot(await client.getInsights())
}

export function selectExactTargetFindingView(
  sections,
  { targetType = '', targetId = '', findingId = '' } = {},
) {
  const normalizedSections = Array.isArray(sections) ? sections : []
  if (!targetType || !targetId) {
    return { sections: normalizedSections, requestedFindingMatched: !findingId }
  }

  const exactTargetSections = normalizedSections.map((section) => ({
    ...section,
    findings: section.findings.filter((finding) => (
      finding.targetType === targetType && finding.targetId === targetId
    )),
  }))
  const requestedFindingMatched = !findingId || exactTargetSections.some((section) => (
    section.findings.some((finding) => finding.id === findingId)
  ))

  if (!findingId || !requestedFindingMatched) {
    return { sections: exactTargetSections, requestedFindingMatched }
  }
  return {
    sections: exactTargetSections.map((section) => ({
      ...section,
      findings: section.findings.filter((finding) => finding.id === findingId),
    })),
    requestedFindingMatched,
  }
}
