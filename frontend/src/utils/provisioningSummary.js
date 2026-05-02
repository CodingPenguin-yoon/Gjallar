const REQUIRED_FIELDS = [
  { id: 'node', label: 'node', configKey: 'selectedServerId' },
  { id: 'template', label: 'template', configKey: 'selectedTemplateId' },
  { id: 'storage', label: 'storage', configKey: 'selectedStorageId' },
  { id: 'network', label: 'network', configKey: 'selectedNetworkIds' },
]

function hasValue(value) {
  if (Array.isArray(value)) return value.length > 0
  return value !== undefined && value !== null && String(value).trim() !== ''
}

export function buildProvisioningSummary(config = {}) {
  const missingRequiredFields = REQUIRED_FIELDS
    .filter((field) => !hasValue(config[field.configKey]))
    .map((field) => field.label)

  const selectedPackages = Array.isArray(config.selectedPackages) ? config.selectedPackages : []
  const selectedRoles = Array.isArray(config.selectedRoles) ? config.selectedRoles : []
  const networkIds = Array.isArray(config.selectedNetworkIds) ? config.selectedNetworkIds : []
  const title = String(config.serverName || '').trim() || 'Auto-generated VM name'
  const ipMode = config.ipMode === 'static' ? 'static' : 'dhcp'

  return {
    title,
    ready: missingRequiredFields.length === 0,
    missingRequiredFields,
    target: {
      node: config.selectedServerId || '-',
      template: config.selectedTemplateId || '-',
      storage: config.selectedStorageId || '-',
    },
    resources: {
      cpuCores: config.cpuCores || 'template default',
      memoryGb: config.memory || 'template default',
    },
    network: {
      mode: ipMode,
      networks: networkIds,
      vmIp: ipMode === 'static' ? config.vmIp || '-' : 'DHCP',
      gateway: ipMode === 'static' ? config.vmGateway || '-' : '-',
    },
    bootstrap: {
      enabled: selectedPackages.length > 0 || selectedRoles.length > 0,
      packages: selectedPackages,
      roles: selectedRoles,
    },
  }
}

export function formatProvisioningMissingFields(fields = []) {
  if (!fields.length) return 'Ready to provision'
  return `Missing required selections: ${fields.join(', ')}`
}
