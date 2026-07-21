import { InsightsExplorer } from '../../features/insights'

export default function InsightsPage({ category = 'overview' }) {
  return <InsightsExplorer activeCategory={category} />
}
