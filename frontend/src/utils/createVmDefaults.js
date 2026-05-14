const GENERAL_VM_PROFILE = {
  profileId: 'general-vm',
  label: 'General VM',
  createEnabled: true,
}

export function buildCreateVmDefaults() {
  return {
    profileId: GENERAL_VM_PROFILE.profileId,
    hardware: {
      cpu: 2,
      memoryMb: 4096,
      diskGb: 50,
    },
    network: {
      ipMode: 'static',
      prefix: '',
      gateway: '',
    },
    access: {
      cloudInitUser: 'yoon',
      passwordLogin: false,
    },
    profileOptions: [{ ...GENERAL_VM_PROFILE }],
  }
}
