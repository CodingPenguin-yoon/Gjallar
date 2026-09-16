function normalizeHardwareLimit(source = {}) {
  const result = { default: Number(source.default), min: Number(source.min), max: Number(source.max) }
  return Object.values(result).every(Number.isFinite) && result.min > 0
    && result.min <= result.default && result.default <= result.max ? result : null
}

export function normalizeCreateVmProfiles(profiles = []) {
  const values = Array.isArray(profiles) ? profiles : (Array.isArray(profiles?.profiles) ? profiles.profiles : [])
  return values.map((profile) => {
    const profileId = profile.profile_id || profile.profileId || profile.id || ''
    const hardware = profile.hardware || {}
    const cpu = normalizeHardwareLimit(hardware.cpu)
    const memoryMb = normalizeHardwareLimit(hardware.memory_mb || hardware.memoryMb)
    const diskGb = normalizeHardwareLimit(hardware.disk_gb || hardware.diskGb)
    if (!profileId || !cpu || !memoryMb || !diskGb) return null
    const requirements = profile.template_requirements || profile.templateRequirements || {}
    const access = profile.access_recommendations || profile.accessRecommendations || {}
    return {
      id: profileId, profileId,
      displayName: profile.display_name || profile.displayName || profileId,
      displayNameKo: profile.display_name_ko || profile.displayNameKo || '',
      enabled: profile.enabled !== false,
      createEnabled: profile.create_enabled ?? profile.createEnabled ?? (profile.enabled !== false),
      hardware: { cpu, memoryMb, diskGb },
      templateRequirements: {
        requireCloudInit: requirements.require_cloud_init ?? requirements.requireCloudInit ?? true,
        requireQemuGuestAgent: requirements.require_qemu_guest_agent ?? requirements.requireQemuGuestAgent ?? true,
      },
      accessRecommendations: {
        defaultUser: access.default_user || access.defaultUser || '',
        requireSshKey: access.require_ssh_key ?? access.requireSshKey ?? true,
        allowPasswordLogin: access.allow_password_login ?? access.allowPasswordLogin ?? false,
        allowUserOverride: access.allow_user_override ?? access.allowUserOverride ?? true,
        sshKeySource: access.ssh_key_source || access.sshKeySource || 'request_or_backend_default',
      },
      source: profile.source || '', management: profile.management || '',
    }
  }).filter(Boolean)
}

export function resetHardwareForProfile(profile, templateDiskGb = 0) {
  return {
    cpu: profile.hardware.cpu.default,
    memoryMb: profile.hardware.memoryMb.default,
    diskGb: Math.max(profile.hardware.diskGb.default, Number(templateDiskGb || 0)),
  }
}

export function hardwareFromTemplate(template) {
  return { cpu: template?.cpu || '', memoryMb: template?.memoryMb || '', diskGb: template?.diskGb || '' }
}

export function buildCreateVmDefaults() {
  return {
    creationMode: 'template', profileId: '', hardware: hardwareFromTemplate(null),
    network: { ipMode: 'static', prefix: '', gateway: '' },
    access: {
      cloudInitUser: '', sshPublicKey: '', passwordLogin: false,
      requireSshKey: true, allowPasswordLogin: false, allowUserOverride: true,
      sshKeySource: 'request_or_backend_default',
    },
    profileOptions: [],
  }
}
