const LOCAL_PROFILE_OPTIONS = Object.freeze([
  {
    id: 'general-vm',
    profileId: 'general-vm',
    displayName: 'General VM',
    displayNameKo: '범용 VM',
    enabled: true,
    createEnabled: true,
    hardware: {
      cpu: { default: 2, min: 1, max: 8 },
      memoryMb: { default: 4096, min: 1024, max: 32768 },
      diskGb: { default: 50, min: 50, max: 500 },
    },
    templateRequirements: { requireCloudInit: true, requireQemuGuestAgent: true },
    accessRecommendations: {
      defaultUser: 'yoon',
      requireSshKey: true,
      allowPasswordLogin: false,
      allowUserOverride: true,
      sshKeySource: 'request_or_backend_default',
    },
    source: 'static_seed',
    management: 'read_only',
  },
  {
    id: 'runtime-server',
    profileId: 'runtime-server',
    displayName: 'Runtime Server',
    displayNameKo: '서비스 실행용 VM',
    enabled: true,
    createEnabled: true,
    hardware: {
      cpu: { default: 4, min: 2, max: 16 },
      memoryMb: { default: 8192, min: 4096, max: 65536 },
      diskGb: { default: 100, min: 80, max: 1000 },
    },
    templateRequirements: { requireCloudInit: true, requireQemuGuestAgent: true },
    accessRecommendations: {
      defaultUser: 'yoon',
      requireSshKey: true,
      allowPasswordLogin: false,
      allowUserOverride: true,
      sshKeySource: 'request_or_backend_default',
    },
    source: 'static_seed',
    management: 'read_only',
  },
  {
    id: 'development-vm',
    profileId: 'development-vm',
    displayName: 'Development VM',
    displayNameKo: '개발/테스트용 VM',
    enabled: true,
    createEnabled: true,
    hardware: {
      cpu: { default: 2, min: 1, max: 12 },
      memoryMb: { default: 4096, min: 2048, max: 32768 },
      diskGb: { default: 50, min: 50, max: 500 },
    },
    templateRequirements: { requireCloudInit: true, requireQemuGuestAgent: true },
    accessRecommendations: {
      defaultUser: 'yoon',
      requireSshKey: true,
      allowPasswordLogin: false,
      allowUserOverride: true,
      sshKeySource: 'request_or_backend_default',
    },
    source: 'static_seed',
    management: 'read_only',
  },
])

function cloneProfile(profile) {
  return {
    ...profile,
    hardware: {
      cpu: { ...profile.hardware.cpu },
      memoryMb: { ...profile.hardware.memoryMb },
      diskGb: { ...profile.hardware.diskGb },
    },
    templateRequirements: { ...profile.templateRequirements },
    accessRecommendations: { ...profile.accessRecommendations },
  }
}

function toNumber(value, fallback) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function normalizeHardwareLimit(source = {}, fallback) {
  return {
    default: toNumber(source.default, fallback.default),
    min: toNumber(source.min, fallback.min),
    max: toNumber(source.max, fallback.max),
  }
}

export function localCreateVmProfiles() {
  return LOCAL_PROFILE_OPTIONS.map(cloneProfile)
}

export function normalizeCreateVmProfiles(profiles = []) {
  const profileList = Array.isArray(profiles) ? profiles : (Array.isArray(profiles?.profiles) ? profiles.profiles : [])
  const localById = new Map(localCreateVmProfiles().map((profile) => [profile.profileId, profile]))
  const normalized = profileList
    .map((profile) => {
      const profileId = profile.profile_id || profile.profileId || profile.id || ''
      const fallback = localById.get(profileId) || localById.get('general-vm')
      const hardware = profile.hardware || {}
      const templateRequirements = profile.template_requirements || profile.templateRequirements || {}
      const accessRecommendations = profile.access_recommendations || profile.accessRecommendations || {}
      return {
        id: profile.id || profileId,
        profileId,
        displayName: profile.display_name || profile.displayName || fallback.displayName,
        displayNameKo: profile.display_name_ko || profile.displayNameKo || fallback.displayNameKo,
        enabled: profile.enabled !== false,
        createEnabled: profile.create_enabled ?? profile.createEnabled ?? (profile.enabled !== false),
        hardware: {
          cpu: normalizeHardwareLimit(hardware.cpu, fallback.hardware.cpu),
          memoryMb: normalizeHardwareLimit(hardware.memory_mb || hardware.memoryMb, fallback.hardware.memoryMb),
          diskGb: normalizeHardwareLimit(hardware.disk_gb || hardware.diskGb, fallback.hardware.diskGb),
        },
        templateRequirements: {
          requireCloudInit: templateRequirements.require_cloud_init ?? templateRequirements.requireCloudInit ?? true,
          requireQemuGuestAgent: templateRequirements.require_qemu_guest_agent ?? templateRequirements.requireQemuGuestAgent ?? true,
        },
        accessRecommendations: {
          defaultUser: accessRecommendations.default_user || accessRecommendations.defaultUser || 'yoon',
          requireSshKey: accessRecommendations.require_ssh_key ?? accessRecommendations.requireSshKey ?? true,
          allowPasswordLogin: accessRecommendations.allow_password_login ?? accessRecommendations.allowPasswordLogin ?? false,
          allowUserOverride: accessRecommendations.allow_user_override ?? accessRecommendations.allowUserOverride ?? true,
          sshKeySource: accessRecommendations.ssh_key_source || accessRecommendations.sshKeySource || fallback.accessRecommendations.sshKeySource,
        },
        source: profile.source || fallback.source,
        management: profile.management || fallback.management,
      }
    }).filter((profile) => profile.profileId)

  return normalized
}

export function hardwareDefaultsForProfile(profile) {
  const fallback = localCreateVmProfiles()[0]
  const selected = profile || fallback
  return {
    cpu: selected.hardware.cpu.default,
    memoryMb: selected.hardware.memoryMb.default,
    diskGb: selected.hardware.diskGb.default,
  }
}

export function resetHardwareForProfile(profile, templateDiskGb = 0) {
  const hardware = hardwareDefaultsForProfile(profile)
  const templateDisk = Number(templateDiskGb || 0)
  return templateDisk > hardware.diskGb ? { ...hardware, diskGb: templateDisk } : hardware
}

export function buildCreateVmDefaults() {
  const profileOptions = localCreateVmProfiles()
  const profile = profileOptions[0]
  return {
    profileId: profile.profileId,
    hardware: hardwareDefaultsForProfile(profile),
    network: {
      ipMode: 'static',
      prefix: '',
      gateway: '',
    },
    access: {
      cloudInitUser: 'yoon',
      sshPublicKey: '',
      passwordLogin: false,
      requireSshKey: profile.accessRecommendations.requireSshKey,
      allowPasswordLogin: profile.accessRecommendations.allowPasswordLogin,
      allowUserOverride: profile.accessRecommendations.allowUserOverride,
      sshKeySource: profile.accessRecommendations.sshKeySource,
    },
    profileOptions,
  }
}
