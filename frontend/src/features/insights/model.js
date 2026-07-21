import { normalizeInsightsSnapshot } from '../../entities/insight/model.js'

export async function loadInsightsModel(client) {
  return normalizeInsightsSnapshot(await client.getInsights())
}
