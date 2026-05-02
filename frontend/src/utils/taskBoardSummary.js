const LIVE_STATUS = new Set(['pending', 'running', 'deploying', 'in_progress', 'processing'])
const DONE_STATUS = new Set(['success', 'completed', 'failed', 'error'])
const FAILED_STATUS = new Set(['failed', 'error'])

export function normalizeTaskStatus(status) {
  return String(status || '').toLowerCase()
}

export function isTaskLive(status) {
  return LIVE_STATUS.has(normalizeTaskStatus(status))
}

export function isTaskDone(status) {
  return DONE_STATUS.has(normalizeTaskStatus(status))
}

export function isTaskFailed(status) {
  return FAILED_STATUS.has(normalizeTaskStatus(status))
}

export function describeTaskTarget(task = {}) {
  const metadata = task.metadata || {}
  const name = metadata.vm_name || metadata.server_name || `instance-${String(task.task_id || 'unknown').slice(0, 8)}`
  const node = metadata.vm_node || metadata.server_id || metadata.node
  return node ? `${name} @ ${node}` : String(name)
}

export function buildTaskBoardSummary(tasks = []) {
  const items = Array.isArray(tasks) ? tasks : []
  return items.reduce(
    (acc, task) => {
      acc.total += 1
      if (isTaskLive(task.status)) acc.live += 1
      if (isTaskDone(task.status)) acc.done += 1
      if (isTaskFailed(task.status)) acc.failed += 1
      if (task.archived) acc.archived += 1
      return acc
    },
    { total: 0, live: 0, done: 0, failed: 0, archived: 0 },
  )
}

export function pickProvisioningMetadata(metadata = {}) {
  return {
    requestedName: metadata.server_name || '-',
    node: metadata.vm_node || metadata.server_id || '-',
    vmid: metadata.vm_id || '-',
    vmName: metadata.vm_name || '-',
    template: metadata.template_id || '-',
    storage: metadata.storage_id || '-',
    networks: Array.isArray(metadata.network_ids) ? metadata.network_ids : [],
    requestedIp: metadata.requested_vm_ip || metadata.vm_ip || '-',
    gateway: metadata.requested_vm_gateway || '-',
    packages: Array.isArray(metadata.ansible_packages) ? metadata.ansible_packages : [],
    roles: Array.isArray(metadata.ansible_roles) ? metadata.ansible_roles : [],
  }
}
