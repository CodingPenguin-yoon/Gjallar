export function toNumber(value, fallback = 0) {
  const number = typeof value === 'number' ? value : Number.parseFloat(value || fallback)
  return Number.isFinite(number) ? number : fallback
}

export function getResourceTone(percent) {
  const value = toNumber(percent)
  if (value >= 90) {
    return { level: 'critical', label: 'Critical', barClass: 'bg-red-500', textClass: 'text-red-700', bgClass: 'bg-red-50 border-red-200' }
  }
  if (value >= 70) {
    return { level: 'warning', label: 'Warning', barClass: 'bg-yellow-500', textClass: 'text-yellow-700', bgClass: 'bg-yellow-50 border-yellow-200' }
  }
  return { level: 'healthy', label: 'Healthy', barClass: 'bg-green-500', textClass: 'text-green-700', bgClass: 'bg-green-50 border-green-200' }
}

function buildNodeSignals(node = {}) {
  const signals = []
  const nodeName = node.name || node.node || 'unknown-node'
  if (String(node.status || '').toLowerCase() !== 'online') {
    signals.push({ level: 'critical', label: `${nodeName} is ${node.status || 'offline'}` })
  }

  const cpuTone = getResourceTone(node.cpu_usage_percent)
  if (cpuTone.level !== 'healthy') {
    signals.push({ level: cpuTone.level, label: `${nodeName} CPU ${toNumber(node.cpu_usage_percent).toFixed(1)}%` })
  }

  const memoryTone = getResourceTone(node.memory_usage_percent)
  if (memoryTone.level !== 'healthy') {
    signals.push({ level: memoryTone.level, label: `${nodeName} memory ${toNumber(node.memory_usage_percent).toFixed(1)}%` })
  }

  for (const storage of node.storages || []) {
    const storageTone = getResourceTone(storage.usage_percent)
    if (storageTone.level !== 'healthy') {
      signals.push({
        level: storageTone.level,
        label: `${nodeName}/${storage.name || storage.storage || 'storage'} ${toNumber(storage.usage_percent).toFixed(1)}%`,
      })
    }
  }
  return signals
}

export function buildMonitoringSummary(nodes = []) {
  const items = Array.isArray(nodes) ? nodes : []
  const signals = items.flatMap(buildNodeSignals)
  const criticalSignals = signals.filter((signal) => signal.level === 'critical').length
  const warningSignals = signals.filter((signal) => signal.level === 'warning').length
  return {
    totalNodes: items.length,
    onlineNodes: items.filter((node) => String(node.status || '').toLowerCase() === 'online').length,
    criticalSignals,
    warningSignals,
    signals,
  }
}
