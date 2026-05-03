export function summarizeProvisioningReadiness(readiness) {
  if (!readiness || typeof readiness !== 'object') {
    return {
      status: 'unknown',
      label: 'Readiness unknown',
      tone: 'gray',
      canProvision: false,
      counts: { ok: 0, warning: 0, error: 0, total: 0 },
      checks: [],
      nextActions: ['Run provisioning readiness check before creating a VM.'],
    }
  }

  const checks = Array.isArray(readiness.checks) ? readiness.checks : []
  const counts = checks.reduce(
    (acc, check) => {
      const status = check?.status || 'unknown'
      if (status === 'ok') acc.ok += 1
      if (status === 'warning') acc.warning += 1
      if (status === 'error') acc.error += 1
      acc.total += 1
      return acc
    },
    { ok: 0, warning: 0, error: 0, total: 0 }
  )

  const status = readiness.status || (counts.error > 0 ? 'error' : counts.warning > 0 ? 'warning' : 'ready')
  const toneByStatus = {
    ready: 'green',
    warning: 'yellow',
    error: 'red',
  }
  const labelByStatus = {
    ready: 'Ready',
    warning: 'Needs attention',
    error: 'Blocked',
  }

  const nextActions = Array.isArray(readiness.next_actions) && readiness.next_actions.length > 0
    ? readiness.next_actions
    : status === 'ready'
      ? ['Provisioning runtime is ready.']
      : ['Review failed readiness checks before provisioning.']

  return {
    status,
    label: labelByStatus[status] || 'Readiness unknown',
    tone: toneByStatus[status] || 'gray',
    canProvision: status === 'ready' || status === 'warning',
    counts,
    checks,
    summary: readiness.summary || '',
    nextActions,
  }
}
