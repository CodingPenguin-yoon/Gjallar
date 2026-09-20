export function formatMetric(value, unit) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '관찰 없음'
  if (unit === '%') return `${value.toFixed(1)}%`
  if (unit === 'bytes' || unit === 'bytes/s') {
    const sizes = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
    const exponent = value > 0 ? Math.min(4, Math.floor(Math.log(value) / Math.log(1024))) : 0
    return `${(value / 1024 ** Math.max(0, exponent)).toFixed(1)} ${sizes[Math.max(0, exponent)]}${unit === 'bytes/s' ? '/s' : ''}`
  }
  return String(value)
}

export function chartSegments(points, metric, resolution, minimumMaximum = 1) {
  const observed = points.filter(point => typeof point.values[metric] === 'number' && Number.isFinite(point.values[metric]))
  if (!observed.length) return { segments: [], maximum: null }
  const maximum = Math.max(minimumMaximum, ...observed.map(point => point.values[metric]))
  const first = points[0].timestamp
  const span = Math.max(1, points.at(-1).timestamp - first)
  const segments = []
  let segment = []
  let previous = null
  for (const point of points) {
    const value = point.values[metric]
    const valid = typeof value === 'number' && Number.isFinite(value)
    const gap = previous !== null && (!resolution || point.timestamp - previous > resolution * 1.5)
    if (!valid || gap) {
      if (segment.length) segments.push(segment)
      segment = []
    }
    if (valid) segment.push({ x: 20 + (point.timestamp - first) / span * 760, y: 180 - value / maximum * 160 })
    previous = point.timestamp
  }
  if (segment.length) segments.push(segment)
  return { segments, maximum }
}

export function metricsTargetMatches(report, kind, node, resource, timeframe) {
  return report?.target?.kind === kind && report.target.node_id === node && report.timeframe === timeframe
    && (kind !== 'vm' || String(report.target.vmid) === String(resource))
    && (kind !== 'storage' || report.target.storage_id === resource)
}
