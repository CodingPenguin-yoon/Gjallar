export function normalizeOperationalStatus(status) {
  return String(status ?? '').trim().toLowerCase()
}

function numericValue(...candidates) {
  for (const candidate of candidates) {
    const parsed = Number(candidate)
    if (Number.isFinite(parsed)) {
      return parsed
    }
  }
  return 0
}

function diskTotalGb(instance) {
  const disks = Array.isArray(instance?.disks) ? instance.disks : []
  if (disks.length > 0) {
    return disks.reduce((sum, disk) => sum + numericValue(disk?.size_gb, disk?.sizeGb), 0)
  }
  return numericValue(instance?.disk_gb, instance?.diskGb)
}

export function hasVisibleIp(instance) {
  if (instance?.primary_ip) {
    return true
  }
  const addresses = Array.isArray(instance?.ip_addresses) ? instance.ip_addresses : []
  return addresses.some(Boolean)
}

export function buildInventorySummary(instances = []) {
  const safeInstances = Array.isArray(instances) ? instances : []

  return safeInstances.reduce(
    (summary, instance) => {
      const status = normalizeOperationalStatus(instance?.status)
      const visibleIp = hasVisibleIp(instance)

      summary.total += 1
      summary.cpuCores += numericValue(instance?.cpu_cores, instance?.cpu)
      summary.memoryGb += numericValue(instance?.memory_gb, instance?.memory)
      summary.diskGb += diskTotalGb(instance)

      if (status === 'running') {
        summary.running += 1
      } else if (status === 'stopped') {
        summary.stopped += 1
      } else {
        summary.unknown += 1
      }

      if (visibleIp) {
        summary.visibleIpCount += 1
      } else {
        summary.missingIpCount += 1
      }

      return summary
    },
    {
      total: 0,
      running: 0,
      stopped: 0,
      unknown: 0,
      visibleIpCount: 0,
      missingIpCount: 0,
      cpuCores: 0,
      memoryGb: 0,
      diskGb: 0,
    }
  )
}

export function getInstanceOperationalSignals(instance) {
  const status = normalizeOperationalStatus(instance?.status)
  const signals = []

  if (status === 'running' && !hasVisibleIp(instance)) {
    signals.push({
      tone: 'warning',
      label: 'No IP visible',
      detail: 'Running VM has no discovered IP address',
    })
  }

  return signals
}
