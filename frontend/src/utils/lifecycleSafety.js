const ACTION_POLICIES = {
  start: {
    action: 'start',
    label: 'Start',
    severity: 'low',
    typedConfirmation: false,
    risk: 'Power on the VM. This is usually safe but may start services or consume node resources.',
  },
  shutdown: {
    action: 'shutdown',
    label: 'Shutdown',
    severity: 'medium',
    typedConfirmation: false,
    risk: 'Ask the guest OS to shut down gracefully. Services inside the VM will become unavailable.',
  },
  reboot: {
    action: 'reboot',
    label: 'Reboot',
    severity: 'medium',
    typedConfirmation: false,
    risk: 'Restart the VM. Running services will be interrupted until the VM is back online.',
  },
  stop: {
    action: 'stop',
    label: 'Stop',
    severity: 'high',
    typedConfirmation: false,
    risk: 'Force power off the VM. This can interrupt writes and may cause application or filesystem issues.',
  },
  terminate: {
    action: 'terminate',
    label: 'Terminate',
    severity: 'critical',
    typedConfirmation: true,
    risk: 'Shutdown, force stop if needed, and permanently delete the VM. This action cannot be undone from Gjallar.',
  },
}

export function getInstanceDisplayName(instance) {
  return instance?.name || instance?.server_name || `VM ${instance?.vmid || ''}`.trim() || 'unknown VM'
}

export function getLifecycleActionPolicy(action) {
  const policy = ACTION_POLICIES[action]
  if (policy) {
    return {
      action: policy.action,
      label: policy.label,
      severity: policy.severity,
      typedConfirmation: policy.typedConfirmation,
    }
  }
  return {
    action,
    label: action || 'Action',
    severity: 'medium',
    typedConfirmation: false,
  }
}

export function requiresTypedConfirmation(action) {
  return Boolean(ACTION_POLICIES[action]?.typedConfirmation)
}

export function buildLifecycleConfirmation({ instance, action }) {
  const rawPolicy = ACTION_POLICIES[action] || {
    action,
    label: action || 'Action',
    severity: 'medium',
    typedConfirmation: false,
    risk: 'This changes VM runtime state.',
  }
  const name = getInstanceDisplayName(instance)
  const node = instance?.node || 'unknown-node'
  const vmid = instance?.vmid ?? instance?.vm_id ?? instance?.id ?? 'unknown-vmid'
  const status = instance?.status || 'unknown'
  const requiredTypedValue = rawPolicy.typedConfirmation ? name : null

  return {
    action: rawPolicy.action,
    title: `${rawPolicy.label} VM ${name}?`,
    confirmText: rawPolicy.label,
    severity: rawPolicy.severity,
    requiredTypedValue,
    message: [
      rawPolicy.risk,
      '',
      `Target: ${name}`,
      `Location: ${node}/${vmid}`,
      `Current status: ${status}`,
      requiredTypedValue ? `Type exactly "${requiredTypedValue}" to continue.` : 'Confirm only if this is the intended VM.',
    ].join('\n'),
  }
}
