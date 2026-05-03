export const DEFAULT_DISK_SIZE_GB = 50

function parsePositiveInt(value, fallback = undefined) {
  const parsed = parseInt(value, 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

export function buildProvisioningResourcePreflightPayload(config = {}) {
  if (config.server_id) {
    return {
      server_id: config.server_id,
      template_id: config.template_id,
      storage_id: config.storage_id,
      network_ids: config.network_ids || [],
      server_name: config.server_name,
      vmid: config.vmid,
      disk_size_gb: parsePositiveInt(config.disk_size_gb, DEFAULT_DISK_SIZE_GB),
      vm_ip: config.vm_ip,
      vm_gateway: config.vm_gateway,
    }
  }

  return {
    server_id: config.selectedServerId,
    template_id: config.selectedTemplateId,
    storage_id: config.selectedStorageId,
    network_ids: config.selectedNetworkIds || [],
    server_name: config.serverName,
    vmid: config.vmid,
    disk_size_gb: parsePositiveInt(config.diskSize, DEFAULT_DISK_SIZE_GB),
    vm_ip: config.vmIp,
    vm_gateway: config.vmGateway,
  }
}

export function buildProvisioningPayload(config = {}) {
  if (config.server_id) {
    return {
      server_id: config.server_id,
      template_id: config.template_id,
      storage_id: config.storage_id,
      storage_type: config.storage_type,
      network_ids: config.network_ids,
      server_name: config.server_name,
      cpu_cores: config.cpu_cores,
      memory_gb: config.memory_gb,
      disk_size_gb: parsePositiveInt(config.disk_size_gb, DEFAULT_DISK_SIZE_GB),
      ansible_packages: config.ansible_packages || [],
      ansible_roles: config.ansible_roles || [],
      vm_ip: config.vm_ip,
      vm_gateway: config.vm_gateway,
    }
  }

  return {
    server_id: config.selectedServerId,
    template_id: config.selectedTemplateId,
    server_name: config.serverName || `instance-${Date.now()}`,
    cpu_cores: parsePositiveInt(config.cpuCores),
    memory_gb: parsePositiveInt(config.memory),
    disk_size_gb: parsePositiveInt(config.diskSize, DEFAULT_DISK_SIZE_GB),
    storage_id: config.selectedStorageId,
    network_ids: config.selectedNetworkIds || [],
    vm_ip: config.vmIp,
    vm_gateway: config.vmGateway,
    ansible_packages: config.selectedPackages || [],
    ansible_roles: config.selectedRoles || [],
  }
}
