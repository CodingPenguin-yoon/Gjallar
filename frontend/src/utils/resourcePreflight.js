export function summarizeResourcePreflight(preflight) {
  if (!preflight || typeof preflight !== 'object') {
    return {
      status: 'unknown',
      label: 'Resource check unknown',
      tone: 'gray',
      canProvision: false,
      counts: { ok: 0, warning: 0, error: 0, total: 0 },
      checks: [],
      summary: '',
      nextActions: ['Run resource preflight after selecting node/template/storage/network.'],
    }
  }

  const checks = Array.isArray(preflight.checks) ? preflight.checks : []
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

  const status = preflight.status || (counts.error > 0 ? 'error' : counts.warning > 0 ? 'warning' : 'ready')
  const toneByStatus = {
    ready: 'green',
    warning: 'yellow',
    error: 'red',
  }
  const labelByStatus = {
    ready: 'Resources ready',
    warning: 'Review resources',
    error: 'Resource blocked',
  }

  const nextActions = Array.isArray(preflight.next_actions) && preflight.next_actions.length > 0
    ? preflight.next_actions
    : status === 'ready'
      ? ['Selected Proxmox resources are ready.']
      : ['Review failed resource checks before provisioning.']

  return {
    status,
    label: labelByStatus[status] || 'Resource check unknown',
    tone: toneByStatus[status] || 'gray',
    canProvision: status === 'ready' || status === 'warning',
    counts,
    checks,
    summary: preflight.summary || '',
    nextActions,
  }
}
