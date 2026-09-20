import { metricsTargetMatches } from './model.js'

export const clusterMetrics = [
  { key: 'cpu_percent', label: '전체 CPU', unit: '%' },
  { key: 'memory_used_bytes', label: '전체 메모리 사용', unit: 'bytes' },
  { key: 'network_in_bytes_per_second', label: '전체 네트워크 수신', unit: 'bytes/s' },
  { key: 'network_out_bytes_per_second', label: '전체 네트워크 송신', unit: 'bytes/s' },
]
const keys = [...clusterMetrics.map(metric => metric.key), 'memory_total_bytes']
const valid = value => typeof value === 'number' && Number.isFinite(value) && value >= 0

export function aggregateValues(nodes, samples) {
  const weights = nodes.map(node => node.cpuTotal)
  const totalCpu = weights.reduce((sum, value) => sum + (valid(value) ? value : 0), 0)
  return Object.fromEntries(keys.map(key => {
    const values = samples.map(sample => sample?.[key])
    if (!nodes.length || samples.length !== nodes.length || !values.every(valid)) return [key, null]
    if (key === 'cpu_percent') {
      if (!weights.every(value => valid(value) && value > 0) || values.some(value => value > 100)) return [key, null]
      return [key, values.reduce((sum, value, index) => sum + value * weights[index], 0) / totalCpu]
    }
    return [key, values.reduce((sum, value) => sum + value, 0)]
  }))
}

export function aggregateClusterReports(nodes, results, timeframe, now = Date.now()) {
  const reports = nodes.map((node, index) => {
    const result = results[index]
    return result?.status === 'fulfilled' && metricsTargetMatches(result.value, 'node', node.id, '', timeframe) ? result.value : null
  })
  const failedNodes = nodes.filter((_, index) => !reports[index]?.current?.available || !reports[index]?.history?.available).map(node => node.name || node.id)
  const histories = reports.map(report => report?.history?.available ? report.history : null)
  const maps = histories.map(history => new Map((history?.points || []).map(point => [point.timestamp, point.values])))
  const timestamps = [...new Set(histories.flatMap(history => history?.points?.map(point => point.timestamp) || []))].sort((a, b) => a - b)
  const points = timestamps.map(timestamp => ({ timestamp, values: aggregateValues(nodes, maps.map(map => map.get(timestamp))) }))
  const resolution = histories[0]?.resolution_seconds
  const regular = resolution > 0 && histories.every(history => history?.resolution_seconds === resolution)
  const received = reports.map(report => report?.current?.received_at).filter(Boolean).sort()
  const values = aggregateValues(nodes, reports.map(report => report?.current?.available ? report.current.values : null))
  return {
    failedNodes, observedNodes: nodes.length - failedNodes.length,
    current: { available: reports.length > 0 && reports.every(report => report?.current?.available), values, received_at: received[0] },
    history: {
      available: histories.some(Boolean), points, start: timestamps[0], end: timestamps.at(-1),
      resolution_seconds: regular ? resolution : null,
      metrics: Object.fromEntries(keys.map(key => {
        const observed = points.filter(point => valid(point.values[key]))
        const latest = observed.at(-1)?.timestamp ?? null
        return [key, { observed_points: observed.length, missing_points: points.length - observed.length,
          latest_value_at: latest, stale: latest === null || !regular || now / 1000 - latest > resolution * 2 + 60 }]
      })),
    },
  }
}

// Keep requests bounded even when a connection includes many nodes.
export async function readClusterReports(nodes, timeframe, getMetrics, cancelled = () => false) {
  const results = new Array(nodes.length)
  let next = 0
  await Promise.all(Array.from({ length: Math.min(4, nodes.length) }, async () => {
    while (next < nodes.length && !cancelled()) {
      const index = next++
      try {
        const value = await getMetrics('node', nodes[index].id, '', timeframe)
        if (!metricsTargetMatches(value, 'node', nodes[index].id, '', timeframe)) throw new Error('노드 또는 기간 불일치')
        results[index] = { status: 'fulfilled', value }
      } catch (reason) { results[index] = { status: 'rejected', reason } }
    }
  }))
  return results
}
